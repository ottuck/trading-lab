"""계산해 보기 API: 시험해 보기(백테스트)와 평행세계. 계산은 application.research가 한다."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from quant_lab.api.deps import SessionDep
from quant_lab.api.schemas import (
    BacktestDetail,
    BacktestRequest,
    BacktestSummary,
    MonthBuy,
    ParallelRequest,
    ParallelView,
    WorldPoint,
    WorldView,
)
from quant_lab.application import research
from quant_lab.application.errors import NotFound
from quant_lab.application.parallel import World
from quant_lab.config import get_settings
from quant_lab.domain.portfolio import CostModel
from quant_lab.persistence.models import BacktestRow

router = APIRouter()
DEMO_BACKTESTS = 30  # 공개 데모에서 남기는 시험해 보기 결과 수


def parallel_view(worlds: list[World]) -> ParallelView:
    me = worlds[0].final_equity
    return ParallelView(
        start=worlds[0].start,
        end=worlds[0].end,
        worlds=[
            WorldView(
                key=w.key,
                title=w.title,
                params=w.params,
                final_equity=w.final_equity,
                contributed=w.contributed,
                cagr=w.cagr,
                same_as_me=w.key != "me" and w.final_equity == me,
                equity=[WorldPoint(date=d, equity=e) for d, e in w.equity],
                recent=[MonthBuy(month=k, bought=v) for k, v in w.recent],
            )
            for w in worlds
        ],
    )


@router.post("/backtests", status_code=status.HTTP_201_CREATED)
def run_backtest(session: SessionDep, body: BacktestRequest) -> BacktestDetail:
    """일봉 백테스트는 수 초면 끝나서 요청 안에서 실행한다 (스레드풀, 증권사 호출 없음)."""
    saved_id = research.run_backtest(
        session,
        symbol=body.symbol,
        symbols=[(s.symbol, s.weight) for s in body.symbols] if body.symbols else None,
        strategy=body.strategy,
        params=body.params,
        start=body.start,
        end=body.end,
        initial_cash=body.initial_cash,
        costs=CostModel(commission_rate=body.commission_rate, slippage_bps=body.slippage_bps),
        now=datetime.now(UTC),
        keep_latest=DEMO_BACKTESTS if get_settings().demo_mode else None,
    )
    return backtest(session, saved_id)


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
        raise NotFound("백테스트가 없습니다")
    return BacktestDetail.model_validate(row, from_attributes=True)


@router.post("/parallel")
def parallel(session: SessionDep, body: ParallelRequest) -> ParallelView:
    """평행세계의 나: 내 규칙을 하나씩 바꾼 나들을 같은 기간에 계산한다 (저장하지 않음)."""
    worlds = research.parallel_request(
        session,
        symbol=body.symbol,
        symbols=[(s.symbol, s.weight) for s in body.symbols] if body.symbols else None,
        params=body.params,
        start=body.start,
        end=body.end,
        initial_cash=body.initial_cash,
    )
    return parallel_view(worlds)
