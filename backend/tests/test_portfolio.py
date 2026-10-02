from decimal import Decimal

from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits, affordable_qty

COSTS = CostModel(commission_rate=Decimal("0.001"), slippage_bps=Decimal(10))


def test_toss_fee_rules() -> None:
    # 위탁수수료는 $0.01 미만 절사, 매도는 SEC Fee(최소 $0.01) 추가
    assert COSTS.commission(Decimal("1234.567")) == Decimal("1.23")
    assert COSTS.sell_fees(Decimal("1000")) == Decimal("1.00") + Decimal("0.02")
    assert COSTS.sell_fees(Decimal("100")) == Decimal("0.10") + Decimal("0.01")
    # 체결금액 $10 이하는 위탁수수료 무료 (SEC Fee는 남는다)
    assert COSTS.commission(Decimal("9.99")) == 0
    assert COSTS.sell_fees(Decimal("9.99")) == Decimal("0.01")


def test_round_trip_pnl_includes_commissions() -> None:
    pf = Portfolio(cash=Decimal(10_000))
    pf.buy(Decimal(10), Decimal(100), Decimal(1))
    assert pf.cash == Decimal(8_999)
    assert pf.avg_cost == Decimal("100.1")
    pnl = pf.sell(Decimal(10), Decimal(110), Decimal("1.10"))
    assert pnl == Decimal("97.90")  # 1100 - 1.10 - 1001
    assert pf.qty == 0
    assert pf.cash == Decimal("10097.90")


def test_affordable_qty_is_fractional_and_covers_commission() -> None:
    # 토스 금액 주문처럼 소수점 6자리까지 산다. 수수료까지 예산 안에 들어온다.
    q = affordable_qty(Decimal(675), Decimal("700.86"), COSTS, RiskLimits(), Decimal(0))
    assert q == Decimal("0.962140")  # 한 주보다 적은 돈으로도 산다
    assert q * Decimal("700.86") + COSTS.commission(q * Decimal("700.86")) <= 675
    q = affordable_qty(Decimal(1000), Decimal(100), COSTS, RiskLimits(), Decimal(0))
    assert q == Decimal("9.990009")  # 10주어치에서 수수료 0.1%만큼 덜 산다
    # $1보다 적은 잔돈은 사지 않는다
    assert affordable_qty(Decimal("0.99"), Decimal(100), COSTS, RiskLimits(), Decimal(0)) == 0
