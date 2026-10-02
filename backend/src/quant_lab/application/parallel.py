"""평행세계의 나 (N4): 내 규칙을 하나씩 바꾼 "다른 나"들을 같은 일봉으로 함께 계산한다.

저장된 봇이 아니라 그때그때 계산하고 저장하지 않는다. 점수·등수는 매기지 않는다 (project.md 1절).
나처럼 모으기(dip_saver) 전용이다.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from sqlalchemy.orm import Session

from quant_lab.application.backtesting import load_series
from quant_lab.domain.backtest import BacktestResult, run_backtest
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import DipSaver


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


def variants(params: dict[str, int]) -> list[tuple[str, str, dict[str, int]]]:
    """내 규칙에서 한 가지씩만 바꾼 나들. 나와 규칙이 같아지는 것은 뺀다."""
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
    add("double", "두 배로 넣은 나", deposit=params["deposit"] * 2)
    return out


def _monthly(points: list[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    """달마다 마지막 거래일만 남긴다 (마지막 날은 항상 남긴다)."""
    out = [p for p, q in pairwise(points) if p[0].month != q[0].month]
    return [*out, points[-1]] if points else out


def _world(key: str, title: str, params: dict[str, int], result: BacktestResult) -> World:
    m = result.metrics
    return World(
        key,
        title,
        params,
        m.start,
        m.end,
        m.final_equity,
        m.contributed,
        m.cagr,
        _monthly([(p.session_date, p.equity) for p in result.equity]),
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

    두 배로 넣은 나는 시작 금액도 두 배다 (첫 판단일의 시작 금액은 그달 입금으로 본다).
    """
    me = DipSaver(**params)
    series = load_series(session, weights, me.warmup, start, end)
    base = run_backtest(series, me, initial_cash, costs, RiskLimits(), weights=weights)
    m = base.metrics
    worlds = [
        _world("me", "나", me.params, base),
        World(
            "dca",
            "매달 그냥 사는 나",
            None,
            m.start,
            m.end,
            m.benchmark_final_equity,
            m.contributed,
            m.benchmark_cagr,
            _monthly([(p.session_date, p.benchmark) for p in base.equity]),
        ),
    ]
    for key, title, other in variants(me.params):
        strategy = DipSaver(**other)
        cash = initial_cash * Decimal(other["deposit"]) / Decimal(me.deposit)
        result = run_backtest(series, strategy, cash, costs, RiskLimits(), weights=weights)
        worlds.append(_world(key, title, strategy.params, result))
    return worlds
