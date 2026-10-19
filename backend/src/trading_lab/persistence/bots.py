"""봇·명령·이벤트 저장소."""

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from trading_lab.domain.bot import BotState, CommandKind
from trading_lab.domain.events import EventKind
from trading_lab.domain.live import LiveState, SkipReason
from trading_lab.domain.portfolio import CostModel, Portfolio, Position, RiskLimits
from trading_lab.domain.strategy import month_key
from trading_lab.persistence.backtests import to_jsonable
from trading_lab.persistence.models import (
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


def bot_directory(session: Session) -> list[tuple[int, str, str, Decimal | None]]:
    """(id, 이름, 종목, 따라 사기 비율) — 알림처럼 봇 전체가 아니라 이름만 필요한 곳."""
    rows = session.execute(select(BotRow.id, BotRow.name, BotRow.symbol, BotRow.live_ratio)).all()
    return [(r.id, r.name, r.symbol, r.live_ratio) for r in rows]


def name_taken(session: Session, name: str) -> bool:
    return session.scalar(select(BotRow.id).where(BotRow.name == name)) is not None


def strategy_taken(session: Session, strategy: str, *, except_bot_id: int | None = None) -> bool:
    """같은 전략의 다른 봇이 있는가."""
    return (
        session.scalar(
            select(BotRow.id)
            .where(BotRow.strategy == strategy, BotRow.id != (except_bot_id or 0))
            .limit(1)
        )
        is not None
    )


def first_decision_date(session: Session, bot_id: int) -> date | None:
    return session.scalar(
        select(func.min(DecisionRow.session_date)).where(DecisionRow.bot_id == bot_id)
    )


def last_decision_date(session: Session, bot_id: int, mode: str) -> date | None:
    return session.scalar(
        select(func.max(DecisionRow.session_date)).where(
            DecisionRow.bot_id == bot_id, DecisionRow.mode == mode
        )
    )


def find_decision(session: Session, bot_id: int, day: date, mode: str) -> DecisionRow | None:
    return session.scalars(
        select(DecisionRow).where(
            DecisionRow.bot_id == bot_id, DecisionRow.session_date == day, DecisionRow.mode == mode
        )
    ).first()


def decisions_of(session: Session, bot_id: int) -> list[DecisionRow]:
    """봇의 모든 판단, 오래된 것부터."""
    return list(
        session.scalars(
            select(DecisionRow)
            .where(DecisionRow.bot_id == bot_id)
            .order_by(DecisionRow.session_date)
        )
    )


def deposits_by_date(session: Session, bot_id: int) -> dict[date, BotDepositRow]:
    return {
        d.session_date: d
        for d in session.scalars(select(BotDepositRow).where(BotDepositRow.bot_id == bot_id))
    }


def positions_of(session: Session, bot_id: int) -> list[BotPositionRow]:
    return list(session.scalars(select(BotPositionRow).where(BotPositionRow.bot_id == bot_id)))


def pending_buy_orders(session: Session, bot_id: int) -> list[SimOrderRow]:
    """체결을 기다리는 모의 매수."""
    return [o for o in pending_orders(session, bot_id) if o.side == "BUY"]


def held_symbols(session: Session, bot_id: int) -> list[str]:
    return list(
        session.scalars(
            select(BotPositionRow.symbol).where(
                BotPositionRow.bot_id == bot_id, BotPositionRow.qty > 0
            )
        )
    )


def last_fill(session: Session, bot_id: int, symbol: str) -> SimOrderRow | None:
    """그 종목에서 가장 최근에 체결된 모의 주문 (가격이 있는 것)."""
    return session.scalars(
        select(SimOrderRow)
        .where(
            SimOrderRow.bot_id == bot_id,
            SimOrderRow.symbol == symbol,
            SimOrderRow.status == "FILLED",
            SimOrderRow.price.is_not(None),
            SimOrderRow.fill_date.is_not(None),
        )
        .order_by(SimOrderRow.fill_date.desc(), SimOrderRow.id.desc())
        .limit(1)
    ).first()


def filled_counts(session: Session, bot_id: int, start: date, end: date) -> dict[str, int]:
    """[start, end]에 체결된 모의 주문 수 (BUY/SELL별)."""
    rows = session.execute(
        select(SimOrderRow.side, func.count())
        .where(
            SimOrderRow.bot_id == bot_id,
            SimOrderRow.status == "FILLED",
            SimOrderRow.fill_date >= start,
            SimOrderRow.fill_date <= end,
        )
        .group_by(SimOrderRow.side)
    ).all()
    return {side: n for side, n in rows}


def previous_finished_run(session: Session, bot_id: int, except_run_id: uuid.UUID) -> RunRow | None:
    return session.scalars(
        select(RunRow)
        .where(RunRow.bot_id == bot_id, RunRow.id != except_run_id, RunRow.finished_at.is_not(None))
        .order_by(RunRow.started_at.desc())
        .limit(1)
    ).first()


def preferred_bot(session: Session, strategy: str) -> BotRow | None:
    """그 전략의 봇 하나 (실행 중인 것부터, 여럿이면 먼저 만든 것)."""
    return session.scalars(
        select(BotRow)
        .where(BotRow.strategy == strategy)
        .order_by((BotRow.state != "RUNNING"), BotRow.id)
        .limit(1)
    ).first()


def other_strategy_bots(session: Session, bot_id: int, strategy: str) -> list[BotRow]:
    """다른 봇 중 전략이 다른 것, 먼저 만든 순서."""
    return list(
        session.scalars(
            select(BotRow)
            .where(BotRow.id != bot_id, BotRow.strategy != strategy)
            .order_by(BotRow.id)
        )
    )


def bot_names(session: Session) -> dict[int, str]:
    return {b.id: b.name for b in session.scalars(select(BotRow))}


def last_decision(session: Session, bot_id: int) -> DecisionRow | None:
    return session.scalars(
        select(DecisionRow)
        .where(DecisionRow.bot_id == bot_id)
        .order_by(DecisionRow.session_date.desc())
        .limit(1)
    ).first()


def decisions_on(session: Session, bot_id: int, day: date) -> list[DecisionRow]:
    return list(
        session.scalars(
            select(DecisionRow).where(DecisionRow.bot_id == bot_id, DecisionRow.session_date == day)
        )
    )


def last_run(session: Session, bot_id: int) -> RunRow | None:
    return session.scalars(
        select(RunRow).where(RunRow.bot_id == bot_id).order_by(RunRow.started_at.desc()).limit(1)
    ).first()


def pending_command_kind(session: Session, bot_id: int) -> str | None:
    """아직 Worker가 처리하지 않은 가장 최근 명령."""
    return session.scalars(
        select(CommandRow.kind)
        .where(CommandRow.bot_id == bot_id, CommandRow.processed_at.is_(None))
        .order_by(CommandRow.created_at.desc())
        .limit(1)
    ).first()


def real_fill_count(session: Session, bot_id: int) -> int:
    """이 봇이 실제로 체결(일부 포함)한 주문 수."""
    return (
        session.scalar(
            select(func.count())
            .select_from(LiveOrderRow)
            .where(LiveOrderRow.bot_id == bot_id, LiveOrderRow.filled_qty > 0)
        )
        or 0
    )


def filled_sim_orders(session: Session, bot_id: int) -> list[SimOrderRow]:
    """체결된 모의 주문, 체결일 순서."""
    return list(
        session.scalars(
            select(SimOrderRow)
            .where(SimOrderRow.bot_id == bot_id, SimOrderRow.status == "FILLED")
            .order_by(SimOrderRow.fill_date, SimOrderRow.id)
        )
    )


def latest_decisions(session: Session, bot_id: int, limit: int) -> list[DecisionRow]:
    return list(
        session.scalars(
            select(DecisionRow)
            .where(DecisionRow.bot_id == bot_id)
            .order_by(DecisionRow.session_date.desc())
            .limit(limit)
        )
    )


def latest_sim_orders(session: Session, bot_id: int, limit: int) -> list[SimOrderRow]:
    return list(
        session.scalars(
            select(SimOrderRow)
            .where(SimOrderRow.bot_id == bot_id)
            .order_by(SimOrderRow.id.desc())
            .limit(limit)
        )
    )


def running_bots(session: Session) -> list[BotRow]:
    return list(session.scalars(select(BotRow).where(BotRow.state == BotState.RUNNING)))


def due_bot_ids(session: Session, now: datetime) -> list[int]:
    """평가할 때가 된 실행 중인 봇 (다음 평가 시각이 없거나 지났다)."""
    return list(
        session.scalars(
            select(BotRow.id).where(
                BotRow.state == BotState.RUNNING,
                (BotRow.next_evaluation_at.is_(None)) | (BotRow.next_evaluation_at <= now),
            )
        )
    )


def pending_command_ids(session: Session) -> list[int]:
    """아직 처리하지 않은 명령, 만든 순서."""
    return list(
        session.scalars(
            select(CommandRow.id)
            .where(CommandRow.processed_at.is_(None))
            .order_by(CommandRow.created_at, CommandRow.id)
        )
    )
