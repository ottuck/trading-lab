from decimal import Decimal

from quant_lab.domain.strategy import ConnorsRsi2, DonchianBreakout, SmaCross, TrendFilter
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


def test_trend_filter_and_rsi2_signals() -> None:
    rising = make_bars("X", [100 + i for i in range(220)])
    tf = TrendFilter(sma=200).signal(rising, holding=False)
    assert tf is not None and tf.long

    # 상승 추세 중 이틀 연속 급락 → RSI(2) 과매도 매수, 이후 반등하면 청산
    dip = make_bars("X", [100 + i for i in range(218)] + [300, 290])
    s = ConnorsRsi2()
    entry = s.signal(dip, holding=False)
    assert entry is not None and entry.long
    bounce = make_bars("X", [100 + i for i in range(218)] + [300, 290, 330])
    exit_ = s.signal(bounce, holding=True)
    assert exit_ is not None and not exit_.long
