from decimal import Decimal

import pytest

from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits, affordable_qty

COSTS = CostModel(commission_rate=Decimal("0.001"), slippage_bps=Decimal(10))


def test_slippage_moves_price_against_us() -> None:
    assert COSTS.buy_price(Decimal(100)) == Decimal("100.1")
    assert COSTS.sell_price(Decimal(100)) == Decimal("99.9")


def test_round_trip_pnl_includes_commissions() -> None:
    pf = Portfolio(cash=Decimal(10_000))
    pf.buy(10, Decimal(100), Decimal(1))
    assert pf.cash == Decimal(8_999)
    assert pf.avg_cost == Decimal("100.1")
    pnl = pf.sell(10, Decimal(110), Decimal("1.10"))
    assert pnl == Decimal("97.90")  # 1100 - 1.10 - 1001
    assert pf.qty == 0
    assert pf.cash == Decimal("10097.90")


def test_cannot_overspend_or_oversell() -> None:
    pf = Portfolio(cash=Decimal(100))
    with pytest.raises(ValueError):
        pf.buy(2, Decimal(60), Decimal(0))
    with pytest.raises(ValueError):
        pf.sell(1, Decimal(60), Decimal(0))


def test_affordable_qty_covers_commission() -> None:
    # 1000 / 100 = 10주지만 수수료 때문에 9주
    assert affordable_qty(Decimal(1000), Decimal(100), COSTS, RiskLimits(), Decimal(0)) == 9


def test_affordable_qty_respects_limits() -> None:
    limits = RiskLimits(max_position_value=Decimal(2_000), max_order_value=Decimal(5_000))
    assert affordable_qty(Decimal(100_000), Decimal(100), COSTS, limits, Decimal(1_500)) == 4
    assert affordable_qty(Decimal(100_000), Decimal(100), COSTS, limits, Decimal(2_000)) == 0
