"""봇·명령·이벤트 저장소."""

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from quant_lab.domain.bot import BotState, CommandKind
from quant_lab.domain.events import EventKind
from quant_lab.domain.live import LiveState, SkipReason
from quant_lab.domain.portfolio import CostModel, Portfolio, Position, RiskLimits
from quant_lab.domain.strategy import month_key
from quant_lab.persistence.backtests import to_jsonable
from quant_lab.persistence.models import (
    BotAccountRow,
    BotDepositRow,
    BotPositionRow,
    BotRow,
    CommandRow,
    DecisionRow,
    EventRow,
    LiveOrderRow,
    RunRow,
    SimOrderRow,
)


def create_bot(
    session: Session,
    *,
    name: str,
    symbol: str,
    strategy: str,
    params: dict[str, int],
    initial_cash: Decimal,
    costs: CostModel,
    limits: RiskLimits,
    now: datetime,
    weights: dict[str, int] | None = None,
) -> BotRow:
    """weights는 종목별 비율(합 100). 없으면 symbol 하나에 100. 첫 종목이 symbol이 된다."""
    weights = weights or {symbol: 100}
    bot = BotRow(
        name=name,
        symbol=next(iter(weights)),
        symbols=[{"symbol": s, "weight": w} for s, w in weights.items()],
        strategy=strategy,
        params=params,
        state=BotState.STOPPED,
        initial_cash=initial_cash,
        commission_rate=costs.commission_rate,
        slippage_bps=costs.slippage_bps,
        risk=to_jsonable(limits),
        created_at=now,
        updated_at=now,
    )
    session.add(bot)
    session.flush()
    session.add(
        BotAccountRow(
            bot_id=bot.id,
            cash=initial_cash,
            realized_pnl=Decimal(0),
            contributed=initial_cash,
            reserve=Decimal(0),
            updated_at=now,
        )
    )
    return bot


def bot_weights(bot: BotRow) -> dict[str, int]:
    """종목별 비율 (합 100). 첫 종목이 목록·알림에 보이는 대표 종목이다.

    비율 0은 종목을 바꾸며 뺐지만 들고 있는 종목이다: 시세·평가에는 쓰고 더 사지 않는다.
    """
    return {str(item["symbol"]): int(item["weight"]) for item in bot.symbols}


def active_weights(bot: BotRow) -> dict[str, int]:
    """판단(사기)에 쓰는 종목만 (비율 0 제외)."""
    return {s: w for s, w in bot_weights(bot).items() if w > 0}


def bot_costs(bot: BotRow) -> CostModel:
    return CostModel(commission_rate=bot.commission_rate, slippage_bps=bot.slippage_bps)


def bot_limits(bot: BotRow) -> RiskLimits:
    def dec(key: str) -> Decimal | None:
        value = bot.risk.get(key)
        return None if value is None else Decimal(value)

    return RiskLimits(
        max_position_value=dec("max_position_value"), max_order_value=dec("max_order_value")
    )


def get_bot(session: Session, bot_id: int, *, for_update: bool = False) -> BotRow | None:
    stmt = select(BotRow).where(BotRow.id == bot_id)
    if for_update:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def list_bots(session: Session) -> list[BotRow]:
    return list(session.scalars(select(BotRow).order_by(BotRow.id)))


def set_bot_state(
    session: Session, bot: BotRow, state: BotState, reason: str | None, now: datetime
) -> None:
    bot.state = state
    bot.state_reason = reason
    bot.updated_at = now


def deposited_month(session: Session, bot_id: int, today: date) -> str:
    """정기 입금을 마지막으로 넣은 달 (YYYY-MM).

    시작 금액이 시작한 달의 입금이라 입금 기록이 없으면 시작한 달(첫 판단일의 달, 첫 판단 전이면
    오늘의 달)을 넣은 달로 본다. 그달 입금일에 또 넣지 않는다 (백테스트와 같음).
    """
    last = session.scalar(
        select(func.max(BotDepositRow.month)).where(BotDepositRow.bot_id == bot_id)
    )
    if last is not None:
        return last
    first = session.scalar(
        select(func.min(DecisionRow.session_date)).where(DecisionRow.bot_id == bot_id)
    )
    return month_key(first or today)


def load_account(session: Session, bot_id: int) -> Portfolio:
    row = session.get_one(BotAccountRow, bot_id)
    positions = session.scalars(select(BotPositionRow).where(BotPositionRow.bot_id == bot_id))
    return Portfolio(
        cash=row.cash,
        positions={p.symbol: Position(p.qty, p.avg_cost) for p in positions},
        realized_pnl=row.realized_pnl,
        contributed=row.contributed,
        reserve=row.reserve,
    )


def save_account(session: Session, bot_id: int, pf: Portfolio, now: datetime) -> None:
    session.execute(
        update(BotAccountRow)
        .where(BotAccountRow.bot_id == bot_id)
        .values(
            cash=pf.cash,
            realized_pnl=pf.realized_pnl,
            contributed=pf.contributed,
            reserve=pf.reserve,
            updated_at=now,
        )
    )
    session.execute(delete(BotPositionRow).where(BotPositionRow.bot_id == bot_id))
    session.add_all(
        BotPositionRow(bot_id=bot_id, symbol=s, qty=p.qty, avg_cost=p.avg_cost)
        for s, p in pf.positions.items()
        if p.qty > 0
    )


def pending_orders(session: Session, bot_id: int) -> list[SimOrderRow]:
    """체결을 기다리는 모의 주문 (봇·종목당 최대 1개)."""
    stmt = (
        select(SimOrderRow)
        .where(SimOrderRow.bot_id == bot_id, SimOrderRow.status == "PENDING")
        .order_by(SimOrderRow.id)
    )
    return list(session.scalars(stmt))


def add_event(
    session: Session,
    at: datetime,
    level: str,
    kind: EventKind,
    message: str,
    *,
    bot_id: int | None = None,
    run_id: uuid.UUID | None = None,
    data: Mapping[str, Any] | None = None,
) -> None:
    """data 형식은 domain/events.py가 정한다. message는 로그용 원문이라 아무도 해석하지 않는다."""
    session.add(
        EventRow(
            at=at,
            level=level,
            kind=kind,
            message=message,
            bot_id=bot_id,
            run_id=run_id,
            data=to_jsonable(dict(data)) if data is not None else None,
        )
    )


def enqueue_command(session: Session, bot_id: int, kind: CommandKind, now: datetime) -> CommandRow:
    cmd = CommandRow(bot_id=bot_id, kind=kind, created_at=now)
    session.add(cmd)
    session.flush()
    return cmd


def unprocessed_commands(session: Session) -> list[CommandRow]:
    stmt = (
        select(CommandRow)
        .where(CommandRow.processed_at.is_(None))
        .order_by(CommandRow.created_at, CommandRow.id)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(stmt))


def drop_unsent_live_orders(session: Session, bot_id: int, now: datetime) -> None:
    """아직 보내지 않은 실제 주문을 "안 사기"로 닫는다 (따라 사기 끄기·봇 삭제·다시 시작).

    이미 보낸 주문은 증권사에 있으므로 그대로 두고 체결을 계속 확인한다.
    """
    session.execute(
        update(LiveOrderRow)
        .where(
            LiveOrderRow.bot_id == bot_id,
            LiveOrderRow.state.in_([LiveState.WAITING_APPROVAL, LiveState.APPROVED]),
        )
        .values(state=LiveState.SKIPPED, reason=SkipReason.DECLINED, updated_at=now)
    )


def delete_bot(session: Session, bot_id: int) -> None:
    """봇과 그 기록을 모두 지운다 (화면의 봇 삭제, replay 임시 봇 정리).

    실제 주문 기록은 남는다 (DB가 봇 연결만 비움). 아직 보내지 않은 실제 주문은 먼저 닫는다.
    """
    drop_unsent_live_orders(session, bot_id, datetime.now(UTC))
    for model in (
        EventRow,
        SimOrderRow,
        DecisionRow,
        RunRow,
        CommandRow,
        BotDepositRow,
        BotPositionRow,
        BotAccountRow,
    ):
        session.execute(delete(model).where(model.bot_id == bot_id))
    session.execute(delete(BotRow).where(BotRow.id == bot_id))


def reset_bot_history(session: Session, bot: BotRow, now: datetime) -> None:
    """판단·주문·실행·명령·기록을 지우고 잔고를 시작 금액으로. 다음 tick에 바로 다시 판단한다.

    설정을 바꾼 기록(설정 화면의 "바꾼 기록")은 판단·거래 기록이 아니므로 남긴다.
    """
    session.execute(
        delete(EventRow).where(EventRow.bot_id == bot.id, EventRow.kind != EventKind.CONFIG_CHANGE)
    )
    for model in (
        SimOrderRow,
        DecisionRow,
        RunRow,
        CommandRow,
        BotDepositRow,
        BotPositionRow,
    ):
        session.execute(delete(model).where(model.bot_id == bot.id))
    save_account(session, bot.id, Portfolio(cash=bot.initial_cash), now)
    drop_unsent_live_orders(session, bot.id, now)
    if bot.live_ratio is not None:  # 따라 사기는 새 기록부터
        bot.live_since = now
    bot.next_evaluation_at = None
    bot.updated_at = now
