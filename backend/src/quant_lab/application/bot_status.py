"""봇 상태 계산: 종목별 평가와 합계(장 마감 + 실시간), 마지막 판단, 하루 단위 자산 곡선.

화면 종류와 무관한 값만 만든다. 필드 이름은 API 응답과 같아서 API는 그대로 옮겨 담는다.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.application.messages import action_phrase, decision_reason
from quant_lab.domain.portfolio import Portfolio, RiskLimits, affordable_qty
from quant_lab.persistence.bots import bot_costs, bot_weights, list_bots
from quant_lab.persistence.models import (
    BotAccountRow,
    BotDepositRow,
    BotPositionRow,
    BotRow,
    DailyBarRow,
    DecisionRow,
    LiveBarRow,
    QuoteRow,
    RunRow,
    SimOrderRow,
)


@dataclass(frozen=True)
class PositionStatus:
    symbol: str
    weight: int  # 봇의 종목 비율 (봇에서 빠진 종목이면 0)
    qty: Decimal
    avg_cost: Decimal
    last_close: Decimal | None
    last_close_date: date | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    live_price: Decimal | None = None
    live_at: datetime | None = None
    live_change: Decimal | None = None


@dataclass(frozen=True)
class AccountStatus:
    initial_cash: Decimal
    cash: Decimal
    qty: Decimal  # 대표 종목
    avg_cost: Decimal
    realized_pnl: Decimal
    contributed: Decimal
    reserve: Decimal
    positions: list[PositionStatus]
    last_close: Decimal | None
    last_close_date: date | None
    market_value: Decimal | None = None  # 한 종목이라도 시세가 없으면 합계는 비운다
    unrealized_pnl: Decimal | None = None
    equity: Decimal | None = None
    total_return: Decimal | None = None  # 넣은 돈 대비
    live_price: Decimal | None = None
    live_at: datetime | None = None
    live_change: Decimal | None = None
    live_equity: Decimal | None = None
    live_unrealized_pnl: Decimal | None = None


@dataclass(frozen=True)
class DecisionStatus:
    id: int
    symbol: str
    session_date: date
    action: str
    target_long: bool
    holding: bool
    reason: str
    indicators: dict[str, Any]
    blocked: str | None
    created_at: datetime
    plain_reason: str = ""
    plain_action: str = ""


@dataclass(frozen=True)
class BotStatus:
    id: int
    name: str
    symbol: str
    symbols: list[dict[str, Any]]
    strategy: str
    params: dict[str, Any]
    state: str
    state_reason: str | None
    commission_rate: Decimal
    slippage_bps: Decimal
    risk: dict[str, Any]
    next_evaluation_at: datetime | None
    account: AccountStatus
    last_decision: DecisionStatus | None
    last_decisions: list[DecisionStatus]
    pending_order: SimOrderRow | None
    pending_orders: list[SimOrderRow]
    last_run: RunRow | None
    data_latest_date: date | None
    data_fetched_at: datetime | None
    data_source: str | None
    live_ratio: Decimal | None = None  # 실제로 따라 사기 비율 (꺼짐이면 None)
    live_streak: int = 0  # 연속으로 문제없이 체결된 실제 주문


@dataclass(frozen=True)
class EquityPoint:
    date: date
    equity: Decimal
    contributed: Decimal  # 이날까지 넣은 돈
    benchmark: Decimal  # 같은 돈으로 그냥 들고 있었다면
    live: bool = field(default=False)


def _last_bar(session: Session, symbol: str) -> DailyBarRow | None:
    return session.scalars(
        select(DailyBarRow)
        .where(DailyBarRow.symbol == symbol)
        .order_by(DailyBarRow.session_date.desc())
        .limit(1)
    ).first()


def account_status(session: Session, bot: BotRow) -> AccountStatus:
    """종목별 보유를 장 마감 가격(+ 있으면 실시간 가격)으로 평가하고 합계를 낸다."""
    acc = session.get_one(BotAccountRow, bot.id)
    held = {
        p.symbol: p
        for p in session.scalars(select(BotPositionRow).where(BotPositionRow.bot_id == bot.id))
    }
    weights = bot_weights(bot)
    positions: list[PositionStatus] = []
    complete = True
    market_value = cost_basis = live_value = Decimal(0)
    live_at: datetime | None = None
    for symbol in list(weights) + [s for s in held if s not in weights]:
        pos = held.get(symbol)
        qty = pos.qty if pos else Decimal(0)
        avg = pos.avg_cost if pos else Decimal(0)
        last = _last_bar(session, symbol)
        quote = session.get(QuoteRow, symbol)
        if last is None:
            complete = False
            positions.append(
                PositionStatus(symbol, weights.get(symbol, 0), qty, avg, None, None, None, None)
            )
            continue
        value = qty * last.close
        market_value += value
        cost_basis += qty * avg
        live_value += qty * (quote.price if quote else last.close)
        if quote is not None:
            live_at = max(live_at, quote.quoted_at) if live_at else quote.quoted_at
        positions.append(
            PositionStatus(
                symbol=symbol,
                weight=weights.get(symbol, 0),
                qty=qty,
                avg_cost=avg,
                last_close=last.close,
                last_close_date=last.session_date,
                market_value=value,
                unrealized_pnl=value - qty * avg,
                live_price=quote.price if quote else None,
                live_at=quote.quoted_at if quote else None,
                live_change=quote.price / last.close - 1 if quote and last.close else None,
            )
        )
    main = positions[0]
    common: dict[str, Any] = {
        "initial_cash": bot.initial_cash,
        "cash": acc.cash,
        "qty": main.qty,
        "avg_cost": main.avg_cost,
        "realized_pnl": acc.realized_pnl,
        "contributed": acc.contributed,
        "reserve": acc.reserve,
        "positions": positions,
        "last_close": main.last_close,
        "last_close_date": main.last_close_date,
    }
    if not complete:
        return AccountStatus(**common)
    equity = acc.cash + market_value
    live: dict[str, Any] = {}
    if live_at is not None:
        live = {
            "live_price": main.live_price,
            "live_at": live_at,
            "live_change": main.live_change,
            "live_equity": acc.cash + live_value,
            "live_unrealized_pnl": live_value - cost_basis,
        }
    return AccountStatus(
        **common,
        market_value=market_value,
        unrealized_pnl=market_value - cost_basis,
        equity=equity,
        total_return=(equity / acc.contributed - 1) if acc.contributed else None,
        **live,
    )


def decision_status(row: DecisionRow, bot: BotRow | None = None) -> DecisionStatus:
    """bot을 주면 쉬운 말 설명(plain_reason·plain_action)도 채운다."""
    plain_reason = plain_action = ""
    if bot is not None:
        strategy = row.strategy or {}
        plain_reason = decision_reason(
            strategy.get("name", bot.strategy),
            strategy.get("params", bot.params),
            row.indicators,
            row.target_long,
            row.holding,
            action=row.action,
        )
        plain_action = action_phrase(row.action, row.holding, row.symbol)
    return DecisionStatus(
        id=row.id,
        symbol=row.symbol,
        session_date=row.session_date,
        action=row.action,
        target_long=row.target_long,
        holding=row.holding,
        reason=row.reason,
        indicators=row.indicators,
        blocked=row.blocked,
        created_at=row.created_at,
        plain_reason=plain_reason,
        plain_action=plain_action,
    )


def bot_status(session: Session, bot: BotRow) -> BotStatus:
    last_decision = session.scalars(
        select(DecisionRow)
        .where(DecisionRow.bot_id == bot.id)
        .order_by(DecisionRow.session_date.desc())
        .limit(1)
    ).first()
    last_decisions = (
        list(
            session.scalars(
                select(DecisionRow).where(
                    DecisionRow.bot_id == bot.id,
                    DecisionRow.session_date == last_decision.session_date,
                )
            )
        )
        if last_decision
        else []
    )
    weights = bot_weights(bot)
    order = {s: i for i, s in enumerate(weights)}
    last_decisions.sort(key=lambda d: order.get(d.symbol, len(order)))
    main = next((d for d in last_decisions if d.symbol == bot.symbol), last_decision)
    pending = list(
        session.scalars(
            select(SimOrderRow)
            .where(SimOrderRow.bot_id == bot.id, SimOrderRow.status == "PENDING")
            .order_by(SimOrderRow.id)
        )
    )
    last_run = session.scalars(
        select(RunRow).where(RunRow.bot_id == bot.id).order_by(RunRow.started_at.desc()).limit(1)
    ).first()
    data_latest, data_fetched = session.execute(
        select(func.max(DailyBarRow.session_date), func.max(DailyBarRow.fetched_at)).where(
            DailyBarRow.symbol == bot.symbol
        )
    ).one()
    last_bar = _last_bar(session, bot.symbol)
    return BotStatus(
        id=bot.id,
        name=bot.name,
        symbol=bot.symbol,
        symbols=[{"symbol": s, "weight": w} for s, w in weights.items()],
        strategy=bot.strategy,
        params=bot.params,
        state=bot.state,
        state_reason=bot.state_reason,
        commission_rate=bot.commission_rate,
        slippage_bps=bot.slippage_bps,
        risk=bot.risk,
        next_evaluation_at=bot.next_evaluation_at,
        account=account_status(session, bot),
        last_decision=decision_status(main, bot) if main else None,
        last_decisions=[decision_status(d, bot) for d in last_decisions],
        pending_order=pending[0] if pending else None,
        pending_orders=pending,
        last_run=last_run,
        data_latest_date=data_latest,
        data_fetched_at=data_fetched,
        data_source=last_bar.source if last_bar else None,
        live_ratio=bot.live_ratio,
        live_streak=bot.live_streak,
    )


def all_bot_statuses(session: Session) -> list[BotStatus]:
    """replay가 만든 임시 봇은 뺀다."""
    return [bot_status(session, b) for b in list_bots(session) if not b.name.startswith("replay-")]


def equity_curve(session: Session, bot: BotRow) -> list[EquityPoint]:
    """하루 단위 모의 자산. 첫 판단일부터 입금·체결 기록을 장 마감 가격에 다시 적용한다.

    benchmark는 같은 돈으로 "그냥 들고 있었다면"의 자산이다. 첫 판단 다음 날 시가에 종목 비율대로
    전부 사고, 입금이 있으면 다음 날 시가에 또 산다 (백테스트의 비교 기준과 같은 규칙).
    여러 종목은 모든 종목에 봉이 있는 날만 그린다. 오늘 진행 중인 장이 있으면 실시간 한 점을 더한다.
    """
    weights = bot_weights(bot)
    first = session.scalar(
        select(func.min(DecisionRow.session_date)).where(DecisionRow.bot_id == bot.id)
    )
    start = first or bot.created_at.date()
    fills = [
        (
            o.fill_date,
            o.symbol,
            o.side,
            o.qty or 0,
            (o.qty or 0) * (o.price or 0),
            o.commission or 0,
        )
        for o in session.scalars(
            select(SimOrderRow)
            .where(SimOrderRow.bot_id == bot.id, SimOrderRow.status == "FILLED")
            .order_by(SimOrderRow.fill_date, SimOrderRow.id)
        )
        if o.fill_date is not None
    ]
    deposits = {
        d.session_date: d.amount
        for d in session.scalars(select(BotDepositRow).where(BotDepositRow.bot_id == bot.id))
    }
    bars: dict[str, dict[date, DailyBarRow]] = {
        s: {
            r.session_date: r
            for r in session.scalars(
                select(DailyBarRow).where(
                    DailyBarRow.symbol == s, DailyBarRow.session_date >= start
                )
            )
        }
        for s in weights
    }
    days = sorted(set.intersection(*(set(b) for b in bars.values())))
    costs = bot_costs(bot)
    cash, contributed, i = bot.initial_cash, bot.initial_cash, 0
    qty: dict[str, Decimal] = defaultdict(Decimal)
    bench = Portfolio(cash=bot.initial_cash)
    bench_buy = False
    out: list[EquityPoint] = []
    for n, day in enumerate(days):
        if bench_buy or n == 1:
            budget_base = bench.cash
            for s, w in weights.items():
                price = costs.buy_price(bars[s][day].open)
                q = affordable_qty(
                    min(bench.cash, budget_base * w / 100), price, costs, RiskLimits(), Decimal(0)
                )
                if q > 0:
                    bench.buy(s, q, price, costs.commission(q * price))
            bench_buy = False
        while i < len(fills) and fills[i][0] <= day:
            _, symbol, side, k, notional, commission = fills[i]
            if side == "BUY":
                cash, qty[symbol] = cash - notional - commission, qty[symbol] + k
            else:
                cash, qty[symbol] = cash + notional - commission, qty[symbol] - k
            i += 1
        if day in deposits:
            amount = deposits[day]
            cash, contributed = cash + amount, contributed + amount
            bench.deposit(amount)
            bench_buy = True
        marks = {s: bars[s][day].close for s in weights}
        held_value = sum((qty[s] * marks.get(s, Decimal(0)) for s in qty), Decimal(0))
        out.append(EquityPoint(day, cash + held_value, contributed, bench.equity(marks)))
    live = {s: (session.get(LiveBarRow, s), session.get(QuoteRow, s)) for s in weights}
    if out and all(
        lb is not None and q is not None and lb.session_date > out[-1].date
        for lb, q in live.values()
    ):
        marks = {s: q.price for s, (_, q) in live.items() if q is not None}
        live_day = max(lb.session_date for lb, _ in live.values() if lb is not None)
        held_value = sum((qty[s] * marks.get(s, Decimal(0)) for s in qty), Decimal(0))
        out.append(
            EquityPoint(live_day, cash + held_value, contributed, bench.equity(marks), live=True)
        )
    return out
