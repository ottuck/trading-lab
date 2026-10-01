from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import ClassVar

import pytest

from quant_lab.domain.backtest import Action, run_backtest
from quant_lab.domain.bars import DailyBar
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import Signal, SmaCross
from tests.fakes import make_bars

NO_COST = CostModel(commission_rate=Decimal(0), slippage_bps=Decimal(0))
CASH = Decimal(10_000)


@dataclass
class SpyStrategy:
    """미리 정한 날짜에 long/flat을 바꾸고, 받은 이력을 기록한다."""

    long_from: date
    flat_from: date | None = None
    name: ClassVar[str] = "spy"
    seen: list[tuple[date, int]] = field(default_factory=list)

    @property
    def params(self) -> dict[str, int]:
        return {}

    @property
    def warmup(self) -> int:
        return 1

    def signal(self, history: Sequence[DailyBar], holding: bool) -> Signal:
        today = history[-1].session_date
        self.seen.append((today, len(history)))
        long = today >= self.long_from and (self.flat_from is None or today < self.flat_from)
        return Signal(long, "spy")


def test_decision_at_close_fills_next_open() -> None:
    bars = make_bars("X", [100, 101, 102, 103, 104, 105])
    strategy = SpyStrategy(long_from=bars[1].session_date, flat_from=bars[3].session_date)
    result = run_backtest(bars, strategy, CASH, NO_COST)

    buy, sell = result.fills
    assert (buy.side, buy.signal_date, buy.fill_date) == (
        Action.BUY,
        bars[1].session_date,
        bars[2].session_date,
    )
    assert buy.price == bars[2].open
    assert buy.qty == int(CASH / bars[2].open)
    assert (sell.side, sell.signal_date, sell.fill_date) == (
        Action.SELL,
        bars[3].session_date,
        bars[4].session_date,
    )
    assert sell.price == bars[4].open


def test_strategy_never_sees_future_bars() -> None:
    bars = make_bars("X", [100 + i for i in range(30)])
    strategy = SpyStrategy(long_from=bars[5].session_date)
    run_backtest(bars, strategy, CASH, NO_COST)
    for i, (today, length) in enumerate(strategy.seen):
        assert today == bars[i].session_date
        assert length == i + 1


def test_truncated_data_gives_same_decisions_as_full_data() -> None:
    closes = [100 + (i % 17) * 3 - (i % 5) * 4 for i in range(300)]
    bars = make_bars("X", closes)
    s = SmaCross(fast=5, slow=20)
    full = run_backtest(bars, s, CASH, CostModel())
    cut = run_backtest(bars[:200], s, CASH, CostModel())

    cutoff = bars[199].session_date
    assert [d for d in full.decisions if d.session_date <= cutoff] == cut.decisions
    assert [f for f in full.fills if f.fill_date <= cutoff] == cut.fills


def test_rerun_is_deterministic() -> None:
    bars = make_bars("X", [100 + (i % 13) * 2 for i in range(120)])
    s = SmaCross(fast=3, slow=10)
    assert run_backtest(bars, s, CASH, CostModel()) == run_backtest(bars, s, CASH, CostModel())


def test_benchmark_and_metrics_on_rising_market() -> None:
    bars = make_bars("X", [100 + i for i in range(50)])
    result = run_backtest(bars, SmaCross(fast=2, slow=5), CASH, NO_COST)
    m = result.metrics
    assert m.max_drawdown == 0
    assert m.benchmark_max_drawdown == 0
    assert m.total_return > 0
    assert m.benchmark_total_return > 0
    # 첫 판단일 자산은 초기 현금
    assert result.equity[0].equity == CASH
    assert result.equity[0].session_date == bars[4].session_date


def test_last_day_signal_is_left_pending() -> None:
    bars = make_bars("X", [100, 101, 102])
    result = run_backtest(bars, SpyStrategy(long_from=bars[2].session_date), CASH, NO_COST)
    assert result.fills == []
    assert result.pending is not None and result.pending.action is Action.BUY


def test_risk_limit_caps_position() -> None:
    bars = make_bars("X", [100, 100, 100, 100])
    limits = RiskLimits(max_position_value=Decimal(1_000))
    result = run_backtest(bars, SpyStrategy(long_from=bars[0].session_date), CASH, NO_COST, limits)
    assert result.fills[0].qty == 10


def test_needs_enough_bars() -> None:
    with pytest.raises(ValueError):
        run_backtest(make_bars("X", [1, 2]), SmaCross(fast=2, slow=5), CASH, NO_COST)
