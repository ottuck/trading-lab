from decimal import Decimal

from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits, affordable_qty

COSTS = CostModel(commission_rate=Decimal("0.001"), slippage_bps=Decimal(10))


def test_toss_fee_rules() -> None:
    # 위탁수수료는 $0.01 미만 절사, 매도는 SEC Fee(최소 $0.01) 추가
    assert COSTS.commission(Decimal("1234.567")) == Decimal("1.23")
    assert COSTS.sell_fees(Decimal("1000")) == Decimal("1.00") + Decimal("0.02")
    assert COSTS.sell_fees(Decimal("100")) == Decimal("0.10") + Decimal("0.01")


def test_round_trip_pnl_includes_commissions() -> None:
    pf = Portfolio(cash=Decimal(10_000))
    pf.buy(10, Decimal(100), Decimal(1))
    assert pf.cash == Decimal(8_999)
    assert pf.avg_cost == Decimal("100.1")
    pnl = pf.sell(10, Decimal(110), Decimal("1.10"))
    assert pnl == Decimal("97.90")  # 1100 - 1.10 - 1001
    assert pf.qty == 0
    assert pf.cash == Decimal("10097.90")


def test_affordable_qty_covers_commission() -> None:
    # 1000 / 100 = 10주지만 수수료 때문에 9주
    assert affordable_qty(Decimal(1000), Decimal(100), COSTS, RiskLimits(), Decimal(0)) == 9
