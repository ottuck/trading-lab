"""실제로 따라 사기 관리 (실거래 R2): 켜기·끄기, 승인·안 사기, 비상 중지, 조회.

화면(API)·CLI가 부른다. DB만 바꾸고 증권사는 부르지 않는다
(주문은 Worker의 LiveDesk가 낸다, 원칙 6).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.application.bots import require_bot
from quant_lab.application.dry_run import build_strategy
from quant_lab.application.errors import Conflict, Invalid, NotFound
from quant_lab.application.live import control, live_event
from quant_lab.domain.events import (
    ConfigChange,
    ConfigChangeData,
    EventKind,
    LiveControlData,
)
from quant_lab.domain.live import AUTO_AFTER, RATIOS, LiveLimits, LiveState, SkipReason
from quant_lab.domain.strategy import deposit_plan
from quant_lab.persistence.bots import add_event, drop_unsent_live_orders
from quant_lab.persistence.models import BotRow, LiveControlRow, LiveOrderRow

RECENT = 20


@dataclass(frozen=True)
class LiveOrderInfo:
    id: int
    bot_id: int | None
    bot_name: str | None
    symbol: str
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
    auto_after: int
    per_order: Decimal
    per_month: Decimal
    ratios: list[str]  # 고를 수 있는 비율 이름 (1/100, 1/10)
    shortfall: list[dict[str, str]]  # 실제 계좌 대조: 보유가 봇이 산 수량보다 적은 종목
    checked_at: datetime | None  # 마지막 대조 시각
    orders: list[LiveOrderInfo]  # 최근 실제 주문 (승인 기다림이 먼저)


def overview(session: Session) -> LiveOverview:
    row = session.get(LiveControlRow, 1)
    names = {b.id: b.name for b in session.scalars(select(BotRow))}
    rows = list(
        session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id.desc()).limit(RECENT))
    )
    rows.sort(key=lambda o: o.state != LiveState.WAITING_APPROVAL)  # 승인 기다림을 맨 앞에
    limits = LiveLimits()
    return LiveOverview(
        trader=row.trader if row else None,
        halted=bool(row and row.halted),
        auto_after=AUTO_AFTER,
        per_order=limits.per_order,
        per_month=limits.per_month,
        ratios=list(RATIOS),
        shortfall=list(row.shortfall or []) if row else [],
        checked_at=row.checked_at if row else None,
        orders=[
            LiveOrderInfo(
                o.id,
                o.bot_id,
                names.get(o.bot_id) if o.bot_id else None,
                o.symbol,
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
    """따라 사기 비율을 켜고(1/100·1/10) 끈다(None). 켜면 처음 몇 번은 다시 승인을 받는다."""
    bot = require_bot(session, bot_id, for_update=True)
    if ratio is not None and ratio not in RATIOS:
        raise Invalid(f"비율은 {', '.join(RATIOS)} 중에서 골라 주세요")
    if ratio is not None and deposit_plan(build_strategy(bot)) is None:
        raise Invalid("실제로 따라 사기는 매달 사 모으는 나 카피 봇만 할 수 있어요")
    value = RATIOS[ratio] if ratio else None
    if value == bot.live_ratio:
        return bot
    before = str(bot.live_ratio) if bot.live_ratio is not None else None
    if value is None:
        drop_unsent_live_orders(session, bot.id, now)
    else:
        bot.live_since, bot.live_streak = now, 0
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
    order = _order(session, order_id)
    if order.state != LiveState.WAITING_APPROVAL:
        raise Conflict("이미 처리된 주문이에요")
    if control(session, now).halted:
        raise Conflict("실제 주문을 멈춰 둔 동안에는 승인할 수 없어요")
    order.state, order.updated_at = LiveState.APPROVED, now
    live_event(session, now, order)
    session.commit()
    return order


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
