from datetime import UTC, date, datetime

from quant_lab.adapters.market_calendar import get_calendar


def test_covers_qqq_history_and_known_closures() -> None:
    cal = get_calendar()
    assert cal.sessions(date(1999, 3, 10), date(1999, 3, 10)) == [date(1999, 3, 10)]
    # 9·11 휴장 (2001-09-11 ~ 09-14)
    assert cal.sessions(date(2001, 9, 10), date(2001, 9, 17)) == [
        date(2001, 9, 10),
        date(2001, 9, 17),
    ]


def test_regular_and_early_close_in_utc() -> None:
    cal = get_calendar()
    # 서머타임 중 16:00 ET = 20:00 UTC
    assert cal.session_close(date(2026, 10, 1)) == datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    # 추수감사절 다음 날 조기 폐장 13:00 ET(표준시) = 18:00 UTC
    assert cal.session_close(date(2026, 11, 27)) == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
