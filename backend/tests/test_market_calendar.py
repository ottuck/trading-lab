from datetime import UTC, date, datetime

from trading_lab.adapters.market_calendar import get_calendar


def test_regular_and_early_close_in_utc() -> None:
    cal = get_calendar()
    # 서머타임 중 16:00 ET = 20:00 UTC
    assert cal.session_close(date(2026, 10, 1)) == datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    # 추수감사절 다음 날 조기 폐장 13:00 ET(표준시) = 18:00 UTC
    assert cal.session_close(date(2026, 11, 27)) == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
