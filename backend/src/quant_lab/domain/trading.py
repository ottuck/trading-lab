"""판단과 모의 체결 규칙. 백테스트와 정기 DRY RUN이 이 함수들을 그대로 쓴다 (project.md 3절 원칙 3).

T일 종가로 판단(decide) → T+1일 시가로 체결(execute). 매수 수량은 체결 시점의 현금으로 정한다.
모으기 전략은 여러 종목(최대 10개)을 한 계좌로 다루며(decide_basket), 매수는 budget(쓸 돈) 안에서
정하고 이미 들고 있어도 더 산다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits, affordable_qty
from quant_lab.domain.strategy import Signal, Spend, Strategy

MAX_SYMBOLS = 10  # 봇 하나가 다루는 종목 수 상한 (2026-10-02 결정)


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    session_date: date
    action: Action
    target_long: bool
    holding: bool
    reason: str
    indicators: dict[str, Decimal]
    blocked: str | None = None
    budget: Decimal | None = None  # 매수에 쓸 돈. None이면 가진 현금 전부 (보통 전략)
    symbol: str = ""


@dataclass(frozen=True, slots=True)
class Fill:
    side: Action
    signal_date: date
    fill_date: date
    qty: Decimal
    price: Decimal
    commission: Decimal
    realized_pnl: Decimal | None
    symbol: str = ""


def decide(
    strategy: Strategy,
    history: Sequence[DailyBar],
    pf: Portfolio,
    costs: CostModel,
    limits: RiskLimits,
    deposit: Decimal = Decimal(0),
) -> DecisionRecord | None:
    """종목 하나의 판단. history의 마지막 봉(완료된 T일)까지 본다. 봉이 부족하면 None.

    모으기 전략은 종목이 하나인 decide_basket과 같다.
    """
    symbol = history[-1].symbol
    holding = pf.qty(symbol) > 0
    signal = strategy.signal(history, holding)
    if signal is None:
        return None
    if signal.spend is not None:
        one = {symbol: (history, signal)}
        return _basket(strategy, one, {symbol: 100}, pf, costs, limits, deposit)[0]
    today = history[-1]
    action = Action.HOLD
    blocked = None
    if signal.long and not holding:
        est = costs.buy_price(today.close)
        if affordable_qty(pf.cash, est, costs, limits, Decimal(0)) > 0:
            action = Action.BUY
        else:
            blocked = "현금 또는 위험 한도 부족으로 매수 불가"
    elif not signal.long and holding:
        action = Action.SELL
    return DecisionRecord(
        session_date=today.session_date,
        action=action,
        target_long=signal.long,
        holding=holding,
        reason=signal.reason,
        indicators=signal.indicators,
        blocked=blocked,
        symbol=symbol,
    )


def decide_basket(
    strategy: Strategy,
    histories: Mapping[str, Sequence[DailyBar]],
    weights: Mapping[str, int],
    pf: Portfolio,
    costs: CostModel,
    limits: RiskLimits,
    deposit: Decimal = Decimal(0),
) -> list[DecisionRecord]:
    """여러 종목을 한 계좌로 판단한다. 판단할 수 있는(봉이 충분한) 종목만 돌려준다.

    종목이 하나이고 보통 전략이면 decide와 같다. 여러 종목은 모으기 전략만 된다.
    deposit은 오늘 새로 들어온 돈이다: 정기 입금, 그리고 첫 판단일의 시작 금액.
    현금은 종목들이 함께 쓴다. weights(합 100)는 종목별 비율이다.
    """
    if len(histories) == 1:
        history = next(iter(histories.values()))
        record = decide(strategy, history, pf, costs, limits, deposit)
        return [record] if record is not None else []
    signals = {}
    for symbol, history in histories.items():
        signal = strategy.signal(history, pf.qty(symbol) > 0)
        if signal is not None:
            signals[symbol] = (history, signal)
    if not signals:
        return []
    return _basket(strategy, signals, weights, pf, costs, limits, deposit)


def _basket(
    strategy: Strategy,
    signals: Mapping[str, tuple[Sequence[DailyBar], Signal]],
    weights: Mapping[str, int],
    pf: Portfolio,
    costs: CostModel,
    limits: RiskLimits,
    deposit: Decimal,
) -> list[DecisionRecord]:
    """모으기 규칙으로 종목별 예산을 나눈다. pf.reserve(고점 때 모아 둔 돈)를 여기서 갱신한다.

    1. 입금일에 고점(NONE)인 종목의 몫은 모아 둔 돈이 된다.
    2. 입금일에 평소(DEPOSIT)인 종목들은 모아 둔 돈을 뺀 현금(그달 입금 + 잔돈)을
       비율대로 나눠 산다.
    3. 하락장(ALL)인 종목들은 남은 현금을 모아 둔 돈까지 모두 비율대로 나눠 산다
       (입금일이 아니어도).
    종목이 하나면 한 종목 규칙과 같다.
    """
    by_spend: dict[Spend, list[str]] = {spend: [] for spend in Spend}
    for symbol, (_, signal) in signals.items():
        if signal.spend is None:
            raise ValueError(f"{strategy.name}은 여러 종목을 다룰 수 없는 전략입니다")
        by_spend[signal.spend].append(symbol)

    def share(amount: Decimal, symbols: list[str]) -> dict[str, Decimal]:
        total = sum(weights[s] for s in symbols)
        return {s: amount * weights[s] / total for s in symbols} if total else {}

    budgets: dict[str, Decimal] = {}
    if deposit > 0:
        hot = sum((deposit * weights[s] / 100 for s in by_spend[Spend.NONE]), Decimal(0))
        pf.reserve = min(pf.cash, pf.reserve + hot)
        if by_spend[Spend.DEPOSIT]:
            budgets |= share(max(Decimal(0), pf.cash - pf.reserve), by_spend[Spend.DEPOSIT])
    if by_spend[Spend.ALL]:
        left = pf.cash - sum(budgets.values(), Decimal(0))
        budgets |= share(left, by_spend[Spend.ALL])
        pf.reserve = Decimal(0)

    records = []
    for symbol, (history, signal) in signals.items():
        today = history[-1]
        budget = budgets.get(symbol)
        action, blocked = Action.HOLD, None
        if budget is not None and budget > 0:
            est = costs.buy_price(today.close)
            if affordable_qty(budget, est, costs, limits, pf.qty(symbol) * est) > 0:
                action = Action.BUY
            elif signal.spend is Spend.DEPOSIT:
                blocked = "살 돈이 최소 주문 금액보다 적어 다음 입금일까지 모아 둠"
        records.append(
            DecisionRecord(
                session_date=today.session_date,
                action=action,
                target_long=signal.long,
                holding=pf.qty(symbol) > 0,
                reason=signal.reason,
                indicators=signal.indicators,
                blocked=blocked,
                budget=budget if action is Action.BUY else None,
                symbol=symbol,
            )
        )
    return records


def execute(
    pf: Portfolio, order: DecisionRecord, bar: DailyBar, costs: CostModel, limits: RiskLimits
) -> Fill | None:
    """order를 bar(T+1일)의 시가로 체결하고 pf를 갱신한다. 살 수 있는 수량이 없으면 None."""
    symbol = order.symbol or bar.symbol
    if order.action is Action.BUY:
        price = costs.buy_price(bar.open)
        cash = pf.cash if order.budget is None else min(pf.cash, order.budget)
        qty = affordable_qty(cash, price, costs, limits, pf.qty(symbol) * price)
        if qty == 0:
            return None
        commission = costs.commission(qty * price)
        pf.buy(symbol, qty, price, commission)
        pnl = None
    elif order.action is Action.SELL:
        price = costs.sell_price(bar.open)
        qty = pf.qty(symbol)
        if qty == 0:
            return None
        commission = costs.sell_fees(qty * price)  # 위탁수수료 + SEC Fee
        pnl = pf.sell(symbol, qty, price, commission)
    else:
        return None
    side = order.action
    return Fill(side, order.session_date, bar.session_date, qty, price, commission, pnl, symbol)
