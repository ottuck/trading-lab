"""일봉 백테스트. 정기 DRY RUN과 같은 규칙을 쓴다 (project.md 7절).

판단·체결 규칙은 domain/trading.py를 그대로 쓴다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits, affordable_qty
from quant_lab.domain.strategy import Strategy
from quant_lab.domain.trading import Action, DecisionRecord, Fill, decide, execute


@dataclass(frozen=True, slots=True)
class EquityPoint:
    session_date: date
    equity: Decimal
    cash: Decimal
    qty: int
    close: Decimal
    benchmark: Decimal


@dataclass(frozen=True, slots=True)
class Metrics:
    start: date
    end: date
    initial_cash: Decimal
    final_equity: Decimal
    total_return: Decimal
    cagr: Decimal
    max_drawdown: Decimal
    exposure: Decimal
    round_trips: int
    win_rate: Decimal | None
    benchmark_final_equity: Decimal
    benchmark_total_return: Decimal
    benchmark_cagr: Decimal
    benchmark_max_drawdown: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    decisions: list[DecisionRecord]
    fills: list[Fill]
    equity: list[EquityPoint]
    metrics: Metrics
    pending: DecisionRecord | None


def run_backtest(
    bars: Sequence[DailyBar],
    strategy: Strategy,
    initial_cash: Decimal,
    costs: CostModel,
    limits: RiskLimits | None = None,
) -> BacktestResult:
    limits = limits or RiskLimits()
    start = strategy.warmup - 1  # 첫 판단이 가능한 봉
    if len(bars) <= start + 1:
        raise ValueError(f"봉이 부족합니다: {len(bars)}개 (필요 {start + 2}개 이상)")

    pf = Portfolio(cash=initial_cash)
    bench = Portfolio(cash=initial_cash)
    decisions: list[DecisionRecord] = []
    fills: list[Fill] = []
    equity: list[EquityPoint] = []
    pending: DecisionRecord | None = None

    for i, bar in enumerate(bars):
        # 1) 전날 판단을 오늘 시가로 체결한다.
        if pending is not None:
            fill = execute(pf, pending, bar, costs, limits)
            if fill is not None:
                fills.append(fill)
            pending = None
        if i == start + 1:
            # 비교 기준: 전략의 첫 체결 기회와 같은 날 시가에 전액 매수 후 보유
            price = costs.buy_price(bar.open)
            qty = affordable_qty(bench.cash, price, costs, RiskLimits(), Decimal(0))
            if qty > 0:
                bench.buy(qty, price, costs.commission(qty * price))

        # 2) 오늘 종가까지 보고 판단한다. bars[: i + 1] 밖의 데이터는 전략에 넘기지 않는다.
        if i >= start:
            record = decide(strategy, bars[: i + 1], pf, costs, limits)
            if record is not None:
                decisions.append(record)
                if record.action is not Action.HOLD:
                    pending = record
            equity.append(
                EquityPoint(
                    session_date=bar.session_date,
                    equity=pf.equity(bar.close),
                    cash=pf.cash,
                    qty=pf.qty,
                    close=bar.close,
                    benchmark=bench.equity(bar.close),
                )
            )

    return BacktestResult(
        decisions=decisions,
        fills=fills,
        equity=equity,
        metrics=_metrics(equity, fills, initial_cash),
        pending=pending,
    )


def _ratio(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def _max_drawdown(values: Sequence[Decimal]) -> Decimal:
    peak = values[0]
    worst = Decimal(0)
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return _ratio(float(worst))


def _cagr(initial: Decimal, final: Decimal, start: date, end: date) -> Decimal:
    years = (end - start).days / 365.25
    if years <= 0 or initial <= 0 or final <= 0:
        return Decimal(0)
    return _ratio(float(final / initial) ** (1 / years) - 1)


def _metrics(equity: list[EquityPoint], fills: list[Fill], initial_cash: Decimal) -> Metrics:
    first, last = equity[0], equity[-1]
    sells = [f for f in fills if f.realized_pnl is not None]
    wins = sum(1 for f in sells if f.realized_pnl is not None and f.realized_pnl > 0)
    return Metrics(
        start=first.session_date,
        end=last.session_date,
        initial_cash=initial_cash,
        final_equity=last.equity,
        total_return=_ratio(float(last.equity / initial_cash - 1)),
        cagr=_cagr(initial_cash, last.equity, first.session_date, last.session_date),
        max_drawdown=_max_drawdown([p.equity for p in equity]),
        exposure=_ratio(sum(1 for p in equity if p.qty > 0) / len(equity)),
        round_trips=len(sells),
        win_rate=_ratio(wins / len(sells)) if sells else None,
        benchmark_final_equity=last.benchmark,
        benchmark_total_return=_ratio(float(last.benchmark / initial_cash - 1)),
        benchmark_cagr=_cagr(initial_cash, last.benchmark, first.session_date, last.session_date),
        benchmark_max_drawdown=_max_drawdown([p.benchmark for p in equity]),
    )
