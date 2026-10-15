"""DB의 일봉으로 백테스트를 실행하고 저장한다."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from trading_lab.domain.backtest import BacktestResult, run_backtest
from trading_lab.domain.bars import DailyBar
from trading_lab.domain.portfolio import CostModel, RiskLimits
from trading_lab.domain.strategy import Strategy
from trading_lab.persistence.backtests import save_backtest
from trading_lab.persistence.bars import load_daily_bars


def load_series(
    session: Session, weights: dict[str, int], warmup: int, start: date | None, end: date | None
) -> dict[str, list[DailyBar]]:
    """종목별 일봉. start일에 첫 판단을 할 수 있도록 그 앞의 warmup 구간을 함께 넘긴다."""
    series = {}
    for s in weights:
        bars = load_daily_bars(session, s, end=end)
        if start is not None:
            first = next((i for i, b in enumerate(bars) if b.session_date >= start), len(bars))
            bars = bars[max(0, first - warmup + 1) :]
        if not bars:
            raise ValueError(f"{s} 일봉이 없습니다. 먼저 sync-bars를 실행하세요.")
        series[s] = bars
    return series


@dataclass(frozen=True)
class BacktestRun:
    result: BacktestResult
    saved_id: uuid.UUID | None


def backtest_symbol(
    session: Session,
    symbol: str,
    strategy: Strategy,
    *,
    initial_cash: Decimal,
    costs: CostModel,
    limits: RiskLimits,
    start: date | None,
    end: date | None,
    now: datetime,
    save: bool,
    weights: dict[str, int] | None = None,
) -> BacktestRun:
    """symbol 하나, 또는 weights(종목별 비율, 합 100)로 여러 종목을 한 계좌로 시험한다."""
    weights = weights or {symbol: 100}
    series = load_series(session, weights, strategy.warmup, start, end)
    symbol = next(iter(weights))

    result = run_backtest(series, strategy, initial_cash, costs, limits, weights=weights)
    saved_id = None
    if save:
        saved_id = save_backtest(
            session,
            symbol=symbol,
            strategy=strategy.name,
            params=strategy.params,
            costs=costs,
            limits=limits,
            result=result,
            data_start=min(b[0].session_date for b in series.values()),
            created_at=now,
            weights=weights,
        )
    return BacktestRun(result=result, saved_id=saved_id)
