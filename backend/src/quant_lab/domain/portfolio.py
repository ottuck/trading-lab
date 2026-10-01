"""모의 체결 비용, 포지션, 주문 수량 규칙."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
BPS = Decimal(10_000)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# 미국 증권거래위원회 수수료(SEC Fee): 매도에만 부과. 토스증권 고지 기준 (2026-04-02 체결분부터)
# max(매도대금 × 0.00206%, $0.01), 소수점 셋째 자리에서 반올림
SEC_FEE_RATE = Decimal("0.0000206")
SEC_FEE_MIN = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class CostModel:
    """수수료율(소수, 0.001 = 0.1%)과 슬리피지(bp). 실행 기록에 함께 저장한다.

    토스증권 미국주식 위탁수수료는 매매대금의 0.1%이며 $0.01 미만은 절사한다
    (2025-12-01부터 표준 요율, 2026-10-02 계좌 조회로 확인).
    """

    commission_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal(5)

    def buy_price(self, reference: Decimal) -> Decimal:
        return reference * (1 + self.slippage_bps / BPS)

    def sell_price(self, reference: Decimal) -> Decimal:
        return reference * (1 - self.slippage_bps / BPS)

    def commission(self, notional: Decimal) -> Decimal:
        """매수 비용: 위탁수수료 ($0.01 미만 절사)."""
        return (notional * self.commission_rate).quantize(CENT, rounding=ROUND_DOWN)

    def sell_fees(self, notional: Decimal) -> Decimal:
        """매도 비용: 위탁수수료 + SEC Fee."""
        sec = max(money(notional * SEC_FEE_RATE), SEC_FEE_MIN)
        return self.commission(notional) + sec


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """주문 수량 상한. None이면 제한 없음."""

    max_position_value: Decimal | None = None
    max_order_value: Decimal | None = None


@dataclass
class Portfolio:
    cash: Decimal
    qty: int = 0
    avg_cost: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)

    def equity(self, mark: Decimal) -> Decimal:
        return self.cash + self.qty * mark

    def buy(self, qty: int, price: Decimal, commission: Decimal) -> None:
        cost = qty * price + commission
        if qty <= 0 or cost > self.cash:
            raise ValueError("매수 수량이 0 이하이거나 현금이 부족합니다")
        self.avg_cost = (self.avg_cost * self.qty + qty * price + commission) / (self.qty + qty)
        self.qty += qty
        self.cash -= cost

    def sell(self, qty: int, price: Decimal, commission: Decimal) -> Decimal:
        if qty <= 0 or qty > self.qty:
            raise ValueError("매도 수량이 보유 수량을 넘습니다")
        proceeds = qty * price - commission
        pnl = proceeds - qty * self.avg_cost
        self.qty -= qty
        self.cash += proceeds
        self.realized_pnl += pnl
        if self.qty == 0:
            self.avg_cost = Decimal(0)
        return pnl


def affordable_qty(
    budget: Decimal, price: Decimal, costs: CostModel, limits: RiskLimits, position_value: Decimal
) -> int:
    """budget 안에서 수수료까지 감당할 수 있고 위험 한도를 넘지 않는 최대 정수 수량."""
    if limits.max_position_value is not None:
        budget = min(budget, limits.max_position_value - position_value)
    if limits.max_order_value is not None:
        budget = min(budget, limits.max_order_value)
    if budget <= 0 or price <= 0:
        return 0
    qty = int((budget / (price * (1 + costs.commission_rate))).to_integral_value(ROUND_DOWN))
    # 수수료 반올림으로 1주 초과하는 경우를 보정한다.
    while qty > 0 and qty * price + costs.commission(qty * price) > budget:
        qty -= 1
    return qty
