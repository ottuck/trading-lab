"""일봉 백테스트. 정기 DRY RUN과 같은 규칙을 쓴다 (project.md 7절).

판단·체결 규칙은 domain/trading.py를 그대로 쓴다.
입금일마다 전략과 비교 기준 계좌에 같은 돈을 넣는다.
비교 기준은 넣은 돈을 다음 날 시가에 바로 사는 "매달 그냥 사기"다.
수익률 지표는 입금 효과를 뺀 시간가중 수익률로 계산한다.
"""

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits, affordable_qty
from quant_lab.domain.strategy import Strategy, is_ai, min_bars, month_key
from quant_lab.domain.trading import (
    Action,
    DecisionRecord,
    Fill,
    decide_basket,
    execute,
    rebalance,
)


@dataclass(frozen=True, slots=True)
class EquityPoint:
    session_date: date
    equity: Decimal
    cash: Decimal
    invested: Decimal  # 보유 주식 평가금액 (여러 종목 합계)
    benchmark: Decimal
    contributed: Decimal  # 이날까지 넣은 돈 (시작 금액 + 입금)
    deposit: Decimal = Decimal(0)  # 이날 들어온 입금액


@dataclass(frozen=True, slots=True)
class YearReturn:
    year: int
    strategy: Decimal
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
    benchmark_final_equity: Decimal
    benchmark_total_return: Decimal
    benchmark_cagr: Decimal
    benchmark_max_drawdown: Decimal
    volatility: Decimal
    sharpe: Decimal | None
    benchmark_volatility: Decimal
    benchmark_sharpe: Decimal | None
    annual_returns: list[YearReturn]
    contributed: Decimal  # 넣은 돈 합계. 입금이 없으면 initial_cash와 같다
    deposits: int  # 입금 횟수


@dataclass(frozen=True, slots=True)
class BacktestResult:
    decisions: list[DecisionRecord]
    fills: list[Fill]
    equity: list[EquityPoint]
    metrics: Metrics
    pending: list[DecisionRecord]  # 마지막 날 판단으로 다음 날 체결될 주문


def run_backtest(
    bars: Mapping[str, Sequence[DailyBar]],
    strategy: Strategy,
    initial_cash: Decimal,
    costs: CostModel,
    limits: RiskLimits | None = None,
    weights: Mapping[str, int] | None = None,
    judgments: Mapping[date, Mapping[str, int] | None] | None = None,
) -> BacktestResult:
    """bars는 종목별 일봉(weights 합 100, 없으면 한 종목 100).

    여러 종목은 모든 종목에 봉이 있는 거래일만 진행하고, 모든 종목이 warmup을 채운 날부터 판단한다.
    이력 전체가 warmup보다 짧은 종목(상장 1년 미만)은 전략의 min_bars를 채운 날부터 본다.
    AI 봇은 기록된 판단(judgments: 판단일 → 목표 비중, 없거나 None이면 그대로 둠)으로만 다시
    돌린다. 과거로 새 AI 판단을 만들지는 않는다 (project.md 14절).
    """
    if is_ai(strategy) and judgments is None:
        raise ValueError("AI 봇은 과거 백테스트를 하지 않아요 (기록된 판단으로만 다시 돌려요)")
    limits = limits or RiskLimits()
    series = dict(bars)
    symbols = list(series)
    weights = dict(weights) if weights else {s: 100 for s in symbols}
    if len(symbols) > 1 and sum(weights[s] for s in symbols) != 100:
        raise ValueError("종목 비율의 합은 100이어야 합니다")
    index = {s: {b.session_date: i for i, b in enumerate(v)} for s, v in series.items()}
    days = sorted(set.intersection(*(set(i) for i in index.values())))
    need = {
        s: strategy.warmup if len(series[s]) >= strategy.warmup else min_bars(strategy)
        for s in symbols
    }
    start = next(
        (k for k, d in enumerate(days) if all(index[s][d] + 1 >= need[s] for s in symbols)),
        len(days),
    )
    if start + 1 >= len(days):
        raise ValueError(
            f"봉이 부족합니다: 공통 거래일 {len(days)}일 ({max(need.values())}일 필요)"
        )

    plan = strategy.deposit_plan
    pf = Portfolio(cash=initial_cash)
    bench = Portfolio(cash=initial_cash)
    decisions: list[DecisionRecord] = []
    fills: list[Fill] = []
    equity: list[EquityPoint] = []
    pending: dict[str, DecisionRecord] = {}
    # 시작 금액이 시작한 달의 입금이다: 그달 입금일에는 또 넣지 않는다 (모의 운영과 같음)
    last_month: str | None = month_key(days[start]) if start < len(days) else None
    bench_buy = False

    for k, day in enumerate(days):
        today = {s: series[s][index[s][day]] for s in symbols}
        # 1) 전날 판단을 오늘 시가로 체결한다.
        for symbol, order in pending.items():
            fill = execute(pf, order, today[symbol], costs, limits)
            if fill is not None:
                fills.append(fill)
        pending = {}
        if k == start + 1 or bench_buy:
            # 비교 기준: 전략의 첫 체결 기회와 같은 날 시가에 비율대로 전액 매수 후 보유.
            # 입금이 있으면 다음 날 시가에 또 산다 ("매달 그냥 사기").
            cash = bench.cash
            for symbol in symbols:
                price = costs.buy_price(today[symbol].open)
                budget = min(bench.cash, cash * weights[symbol] / 100)
                qty = affordable_qty(budget, price, costs, RiskLimits(), Decimal(0))
                if qty > 0:
                    bench.buy(symbol, qty, price, costs.commission(qty * price))
            bench_buy = False

        # 2) 오늘 종가까지 보고 판단한다. 각 종목의 오늘 봉 밖의 데이터는 전략에 넘기지 않는다.
        if k >= start:
            deposit = Decimal(0)
            if plan.due(day, last_month):
                deposit = plan.amount
                pf.deposit(deposit)
                bench.deposit(deposit)
                last_month = month_key(day)
                bench_buy = True
            # 첫 판단일에는 시작 금액도 새로 들어온 돈으로 본다 ("월급 들어오면 바로").
            fresh = deposit + (initial_cash if k == start else Decimal(0))
            histories = {s: series[s][: index[s][day] + 1] for s in symbols}
            if judgments is not None:
                records = rebalance(judgments.get(day), histories, pf, costs, limits)
            else:
                records = decide_basket(strategy, histories, weights, pf, costs, limits, fresh)
            for record in records:
                decisions.append(record)
                if record.action is not Action.HOLD:
                    pending[record.symbol] = record
            marks = {s: today[s].close for s in symbols}
            equity.append(
                EquityPoint(
                    session_date=day,
                    equity=pf.equity(marks),
                    cash=pf.cash,
                    invested=pf.invested(marks),
                    benchmark=bench.equity(marks),
                    contributed=pf.contributed or initial_cash,
                    deposit=deposit,
                )
            )

    return BacktestResult(
        decisions=decisions,
        fills=fills,
        equity=equity,
        metrics=_metrics(equity, initial_cash),
        pending=list(pending.values()),
    )


def _ratio(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def _max_drawdown(values: Sequence[float]) -> Decimal:
    peak = values[0]
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return _ratio(worst)


def _index(values: Sequence[Decimal], deposits: Sequence[Decimal]) -> list[float]:
    """입금 효과를 뺀 누적 수익 지수 (시간가중 수익률). 입금이 없으면 자산 / 첫날 자산과 같다."""
    out = [1.0]
    for (prev, cur), dep in zip(pairwise(values), deposits[1:], strict=True):
        out.append(out[-1] * (float((cur - dep) / prev) if prev > 0 else 1.0))
    return out


def _cagr(index: Sequence[float], start: date, end: date) -> Decimal:
    years = (end - start).days / 365.25
    if years <= 0 or index[-1] <= 0:
        return Decimal(0)
    return _ratio(index[-1] ** (1 / years) - 1)


def _money_weighted(flows: Sequence[tuple[date, Decimal]], end: date, final: Decimal) -> Decimal:
    """넣은 시점을 반영한 연 수익률 (XIRR). 매달 넣을 때 "내 돈이 해마다 몇 %씩 불었나"."""

    def npv(rate: float) -> float:
        total = float(final)
        for d, amount in flows:
            total -= float(amount) * (1 + rate) ** ((end - d).days / 365.25)
        return total

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return Decimal(0)
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return _ratio((lo + hi) / 2)


TRADING_DAYS = 252


def _vol_sharpe(index: Sequence[float]) -> tuple[Decimal, Decimal | None]:
    """일간 수익률 기준 연환산 변동성과 샤프 지수(무위험 수익률 0 가정)."""
    rets = [b / a - 1 for a, b in pairwise(index) if a > 0]
    if len(rets) < 2:
        return Decimal(0), None
    sd = statistics.stdev(rets)
    vol = sd * math.sqrt(TRADING_DAYS)
    sharpe = statistics.fmean(rets) * TRADING_DAYS / vol if vol > 0 else None
    return _ratio(vol), (_ratio(sharpe) if sharpe is not None else None)


def _annual_returns(
    equity: list[EquityPoint], idx: list[float], b_idx: list[float]
) -> list[YearReturn]:
    """연도별 수익률. 각 해의 기준은 전년도 마지막 지수(첫해는 시작)."""
    out: list[YearReturn] = []
    base_s, base_b = idx[0], b_idx[0]
    for i, p in enumerate(equity):
        last_of_year = (
            i == len(equity) - 1 or equity[i + 1].session_date.year != p.session_date.year
        )
        if last_of_year:
            out.append(
                YearReturn(
                    year=p.session_date.year,
                    strategy=_ratio(idx[i] / base_s - 1) if base_s else Decimal(0),
                    benchmark=_ratio(b_idx[i] / base_b - 1) if base_b else Decimal(0),
                )
            )
            base_s, base_b = idx[i], b_idx[i]
    return out


def _metrics(equity: list[EquityPoint], initial_cash: Decimal) -> Metrics:
    first, last = equity[0], equity[-1]
    deposits = [p.deposit for p in equity]
    idx = _index([p.equity for p in equity], deposits)
    b_idx = _index([p.benchmark for p in equity], deposits)
    vol, sharpe = _vol_sharpe(idx)
    b_vol, b_sharpe = _vol_sharpe(b_idx)
    contributed = last.contributed
    cagr = _cagr(idx, first.session_date, last.session_date)
    b_cagr = _cagr(b_idx, first.session_date, last.session_date)
    if any(d > 0 for d in deposits):
        # 입금이 있으면 연평균은 넣은 시점을 반영한 수익률로 (총수익과 같은 방향이 되도록).
        flows = [(first.session_date, initial_cash)] + [
            (p.session_date, p.deposit) for p in equity if p.deposit > 0
        ]
        cagr = _money_weighted(flows, last.session_date, last.equity)
        b_cagr = _money_weighted(flows, last.session_date, last.benchmark)
    return Metrics(
        start=first.session_date,
        end=last.session_date,
        initial_cash=initial_cash,
        final_equity=last.equity,
        total_return=_ratio(float(last.equity / contributed - 1)),
        cagr=cagr,
        max_drawdown=_max_drawdown(idx),
        exposure=_ratio(sum(1 for p in equity if p.invested > 0) / len(equity)),
        benchmark_final_equity=last.benchmark,
        benchmark_total_return=_ratio(float(last.benchmark / contributed - 1)),
        benchmark_cagr=b_cagr,
        benchmark_max_drawdown=_max_drawdown(b_idx),
        volatility=vol,
        sharpe=sharpe,
        benchmark_volatility=b_vol,
        benchmark_sharpe=b_sharpe,
        annual_returns=_annual_returns(equity, idx, b_idx),
        contributed=contributed,
        deposits=sum(1 for d in deposits if d > 0),
    )
