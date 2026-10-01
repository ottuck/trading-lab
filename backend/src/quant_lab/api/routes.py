"""조회와 명령 API. 토스를 호출하지 않고 DB만 읽는다 (project.md 3절 원칙 6)."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.api.schemas import (
    AccountView,
    BacktestDetail,
    BacktestRequest,
    BacktestSummary,
    BarView,
    BotView,
    CommandAccepted,
    CommandRequest,
    DecisionView,
    EventView,
    OrderView,
    RunView,
    StrategyInfo,
)
from quant_lab.application.backtesting import backtest_symbol
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import STRATEGIES
from quant_lab.persistence.bots import enqueue_command, get_bot, list_bots
from quant_lab.persistence.db import get_session
from quant_lab.persistence.models import (
    BacktestRow,
    BotAccountRow,
    BotRow,
    DailyBarRow,
    DecisionRow,
    EventRow,
    RunRow,
    SimOrderRow,
)

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


def _account(session: Session, bot: BotRow) -> AccountView:
    acc = session.get_one(BotAccountRow, bot.id)
    last = session.scalars(
        select(DailyBarRow)
        .where(DailyBarRow.symbol == bot.symbol)
        .order_by(DailyBarRow.session_date.desc())
        .limit(1)
    ).first()
    if last is None:
        return AccountView(
            initial_cash=bot.initial_cash,
            cash=acc.cash,
            qty=acc.qty,
            avg_cost=acc.avg_cost,
            realized_pnl=acc.realized_pnl,
            last_close=None,
            last_close_date=None,
            market_value=None,
            unrealized_pnl=None,
            equity=None,
            total_return=None,
        )
    market_value = acc.qty * last.close
    equity = acc.cash + market_value
    return AccountView(
        initial_cash=bot.initial_cash,
        cash=acc.cash,
        qty=acc.qty,
        avg_cost=acc.avg_cost,
        realized_pnl=acc.realized_pnl,
        last_close=last.close,
        last_close_date=last.session_date,
        market_value=market_value,
        unrealized_pnl=market_value - acc.qty * acc.avg_cost,
        equity=equity,
        total_return=(equity / bot.initial_cash - 1) if bot.initial_cash else None,
    )


def _decision(row: DecisionRow) -> DecisionView:
    return DecisionView.model_validate(row, from_attributes=True)


def _order(row: SimOrderRow) -> OrderView:
    return OrderView.model_validate(row, from_attributes=True)


def _bot_view(session: Session, bot: BotRow) -> BotView:
    last_decision = session.scalars(
        select(DecisionRow)
        .where(DecisionRow.bot_id == bot.id)
        .order_by(DecisionRow.session_date.desc())
        .limit(1)
    ).first()
    pending = session.scalars(
        select(SimOrderRow).where(SimOrderRow.bot_id == bot.id, SimOrderRow.status == "PENDING")
    ).first()
    last_run = session.scalars(
        select(RunRow).where(RunRow.bot_id == bot.id).order_by(RunRow.started_at.desc()).limit(1)
    ).first()
    data_latest, data_fetched = session.execute(
        select(func.max(DailyBarRow.session_date), func.max(DailyBarRow.fetched_at)).where(
            DailyBarRow.symbol == bot.symbol
        )
    ).one()
    return BotView(
        id=bot.id,
        name=bot.name,
        symbol=bot.symbol,
        strategy=bot.strategy,
        params=bot.params,
        state=bot.state,
        state_reason=bot.state_reason,
        commission_rate=bot.commission_rate,
        slippage_bps=bot.slippage_bps,
        risk=bot.risk,
        next_evaluation_at=bot.next_evaluation_at,
        account=_account(session, bot),
        last_decision=_decision(last_decision) if last_decision else None,
        pending_order=_order(pending) if pending else None,
        last_run=RunView.model_validate(last_run, from_attributes=True) if last_run else None,
        data_latest_date=data_latest,
        data_fetched_at=data_fetched,
    )


def _require_bot(session: Session, bot_id: int) -> BotRow:
    bot = get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"봇 {bot_id}가 없습니다")
    return bot


@router.get("/bots")
def bots(session: SessionDep) -> list[BotView]:
    return [_bot_view(session, b) for b in list_bots(session) if not b.name.startswith("replay-")]


@router.get("/bots/{bot_id}")
def bot(session: SessionDep, bot_id: int) -> BotView:
    return _bot_view(session, _require_bot(session, bot_id))


@router.post("/bots/{bot_id}/commands", status_code=status.HTTP_202_ACCEPTED)
def command(session: SessionDep, bot_id: int, body: CommandRequest) -> CommandAccepted:
    """명령은 DB에 기록만 한다. Worker가 다음 주기(15초 이내)에 처리한다."""
    _require_bot(session, bot_id)
    cmd = enqueue_command(session, bot_id, body.kind, datetime.now(UTC))
    session.commit()
    return CommandAccepted(id=cmd.id, bot_id=bot_id, kind=body.kind, created_at=cmd.created_at)


@router.get("/bots/{bot_id}/decisions")
def decisions(
    session: SessionDep, bot_id: int, limit: Annotated[int, Query(le=500)] = 50
) -> list[DecisionView]:
    rows = session.scalars(
        select(DecisionRow)
        .where(DecisionRow.bot_id == bot_id)
        .order_by(DecisionRow.session_date.desc())
        .limit(limit)
    )
    return [_decision(r) for r in rows]


@router.get("/bots/{bot_id}/orders")
def orders(
    session: SessionDep, bot_id: int, limit: Annotated[int, Query(le=500)] = 50
) -> list[OrderView]:
    rows = session.scalars(
        select(SimOrderRow)
        .where(SimOrderRow.bot_id == bot_id)
        .order_by(SimOrderRow.id.desc())
        .limit(limit)
    )
    return [_order(r) for r in rows]


@router.get("/events")
def events(
    session: SessionDep,
    bot_id: int | None = None,
    level: str | None = None,
    limit: Annotated[int, Query(le=500)] = 100,
) -> list[EventView]:
    stmt = select(EventRow).order_by(EventRow.at.desc(), EventRow.id.desc()).limit(limit)
    if bot_id is not None:
        stmt = stmt.where(EventRow.bot_id == bot_id)
    if level:
        stmt = stmt.where(EventRow.level == level.upper())
    return [EventView.model_validate(r, from_attributes=True) for r in session.scalars(stmt)]


@router.get("/bars/{symbol}")
def bars(
    session: SessionDep,
    symbol: str,
    start: date | None = None,
    limit: Annotated[int, Query(le=10_000)] = 600,
) -> list[BarView]:
    stmt = select(DailyBarRow).where(DailyBarRow.symbol == symbol.upper())
    if start:
        stmt = stmt.where(DailyBarRow.session_date >= start)
    rows = list(session.scalars(stmt.order_by(DailyBarRow.session_date.desc()).limit(limit)))
    return [
        BarView(
            date=r.session_date, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume
        )
        for r in reversed(rows)
    ]


@router.get("/strategies")
def strategies() -> list[StrategyInfo]:
    return [StrategyInfo(name=n, default_params=f().params) for n, f in STRATEGIES.items()]


@router.post("/backtests", status_code=status.HTTP_201_CREATED)
def run_backtest(session: SessionDep, body: BacktestRequest) -> BacktestDetail:
    """일봉 1종목 백테스트는 수 초면 끝나서 요청 안에서 실행한다 (스레드풀, 토스 호출 없음)."""
    factory = STRATEGIES.get(body.strategy)
    if factory is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"알 수 없는 전략: {body.strategy}")
    try:
        strategy = factory(**body.params)
        run = backtest_symbol(
            session,
            body.symbol.upper(),
            strategy,
            initial_cash=body.initial_cash,
            costs=CostModel(commission_rate=body.commission_rate, slippage_bps=body.slippage_bps),
            limits=RiskLimits(),
            start=body.start,
            end=body.end,
            now=datetime.now(UTC),
            save=True,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    assert run.saved_id is not None
    return backtest(session, run.saved_id)


@router.get("/backtests")
def backtests(
    session: SessionDep, symbol: str | None = None, limit: Annotated[int, Query(le=100)] = 20
) -> list[BacktestSummary]:
    stmt = select(BacktestRow).order_by(BacktestRow.created_at.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(BacktestRow.symbol == symbol.upper())
    return [BacktestSummary.model_validate(r, from_attributes=True) for r in session.scalars(stmt)]


@router.get("/backtests/{backtest_id}")
def backtest(session: SessionDep, backtest_id: uuid.UUID) -> BacktestDetail:
    row = session.get(BacktestRow, backtest_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "백테스트가 없습니다")
    return BacktestDetail.model_validate(row, from_attributes=True)
