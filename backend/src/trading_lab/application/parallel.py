"""평행세계의 나 (N4): 내 규칙을 하나씩 바꾼 "다른 나"들을 같은 일봉으로 함께 계산한다.

저장된 봇이 아니라 그때그때 계산하고 저장하지 않는다. 점수·등수는 매기지 않는다 (project.md 1절).
나처럼 투자(dip_saver) 전용이다.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from sqlalchemy.orm import Session

from trading_lab.application.backtesting import load_series
from trading_lab.domain.backtest import BacktestResult, run_backtest
from trading_lab.domain.portfolio import CostModel, RiskLimits
from trading_lab.domain.strategy import DipSaver


@dataclass(frozen=True)
class World:
    key: str
    title: str
    params: dict[str, int] | None  # 매달 그냥 사기는 규칙이 없어 None
    start: date
    end: date
    final_equity: Decimal
    contributed: Decimal
    cagr: Decimal  # 넣은 시점을 반영한 연 수익률 (XIRR)
    equity: list[tuple[date, Decimal]]  # 달마다 마지막 날 (그래프용)
    recent: list[tuple[str, Decimal]]  # 지난달·이번 달("YYYY-MM")에 산 금액 (월간 정리용)


def variants(params: dict[str, int], multi: bool = False) -> list[tuple[str, str, dict[str, int]]]:
    """내 규칙에서 한 가지씩만 바꾼 나들. 나와 규칙이 같아지는 것은 뺀다.

    multi(종목이 여럿)면 새 돈으로 비율을 맞추는 나도 넣는다.
    """
    out: list[tuple[str, str, dict[str, int]]] = []

    def add(key: str, title: str, **change: int) -> None:
        other = {**params, **change}
        if other != params:
            out.append((key, title, other))

    if params.get("regular", 1):
        if params.get("hot", 10):
            add("no_rest", "고점에도 안 쉬는 나", hot=0)
        else:
            add("rest", "많이 오르면 쉬는 나", hot=15)
        add("dip_only", "떨어졌을 때만 사는 나", regular=0)
    else:
        add("monthly", "매달 꾸준히 사는 나", regular=1)
    add("patient", "-20%까지 참는 나", dip=20)
    add("eager", "-5%에 바로 사는 나", dip=5)
    if multi and not params.get("rebalance"):
        add("rebalance", "비율 맞추는 나", rebalance=1)
    return out


def _monthly(points: list[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    """달마다 마지막 거래일만 남긴다 (마지막 날은 항상 남긴다)."""
    out = [p for p, q in pairwise(points) if p[0].month != q[0].month]
    return [*out, points[-1]] if points else out


def _months(end: date) -> list[str]:
    """end가 속한 달과 그 전달 ("YYYY-MM")"""
    prev = date(end.year - (end.month == 1), (end.month - 2) % 12 + 1, 1)
    return [f"{prev:%Y-%m}", f"{end:%Y-%m}"]


def _recent(end: date, buys: list[tuple[date, Decimal]]) -> list[tuple[str, Decimal]]:
    months = _months(end)
    return [(k, sum((v for d, v in buys if f"{d:%Y-%m}" == k), Decimal(0))) for k in months]


def world(
    key: str,
    title: str,
    params: dict[str, int] | None,
    result: BacktestResult,
    daily: bool = False,
) -> World:
    """daily면 그래프를 날마다 (시작한 지 얼마 안 된 봇), 아니면 달마다 마지막 날."""
    m = result.metrics
    points = [(p.session_date, p.equity) for p in result.equity]
    return World(
        key,
        title,
        params,
        m.start,
        m.end,
        m.final_equity,
        m.contributed,
        m.cagr,
        points if daily else _monthly(points),
        _recent(m.end, [(f.fill_date, f.qty * f.price + f.commission) for f in result.fills]),
    )


def dca_world(
    result: BacktestResult, title: str = "매달 그냥 사는 나", daily: bool = False
) -> World:
    """같은 날 같은 돈을 넣자마자 비율대로 사는 비교 기준 (백테스트의 benchmark)."""
    m = result.metrics
    points = [(p.session_date, p.benchmark) for p in result.equity]
    return World(
        "dca",
        title,
        None,
        m.start,
        m.end,
        m.benchmark_final_equity,
        m.contributed,
        m.benchmark_cagr,
        points if daily else _monthly(points),
        # 매달 그냥 사기는 넣은 돈을 다음 날 바로 다 산다
        _recent(m.end, [(p.session_date, p.deposit) for p in result.equity]),
    )


def copy_world(
    session: Session,
    weights: dict[str, int],
    params: dict[str, int],
    *,
    start: date,
    initial_cash: Decimal,
    costs: CostModel,
) -> tuple[World, World]:
    """나 카피 봇 규칙으로 start부터 산 결과와 그 종목·비율로 매달 그냥 산 결과 (날마다 그래프)."""
    me = DipSaver(**params)
    series = load_series(session, weights, me.warmup, start, None)
    base = run_backtest(series, me, initial_cash, costs, RiskLimits(), weights=weights)
    return (
        world("copy", "나 카피 봇 규칙", me.params, base, daily=True),
        dca_world(base, "매달 그냥 사기", daily=True),
    )


def parallel_worlds(
    session: Session,
    weights: dict[str, int],
    params: dict[str, int],
    *,
    start: date | None,
    end: date | None,
    initial_cash: Decimal,
    costs: CostModel,
) -> list[World]:
    """[나, 매달 그냥 사는 나, 다른 나들...]. 일봉은 한 번만 읽는다.

    모든 나는 같은 날 같은 돈을 넣는다 (넣는 돈을 바꾸면 수익률 비교가 어려워 바꾸지 않는다).
    """
    me = DipSaver(**params)
    series = load_series(session, weights, me.warmup, start, end)
    base = run_backtest(series, me, initial_cash, costs, RiskLimits(), weights=weights)
    worlds = [world("me", "나", me.params, base), dca_world(base)]
    for key, title, other in variants(me.params, multi=len(weights) > 1):
        strategy = DipSaver(**other)
        result = run_backtest(series, strategy, initial_cash, costs, RiskLimits(), weights=weights)
        worlds.append(world(key, title, strategy.params, result))
    return worlds
