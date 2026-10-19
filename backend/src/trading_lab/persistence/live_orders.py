"""실제 주문(live_orders)과 실거래 제어 행 조회."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from trading_lab.domain.live import LiveState, SkipReason
from trading_lab.persistence.models import BotRow, LiveControlRow, LiveOrderRow, SimOrderRow

# 내기로 한 금액으로 월 한도에 예약하는 상태 (결과 불명 포함)
COMMITTED = (
    LiveState.APPROVED,
    LiveState.SENDING,
    LiveState.SENT,
    LiveState.FILLED,
    LiveState.UNKNOWN,
)
WAITING_TO_SEND = (LiveState.WAITING_APPROVAL, LiveState.APPROVED)
# 체결 수량: 사면 +, 팔면 - (봇이 실제 계좌에 남긴 수량 계산)
SIGNED_QTY = case(
    (LiveOrderRow.side == "SELL", -LiveOrderRow.filled_qty), else_=LiveOrderRow.filled_qty
)


def control(session: Session, now: datetime) -> LiveControlRow:
    """실거래 제어 행 (없으면 만든다). 행을 잠근다."""
    row = session.get(LiveControlRow, 1, with_for_update=True)
    if row is None:
        row = LiveControlRow(id=1, halted=False, trader=None, updated_at=now)
        session.add(row)
        session.flush()
    return row


def month_bought(
    session: Session,
    trade_date: date,
    bot_id: int | None = None,
    exclude_id: int | None = None,
) -> Decimal:
    """거래일이 속한 달에 내기로 한 사기 금액(결과 불명 포함). bot_id가 없으면 계좌 전체."""
    start = trade_date.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    reserved = case(
        (LiveOrderRow.state.in_(COMMITTED), LiveOrderRow.amount),
        (
            LiveOrderRow.filled_qty > 0,
            func.coalesce(LiveOrderRow.filled_amount, LiveOrderRow.amount),
        ),
        else_=func.coalesce(LiveOrderRow.filled_amount, 0),
    )
    query = select(func.coalesce(func.sum(reserved), 0)).where(
        LiveOrderRow.side == "BUY",
        LiveOrderRow.state.in_((*COMMITTED, LiveState.CANCELED, LiveState.REJECTED)),
        LiveOrderRow.trade_date >= start,
        LiveOrderRow.trade_date < end,
    )
    if bot_id is not None:
        query = query.where(LiveOrderRow.bot_id == bot_id)
    if exclude_id is not None:
        query = query.where(LiveOrderRow.id != exclude_id)  # 지금 따지는 주문 자신은 뺀다
    return Decimal(session.scalar(query) or 0)


def has_unknown(session: Session) -> bool:
    """달·봇과 무관하게, 삭제한 봇의 기록까지 확인한다."""
    return (
        session.scalar(
            select(LiveOrderRow.id).where(LiveOrderRow.state == LiveState.UNKNOWN).limit(1)
        )
        is not None
    )


def unplanned_sim_orders(session: Session) -> list[tuple[SimOrderRow, BotRow]]:
    """따라 사기를 켠 뒤 생겼지만 아직 실제 주문이 없는 모의 주문 (오래된 것부터)."""
    rows = session.execute(
        select(SimOrderRow, BotRow)
        .join(BotRow, BotRow.id == SimOrderRow.bot_id)
        .outerjoin(LiveOrderRow, LiveOrderRow.sim_order_id == SimOrderRow.id)
        .where(
            BotRow.live_ratio.is_not(None),
            SimOrderRow.created_at >= BotRow.live_since,
            LiveOrderRow.id.is_(None),
        )
        .order_by(SimOrderRow.id)
    ).all()
    return [(sim, bot) for sim, bot in rows]


def waiting_buy_total(session: Session, day: date) -> Decimal:
    """그날 보내려고 기다리는 사는 주문의 금액 합."""
    return Decimal(
        session.scalar(
            select(func.coalesce(func.sum(LiveOrderRow.amount), 0)).where(
                LiveOrderRow.trade_date == day,
                LiveOrderRow.side == "BUY",
                LiveOrderRow.state.in_(WAITING_TO_SEND),
            )
        )
        or 0
    )


def carried_orders(session: Session, bot_id: int, symbol: str) -> list[LiveOrderRow]:
    """아직 더하지 않은, 작아서 모아 둔 몫."""
    return list(
        session.scalars(
            select(LiveOrderRow).where(
                LiveOrderRow.bot_id == bot_id,
                LiveOrderRow.symbol == symbol,
                LiveOrderRow.reason == SkipReason.CARRIED,
                LiveOrderRow.carried_into.is_(None),
            )
        )
    )


def order_ids_in(session: Session, states: Sequence[str]) -> list[int]:
    return list(
        session.scalars(
            select(LiveOrderRow.id).where(LiveOrderRow.state.in_(states)).order_by(LiveOrderRow.id)
        )
    )


def linked_broker_ids(session: Session, order_id: int, source: str | None) -> set[str]:
    """같은 출처의 다른 기록에 이미 연결된 증권사 주문 번호."""
    return set(
        session.scalars(
            select(LiveOrderRow.broker_order_id).where(
                LiveOrderRow.id != order_id,
                LiveOrderRow.source == source,
                LiveOrderRow.broker_order_id.is_not(None),
            )
        )
    )


def broker_id_linked(
    session: Session, order_id: int, source: str | None, broker_order_id: str
) -> bool:
    return (
        session.scalar(
            select(LiveOrderRow.id)
            .where(
                LiveOrderRow.id != order_id,
                LiveOrderRow.source == source,
                LiveOrderRow.broker_order_id == broker_order_id,
            )
            .limit(1)
        )
        is not None
    )


def net_bought_by_symbol(session: Session, settled_before: datetime) -> dict[str, Decimal]:
    """종목별로 봇이 실제로 산 순수량 (체결 기준, settled_before 이전에 바뀐 주문만)."""
    rows = session.execute(
        select(LiveOrderRow.symbol, func.sum(SIGNED_QTY))
        .where(
            LiveOrderRow.filled_qty.is_not(None),
            LiveOrderRow.state.in_([LiveState.FILLED, LiveState.CANCELED]),
            LiveOrderRow.updated_at <= settled_before,
        )
        .group_by(LiveOrderRow.symbol)
    ).all()
    return {symbol: Decimal(qty) for symbol, qty in rows if qty}


def live_position(session: Session, bot_id: int, symbol: str) -> Decimal:
    """이 봇이 실제 계좌에서 사고판 결과 남은 수량 (체결 기준)."""
    total = session.scalar(
        select(func.coalesce(func.sum(SIGNED_QTY), 0)).where(
            LiveOrderRow.bot_id == bot_id,
            LiveOrderRow.symbol == symbol,
            LiveOrderRow.filled_qty.is_not(None),
        )
    )
    return max(Decimal(total or 0), Decimal(0))


def filled_orders(session: Session) -> list[LiveOrderRow]:
    """체결된 실제 주문(일부 체결 뒤 취소 포함)을 거래일·번호 순으로."""
    return list(
        session.scalars(
            select(LiveOrderRow)
            .where(
                LiveOrderRow.filled_qty > 0,
                LiveOrderRow.state.in_([LiveState.FILLED, LiveState.CANCELED]),
            )
            .order_by(LiveOrderRow.trade_date, LiveOrderRow.id)
        )
    )


def recent_orders(session: Session, n: int) -> list[LiveOrderRow]:
    return list(session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id.desc()).limit(n)))


def unknown_orders(session: Session) -> list[LiveOrderRow]:
    return list(
        session.scalars(
            select(LiveOrderRow)
            .where(LiveOrderRow.state == LiveState.UNKNOWN)
            .order_by(LiveOrderRow.id)
        )
    )
