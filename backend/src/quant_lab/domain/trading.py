"""판단과 모의 체결 규칙. 백테스트와 정기 DRY RUN이 이 함수들을 그대로 쓴다 (project.md 3절 원칙 3).

T일 종가로 판단(decide) → T+1일 시가로 체결(execute). 매수 수량은 체결 시점의 현금으로 정한다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits, affordable_qty
from quant_lab.domain.strategy import Strategy


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


@dataclass(frozen=True, slots=True)
class Fill:
    side: Action
    signal_date: date
    fill_date: date
    qty: int
    price: Decimal
    commission: Decimal
    realized_pnl: Decimal | None


def decide(
    strategy: Strategy,
    history: Sequence[DailyBar],
    pf: Portfolio,
    costs: CostModel,
    limits: RiskLimits,
) -> DecisionRecord | None:
    """history의 마지막 봉(완료된 T일)까지 보고 판단한다. 봉이 부족하면 None."""
    holding = pf.qty > 0
    signal = strategy.signal(history, holding)
    if signal is None:
        return None
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
    )


def execute(
    pf: Portfolio, order: DecisionRecord, bar: DailyBar, costs: CostModel, limits: RiskLimits
) -> Fill | None:
    """order를 bar(T+1일)의 시가로 체결하고 pf를 갱신한다. 살 수 있는 수량이 없으면 None."""
    if order.action is Action.BUY:
        price = costs.buy_price(bar.open)
        qty = affordable_qty(pf.cash, price, costs, limits, pf.qty * price)
        if qty == 0:
            return None
        commission = costs.commission(qty * price)
        pf.buy(qty, price, commission)
        pnl = None
    elif order.action is Action.SELL:
        price = costs.sell_price(bar.open)
        qty = pf.qty
        if qty == 0:
            return None
        commission = costs.sell_fees(qty * price)  # 위탁수수료 + SEC Fee
        pnl = pf.sell(qty, price, commission)
    else:
        return None
    return Fill(order.action, order.session_date, bar.session_date, qty, price, commission, pnl)
