"""DB의 일봉으로 백테스트를 실행하고 저장한다."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from quant_lab.domain.backtest import BacktestResult, run_backtest
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import Strategy
from quant_lab.persistence.backtests import save_backtest
from quant_lab.persistence.bars import load_daily_bars


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
) -> BacktestRun:
    bars = load_daily_bars(session, symbol, end=end)
    if start is not None:
        # start일에 첫 판단을 할 수 있도록 그 앞의 warmup 구간을 함께 넘긴다.
        first = next((i for i, b in enumerate(bars) if b.session_date >= start), len(bars))
        bars = bars[max(0, first - strategy.warmup + 1) :]
    if not bars:
        raise ValueError(f"{symbol} 일봉이 없습니다. 먼저 sync-bars를 실행하세요.")

    result = run_backtest(bars, strategy, initial_cash, costs, limits)
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
            data_start=bars[0].session_date,
            created_at=now,
        )
    return BacktestRun(result=result, saved_id=saved_id)
