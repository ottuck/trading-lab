from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import ClassVar

import pytest

from quant_lab.domain.backtest import run_backtest
from quant_lab.domain.bars import DailyBar
from quant_lab.domain.portfolio import QTY_STEP, CostModel, RiskLimits
from quant_lab.domain.strategy import DipSaver, Signal, SmaCross
from quant_lab.domain.trading import Action
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
    assert buy.qty == (CASH / bars[2].open).quantize(QTY_STEP, rounding=ROUND_DOWN)  # 소수점 6자리
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


def test_risk_limit_caps_position() -> None:
    bars = make_bars("X", [100, 100, 100, 100])
    limits = RiskLimits(max_position_value=Decimal(1_000))
    result = run_backtest(bars, SpyStrategy(long_from=bars[0].session_date), CASH, NO_COST, limits)
    assert result.fills[0].qty == 10


def test_risk_metrics_and_annual_returns() -> None:
    bars = make_bars("X", [100 * (1.001**i) * (1 + 0.01 * (i % 3 - 1)) for i in range(400)])
    m = run_backtest(bars, SmaCross(fast=5, slow=20), CASH, NO_COST).metrics
    years = [y.year for y in m.annual_returns]
    assert years == sorted(set(years)) and len(years) >= 2
    assert m.benchmark_volatility > 0
    assert m.benchmark_sharpe is not None and m.benchmark_sharpe > 0


def test_dip_saver_deposits_monthly_buys_dips_and_never_sells() -> None:
    # 보합 → 빠르게 오름(고점, 쉼) → 30% 빠짐(하락장, 모은 돈 모두) → 보합
    closes = [100] * 30 + [100 + 3 * i for i in range(1, 16)]
    closes += [145 - 3 * i for i in range(1, 16)] + [100] * 40
    bars = make_bars("VOO", closes)
    s = DipSaver(deposit=500, day=1, dip=10, hot=10, high=20, sma=10)
    result = run_backtest(bars, s, Decimal(500), NO_COST)
    m = result.metrics

    # 시작 금액이 시작한 달의 입금이라 그달에는 또 넣지 않는다 (한 달에 한 번)
    months = {(b.session_date.year, b.session_date.month) for b in bars[s.warmup - 1 :]}
    assert m.deposits == len(months) - 1
    assert m.contributed == Decimal(500) * len(months)
    assert all(f.side is Action.BUY for f in result.fills)
    by_date = {d.session_date: d for d in result.decisions}
    # 고점에서는 입금일이어도 사지 않고, 하락장에서는 모아 둔 현금까지 쓴다
    hot = [d for d in result.decisions if d.indicators["premium"] >= Decimal("0.1")]
    assert hot and all(d.action is Action.HOLD for d in hot)
    dip_buys = [
        f for f in result.fills if by_date[f.signal_date].indicators["drawdown"] <= Decimal("-0.1")
    ]
    cash_after = {p.session_date: p.cash for p in result.equity}
    assert dip_buys and cash_after[dip_buys[0].fill_date] < dip_buys[0].price  # 남김없이 샀다
    assert (
        result.fills[0].signal_date == by_date[min(by_date)].session_date
    )  # 시작 금액은 첫날 바로
    # 비교 기준(매달 그냥 사기)도 같은 돈을 넣는다
    assert result.equity[-1].contributed == m.contributed

    # 고점에 쉬지 않기(hot=0): 고점이어도 입금일에 산다
    eager = run_backtest(bars, replace(s, hot=0), Decimal(500), NO_COST)
    assert {d.session_date for d in hot} & {f.signal_date for f in eager.fills}

    # 떨어졌을 때만 사기(regular=0): 평소엔 모아 두고 하락장에만 산다
    saver = run_backtest(bars, replace(s, regular=0), Decimal(500), NO_COST)
    days = {d.session_date: d for d in saver.decisions}
    assert saver.fills
    assert all(days[f.signal_date].indicators["drawdown"] <= Decimal("-0.1") for f in saver.fills)


def test_dip_saver_young_listing_uses_available_history() -> None:
    # 상장 석 달(63일) 종목: 1년이 안 돼도 한 달 이력부터 있는 만큼으로 판단한다
    bars = make_bars("NEW", [100 + i % 5 for i in range(63)])
    s = DipSaver(deposit=500, day=1)
    result = run_backtest(bars, s, Decimal(500), NO_COST)
    first = result.decisions[0]
    assert first.session_date == bars[s.min_bars - 1].session_date
    assert first.indicators["bars"] == s.min_bars and result.fills

    # 이력이 warmup과 꼭 같으면 짧은 종목이 아니다: 체결할 날이 없어 아직 계산하지 않는다
    # (봇을 만든 첫날의 평행세계가 1년 전부터 시작하던 것. 화면은 "아직 비교할 날이 없어요")
    full = make_bars("OLD", [100 + i % 5 for i in range(s.warmup)])
    with pytest.raises(ValueError, match="봉이 부족"):
        run_backtest(full, s, Decimal(500), NO_COST)
