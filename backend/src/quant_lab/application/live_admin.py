"""실제로 따라 사기 관리 (실거래 R2): 켜기·끄기, 승인·안 사기, 비상 중지, 조회.

화면(API)·CLI가 부른다. DB만 바꾸고 증권사는 부르지 않는다
(주문은 Worker의 LiveDesk가 낸다, 원칙 6).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.application.bots import require_bot
from quant_lab.application.errors import Conflict, Invalid, NotFound
from quant_lab.application.live import control, has_unknown, last_close, live_event, month_bought
from quant_lab.domain.events import (
    ConfigChange,
    ConfigChangeData,
    EventKind,
    LiveControlData,
)
from quant_lab.domain.live import (
    RATIOS,
    LiveLimits,
    LiveState,
    RealFill,
    RealLedger,
    SkipReason,
    over_account_limit,
    real_ledger,
)
from quant_lab.persistence.bots import add_event, drop_unsent_live_orders
from quant_lab.persistence.models import BotRow, BrokerAccountRow, LiveControlRow, LiveOrderRow

RECENT = 20
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class LiveOrderInfo:
    id: int
    bot_id: int | None
    bot_name: str | None
    symbol: str
    side: str
    quantity: Decimal | None
    signal_date: date
    trade_date: date
    amount: Decimal
    state: str
    reason: str | None
    filled_qty: Decimal | None
    filled_amount: Decimal | None
    carried_into: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LiveOverview:
    trader: str | None  # 실거래 스위치가 켜졌으면 증권사 출처 코드
    halted: bool
    per_order: Decimal
    per_month: Decimal
    account_month: Decimal  # 계좌 전체 한 달 상한 (승인해도 넘을 수 없다)
    ratios: list[str]  # 고를 수 있는 비율 이름 (1/100)
    # 봇이 낸 실제 주문의 장부 (체결 기준, 수수료 제외 어림값). 최근 주문 목록과 별개로 모두 더한다
    bought_this_month: Decimal  # 이번 달 산 금액
    sold_this_month: Decimal  # 이번 달 판 금액
    sold_total: Decimal  # 지금까지 판 금액 (0이면 팔아 본 적이 없다)
    realized_this_month: Decimal  # 이번 달 팔아서 확정된 손익
    realized_total: Decimal  # 지금까지 확정 손익
    held_cost: Decimal  # 봇이 산 채로 들고 있는 주식의 원가
    held_value: Decimal  # 그 주식의 지금 값 (토스 현재가, 없으면 최근 종가)
    shortfall: list[dict[str, str]]  # 실제 계좌 대조: 보유가 봇이 산 수량보다 적은 종목
    checked_at: datetime | None  # 마지막 대조 시각
    unknown_order_ids: list[int]  # 오래되거나 삭제한 봇의 불명 주문도 빠뜨리지 않는다
    orders: list[LiveOrderInfo]  # 불명 주문 전부 + 최근 실제 주문 (불명·승인 기다림이 먼저)


def _ledger(session: Session) -> RealLedger:
    """체결된 실제 주문(일부 체결 뒤 취소 포함)을 거래일·번호 순으로 장부에 넣는다."""
    rows = session.scalars(
        select(LiveOrderRow)
        .where(
            LiveOrderRow.filled_qty > 0,
            LiveOrderRow.state.in_([LiveState.FILLED, LiveState.CANCELED]),
        )
        .order_by(LiveOrderRow.trade_date, LiveOrderRow.id)
    )
    return real_ledger(
        [
            RealFill(
                o.bot_id,
                o.symbol,
                o.side,
                o.filled_qty or Decimal(0),
                o.filled_amount if o.filled_amount is not None else o.amount,
                o.trade_date.strftime("%Y-%m"),
            )
            for o in rows
        ]
    )


def _held(session: Session, held: dict[str, tuple[Decimal, Decimal]]) -> tuple[Decimal, Decimal]:
    """봇이 산 채로 들고 있는 주식의 (원가, 지금 값). 값은 토스 현재가, 없으면 최근 종가로 본다."""
    account = session.get(BrokerAccountRow, 1)
    prices = {
        h["symbol"]: Decimal(h["last_price"]) for h in (account.holdings if account else []) if h
    }
    cost = value = Decimal(0)
    for symbol, (qty, symbol_cost) in held.items():
        price = prices.get(symbol) or last_close(session, symbol)
        cost += symbol_cost
        value += qty * price if price else symbol_cost  # 가격을 모르면 손익 0으로 둔다
    return cost, value


def overview(session: Session) -> LiveOverview:
    row = session.get(LiveControlRow, 1)
    names = {b.id: b.name for b in session.scalars(select(BotRow))}
    rows = list(
        session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id.desc()).limit(RECENT))
    )
    unknown = list(
        session.scalars(
            select(LiveOrderRow)
            .where(LiveOrderRow.state == LiveState.UNKNOWN)
            .order_by(LiveOrderRow.id)
        )
    )
    known_ids = {o.id for o in rows}
    rows.extend(o for o in unknown if o.id not in known_ids)
    rows.sort(key=lambda o: (o.state != LiveState.UNKNOWN, o.state != LiveState.WAITING_APPROVAL))
    limits = LiveLimits()
    month = datetime.now(KST).strftime("%Y-%m")
    ledger = _ledger(session)
    held_cost, held_value = _held(session, ledger.held)
    return LiveOverview(
        trader=row.trader if row else None,
        halted=bool(row and row.halted),
        per_order=limits.per_order,
        per_month=limits.per_month,
        account_month=limits.account_month,
        ratios=list(RATIOS),
        bought_this_month=ledger.bought.get(month, Decimal(0)),
        sold_this_month=ledger.sold.get(month, Decimal(0)),
        sold_total=sum(ledger.sold.values(), Decimal(0)),
        realized_this_month=ledger.realized.get(month, Decimal(0)),
        realized_total=sum(ledger.realized.values(), Decimal(0)),
        held_cost=held_cost,
        held_value=held_value,
        shortfall=list(row.shortfall or []) if row else [],
        checked_at=row.checked_at if row else None,
        unknown_order_ids=[o.id for o in unknown],
        orders=[
            LiveOrderInfo(
                o.id,
                o.bot_id,
                names.get(o.bot_id) if o.bot_id else None,
                o.symbol,
                o.side,
                o.quantity,
                o.signal_date,
                o.trade_date,
                o.amount,
                o.state,
                o.reason,
                o.filled_qty,
                o.filled_amount,
                o.carried_into,
                o.created_at,
                o.updated_at,
            )
            for o in rows
        ],
    )


def set_bot_ratio(session: Session, bot_id: int, ratio: str | None, now: datetime) -> BotRow:
    """따라 하기 비율을 켜고(1/100) 끈다(None). 켜면 그때부터의 새 모의 주문만 따라 한다.

    나 카피 봇은 매달 사기만, AI 봇은 사기와 일부 팔기를 따라 한다.
    """
    bot = require_bot(session, bot_id, for_update=True)
    if ratio is not None and ratio not in RATIOS:
        raise Invalid("실제 돈은 1/100로만 따라 해요.")
    value = RATIOS[ratio] if ratio else None
    if value == bot.live_ratio:
        return bot
    before = str(bot.live_ratio) if bot.live_ratio is not None else None
    if value is None:
        drop_unsent_live_orders(session, bot.id, now)
    else:
        bot.live_since = now
    bot.live_ratio, bot.updated_at = value, now
    add_event(
        session,
        now,
        "INFO",
        EventKind.CONFIG_CHANGE,
        f"실제로 따라 사기: {before} → {value}",
        bot_id=bot.id,
        data=ConfigChangeData(
            change=ConfigChange.LIVE,
            before={"live_ratio": before},
            after={"live_ratio": str(value) if value is not None else None},
        ),
    )
    session.commit()
    return bot


def _order(session: Session, order_id: int) -> LiveOrderRow:
    order = session.get(LiveOrderRow, order_id, with_for_update=True)
    if order is None:
        raise NotFound("실제 주문이 없습니다")
    return order


def approve(session: Session, order_id: int, now: datetime) -> LiveOrderRow:
    ctl = control(session, now)
    order = _order(session, order_id)
    if order.state != LiveState.WAITING_APPROVAL:
        raise Conflict("이미 처리된 주문이에요")
    if ctl.halted:
        raise Conflict("실제 주문을 멈춰 둔 동안에는 승인할 수 없어요")
    if has_unknown(session):
        raise Conflict("결과를 확인하지 못한 실제 주문이 있어요. 먼저 주문 결과를 확인해 주세요")
    limits = LiveLimits()
    if order.side == "BUY" and over_account_limit(
        order.amount, month_bought(session, order.trade_date, exclude_id=order.id), limits
    ):
        raise Conflict(
            f"이번 달 계좌 전체 한도(${limits.account_month:f})를 넘어서 승인할 수 없어요"
        )
    order.state, order.updated_at = LiveState.APPROVED, now
    live_event(session, now, order)
    session.commit()
    return order


def resolve_unknown(
    session: Session, order_id: int, now: datetime, *, broker_order_id: str | None
) -> None:
    """주문 번호는 조회의 단서만 저장한다. 미접수 확인은 기록을 남기고 이번 몫을 넘긴다."""
    control(session, now)
    order = _order(session, order_id)
    if order.state != LiveState.UNKNOWN:
        raise Conflict("확인이 필요한 주문이 아니에요")
    if broker_order_id is not None:
        broker_order_id = broker_order_id.strip()
        if not broker_order_id or len(broker_order_id) > 64:
            raise Invalid("증권사 주문 번호를 입력해 주세요 (64자 이하)")
        linked = session.scalar(
            select(LiveOrderRow.id)
            .where(
                LiveOrderRow.id != order.id,
                LiveOrderRow.source == order.source,
                LiveOrderRow.broker_order_id == broker_order_id,
            )
            .limit(1)
        )
        if linked is not None:
            raise Conflict("다른 실제 주문에 연결된 번호예요")
        order.broker_order_id = broker_order_id
        order.note = "사용자가 주문 번호 지정; Worker의 증권사 조회 확인 대기"
    else:
        order.state, order.reason = LiveState.SKIPPED, SkipReason.CONFIRMED_NOT_PLACED
        order.note = "사용자가 증권사 주문 내역·보유를 확인해 미접수로 정리"
        order.broker_order_id = None
    order.updated_at = now
    live_event(session, now, order, manual_resolution=True)
    session.commit()


def decline(session: Session, order_id: int, now: datetime) -> LiveOrderRow:
    order = _order(session, order_id)
    if order.state not in (LiveState.WAITING_APPROVAL, LiveState.APPROVED):
        raise Conflict("이미 보냈거나 처리된 주문이에요")
    order.state, order.reason, order.updated_at = LiveState.SKIPPED, SkipReason.DECLINED, now
    live_event(session, now, order)
    session.commit()
    return order


def set_halted(session: Session, halted: bool, now: datetime) -> None:
    """비상 중지: 켜 있는 동안 새 실제 주문을 보내지 않는다 (이미 보낸 주문은 체결을 계속 확인)."""
    row = control(session, now)
    if row.halted == halted:
        return
    row.halted, row.updated_at = halted, now
    row.halted_at = now if halted else None
    add_event(
        session,
        now,
        "WARN" if halted else "INFO",
        EventKind.LIVE_CONTROL,
        f"실제 주문 {'멈춤' if halted else '다시 시작'}",
        data=LiveControlData(halted=halted),
    )
    session.commit()
