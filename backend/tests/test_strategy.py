from decimal import Decimal

from quant_lab.domain.strategy import DonchianBreakout, SmaCross
from tests.fakes import make_bars


def test_sma_cross_long_when_fast_above_slow() -> None:
    s = SmaCross(fast=2, slow=4)
    up = s.signal(make_bars("X", [10, 11, 12, 13]), holding=False)
    down = s.signal(make_bars("X", [13, 12, 11, 10]), holding=True)
    assert up is not None and up.long
    assert up.indicators == {"sma2": Decimal("12.5"), "sma4": Decimal("11.5")}
    assert down is not None and not down.long
    assert "SMA2" in down.reason


def test_donchian_enters_on_breakout_and_holds_inside_channel() -> None:
    s = DonchianBreakout(entry=3, exit=2)
    bars = make_bars("X", [10, 10, 10, 10, 13])
    entry = s.signal(bars, holding=False)
    assert entry is not None and entry.long

    inside = s.signal(make_bars("X", [10, 11, 12, 13, 12.9]), holding=True)
    assert inside is not None and inside.long
