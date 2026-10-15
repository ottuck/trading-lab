import math
from datetime import date, timedelta

from trading_lab.application.demo_prices import DEMO_START, demo_bars


def _weekdays(start: date, end: date) -> list[date]:
    days = (start + timedelta(days=i) for i in range((end - start).days + 1))
    return [d for d in days if d.weekday() < 5]


def test_demo_prices_are_repeatable_and_leveraged() -> None:
    # 예시 시세(D1): 같은 씨앗이면 같은 값, 레버리지 ETF는 기초 지수의 배수, 상장 전엔 봉 없음
    days = _weekdays(date(2023, 1, 2), date(2024, 2, 5))
    a, b = demo_bars(days), demo_bars(days)
    assert a == b and "SEMI" not in a
    qqq, tqqq = a["QQQ"], a["TQQQ"]
    move = float(qqq[-1].close / qqq[-2].close) - 1
    lev = float(tqqq[-1].close / tqqq[-2].close) - 1
    assert abs(lev - 3 * move) < 0.002
    assert a["MAGS"][0].session_date >= date(2023, 4, 11)
    assert all(
        bar.low <= min(bar.open, bar.close) and bar.high >= max(bar.open, bar.close) for bar in qqq
    )


def test_demo_prices_keep_the_past_and_look_like_a_market() -> None:
    # 시드는 6시간마다 오늘까지 다시 만든다: 기간이 늘어도 지난 값(가상 미래 포함)은 그대로여야 한다
    short = demo_bars(_weekdays(DEMO_START, date(2026, 6, 30)))
    long = demo_bars(_weekdays(DEMO_START, date(2027, 6, 30)))
    assert all(long[k][: len(v)] == v for k, v in short.items())

    # 실제 시장처럼: 흔들림이 몰려 오고 가끔 아주 큰 날이 있으며, 큰 하락장의 깊이가 역사와 비슷하다
    closes = [float(b.close) for b in long["VOO"]]
    r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    sd = math.sqrt(sum(x * x for x in r) / len(r))
    assert sum(abs(x) > 4 * sd for x in r) > 10  # 정규분포라면 거의 0번

    def drop(symbol: str, start: date, end: date) -> float:
        c = [float(b.close) for b in long[symbol] if start <= b.session_date <= end]
        return min(c[i] / max(c[: i + 1]) for i in range(len(c))) - 1

    assert -0.40 < drop("VOO", date(2020, 1, 2), date(2020, 6, 30)) < -0.28
    assert -0.95 < drop("NVDA", date(2007, 10, 1), date(2009, 6, 30)) < -0.75
    assert drop("TQQQ", date(2021, 11, 1), date(2022, 12, 30)) < -0.70
