from datetime import date, timedelta

from quant_lab.application.demo_prices import demo_bars


def test_demo_prices_are_repeatable_and_leveraged() -> None:
    # 예시 시세(D1): 같은 씨앗이면 같은 값, 레버리지 ETF는 기초 지수의 배수, 상장 전엔 봉 없음
    days = [
        date(2023, 1, 2) + timedelta(days=i)
        for i in range(400)
        if (date(2023, 1, 2) + timedelta(days=i)).weekday() < 5
    ]
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
