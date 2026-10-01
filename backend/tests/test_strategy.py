from dataclasses import replace
from decimal import Decimal

import pytest

from quant_lab.domain.strategy import DonchianBreakout, SmaCross
from tests.fakes import make_bars


def test_sma_cross_needs_warmup() -> None:
    s = SmaCross(fast=2, slow=4)
    assert s.signal(make_bars("X", [1, 2, 3]), holding=False) is None


def test_sma_cross_long_when_fast_above_slow() -> None:
    s = SmaCross(fast=2, slow=4)
    up = s.signal(make_bars("X", [10, 11, 12, 13]), holding=False)
    down = s.signal(make_bars("X", [13, 12, 11, 10]), holding=True)
    assert up is not None and up.long
    assert up.indicators == {"sma2": Decimal("12.5"), "sma4": Decimal("11.5")}
    assert down is not None and not down.long
    assert "SMA2" in down.reason


def test_sma_cross_rejects_bad_params() -> None:
    with pytest.raises(ValueError):
        SmaCross(fast=5, slow=5)


def test_donchian_enters_on_breakout_and_holds_inside_channel() -> None:
    s = DonchianBreakout(entry=3, exit=2)
    bars = make_bars("X", [10, 10, 10, 10, 13])
    entry = s.signal(bars, holding=False)
    assert entry is not None and entry.long

    inside = s.signal(make_bars("X", [10, 11, 12, 13, 12.9]), holding=True)
    assert inside is not None and inside.long


def test_donchian_exits_below_lower_channel() -> None:
    s = DonchianBreakout(entry=3, exit=2)
    bars = make_bars("X", [10, 11, 12, 13, 11])
    # 직전 2일 최저가 아래로 종가가 떨어지게 만든다
    bars[-1] = replace(bars[-1], close=Decimal(5), low=Decimal(5))
    exit_ = s.signal(bars, holding=True)
    assert exit_ is not None and not exit_.long
