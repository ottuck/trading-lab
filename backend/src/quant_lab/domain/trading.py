"""판단과 모의 체결 규칙. 백테스트와 정기 DRY RUN이 이 함수들을 그대로 쓴다 (project.md 3절 원칙 3).

T일 종가로 판단(decide_basket, AI 봇은 rebalance) → T+1일 시가로 체결(execute).
여러 종목(최대 10개)을 한 계좌로 다루며, 매수는 budget(쓸 돈) 안에서 정하고
이미 들고 있어도 더 산다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.portfolio import (
    MIN_ORDER,
    QTY_STEP,
    CostModel,
    Portfolio,
    RiskLimits,
    affordable_qty,
)
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
    # 매수: 쓸 돈. 매도: 팔 금액 (None이면 전부, AI 봇)
    budget: Decimal | None = None
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

    deposit은 오늘 새로 들어온 돈이다: 정기 입금, 그리고 첫 판단일의 시작 금액.
    현금은 종목들이 함께 쓴다. weights(합 100)는 종목별 비율이다.
    """
    signals = {}
    for symbol, history in histories.items():
        signal = strategy.signal(history)
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
        by_spend[signal.spend].append(symbol)

    rebalance = bool(getattr(strategy, "rebalance", 0))
    closes = {s: history[-1].close for s, (history, _) in signals.items()}

    def share(amount: Decimal, symbols: list[str]) -> dict[str, Decimal]:
        total = sum(weights[s] for s in symbols)
        if not total:
            return {}
        if rebalance and amount > 0:
            # 비율 맞추기(팔지 않음): 새 돈을 비율보다 덜 들고 있는 종목부터 채운다
            held = {s: pf.qty(s) * closes[s] for s in symbols}
            goal = sum(held.values(), Decimal(0)) + amount
            need = {s: max(Decimal(0), goal * weights[s] / total - held[s]) for s in symbols}
            gap = sum(need.values(), Decimal(0))
            if gap > 0:
                return {s: amount * need[s] / gap for s in symbols}
        return {s: amount * weights[s] / total for s in symbols}

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
        assert order.budget is not None, "사는 모의 주문에는 쓸 돈(budget)이 있어야 한다"
        price = costs.buy_price(bar.open)
        cash = min(pf.cash, order.budget)
        qty = affordable_qty(cash, price, costs, limits, pf.qty(symbol) * price)
        if qty == 0:
            return None
        commission = costs.commission(qty * price)
        pf.buy(symbol, qty, price, commission)
        pnl = None
    elif order.action is Action.SELL:
        price = costs.sell_price(bar.open)
        qty = pf.qty(symbol)
        if order.budget is not None:  # 일부 팔기 (AI 봇 비중 맞추기)
            qty = min(qty, (order.budget / price).quantize(QTY_STEP, rounding=ROUND_DOWN))
        if qty == 0:
            return None
        commission = costs.sell_fees(qty * price)  # 위탁수수료 + SEC Fee
        pnl = pf.sell(symbol, qty, price, commission)
    else:
        return None
    side = order.action
    return Fill(side, order.session_date, bar.session_date, qty, price, commission, pnl, symbol)


REBALANCE_BAND = Decimal(2)  # 목표와 지금 비중 차이가 자산의 이 %보다 작으면 사고팔지 않는다


def rebalance(
    targets: Mapping[str, int] | None,
    histories: Mapping[str, Sequence[DailyBar]],
    pf: Portfolio,
    costs: CostModel,
    limits: RiskLimits,
    reasons: Mapping[str, str] | None = None,
    missing: str = "AI 판단이 없어 오늘은 지금 그대로 둬요",
) -> list[DecisionRecord]:
    """AI 봇: 목표 비중(%, 현금 제외)과 지금 비중의 차이를 팔 금액·살 금액으로 바꾼다.

    판단일 종가로 어림하고 다음 거래일 시가에 체결한다. 판 돈으로 사야 하므로 팔기를 먼저
    돌려준다 (체결도 이 순서). 차이가 작으면(REBALANCE_BAND) 그대로 두어 매일 조금씩 사고팔지
    않는다. 목표가 0이면 남김없이 판다. targets가 None(판단 실패)이면 모두 그대로 둔다.
    histories는 봇의 모든 종목이며 보유 종목을 빠짐없이 담아야 한다.
    """
    closes = {s: h[-1].close for s, h in histories.items()}
    equity = pf.equity(closes)
    band = max(MIN_ORDER, equity * REBALANCE_BAND / 100)
    reasons = reasons or {}
    plans: dict[str, tuple[Action, Decimal | None]] = {}
    for symbol, close in closes.items():
        held = pf.qty(symbol) * close
        if targets is None:
            plans[symbol] = (Action.HOLD, None)
            continue
        goal = equity * targets.get(symbol, 0) / 100
        if held > 0 and goal == 0:
            plans[symbol] = (Action.SELL, None)
        elif held - goal >= band:
            plans[symbol] = (Action.SELL, held - goal)
        elif goal - held >= band:
            plans[symbol] = (Action.BUY, goal - held)
        else:
            plans[symbol] = (Action.HOLD, None)

    # 살 돈 = 지금 현금 + 팔아서 들어올 돈(수수료·슬리피지만큼 줄여 어림). 모자라면 비율대로 줄인다
    proceeds = sum(
        (
            (pf.qty(s) * closes[s] if amount is None else amount)
            * (1 - costs.commission_rate - costs.slippage_bps / 10_000)
            for s, (action, amount) in plans.items()
            if action is Action.SELL
        ),
        Decimal(0),
    )
    wanted = sum((a for act, a in plans.values() if act is Action.BUY and a), Decimal(0))
    scale = min(Decimal(1), (pf.cash + proceeds) / wanted) if wanted > 0 else Decimal(1)

    records = []
    for side in (Action.SELL, Action.BUY, Action.HOLD):
        for symbol, (action, amount) in plans.items():
            if action is not side:
                continue
            blocked = None
            if action is Action.BUY:
                assert amount is not None
                amount *= scale
                est = costs.buy_price(closes[symbol])
                held = pf.qty(symbol) * est
                if affordable_qty(amount, est, costs, limits, held) == 0:
                    action, amount = Action.HOLD, None
                    blocked = "살 돈이 최소 주문 금액보다 적거나 위험 한도에 걸림"
            weight = pf.qty(symbol) * closes[symbol] / equity * 100 if equity else Decimal(0)
            target = Decimal(targets.get(symbol, 0)) if targets is not None else weight
            records.append(
                DecisionRecord(
                    session_date=histories[symbol][-1].session_date,
                    action=action,
                    target_long=target > 0,
                    holding=pf.qty(symbol) > 0,
                    reason=reasons.get(symbol, "") if targets is not None else missing,
                    indicators={
                        "target": target.quantize(Decimal("0.1")),
                        "weight": weight.quantize(Decimal("0.1")),
                    },
                    blocked=blocked,
                    budget=amount,
                    symbol=symbol,
                )
            )
    return records
