from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from quant_lab.domain.bars import BarIssue, check_daily_bars, is_completed
from tests.fakes import WeekdayCalendar, make_bars

CAL = WeekdayCalendar()


def kinds(issues: list[BarIssue]) -> list[str]:
    return [i.kind for i in issues]


def test_missing_session_detected() -> None:
    bars = make_bars("QQQ", [100, 101, 102, 103])
    del bars[1]
    issues = check_daily_bars(bars, CAL)
    assert kinds(issues) == ["missing"]
    assert issues[0].session_date == date(2026, 1, 6)


def test_duplicate_and_non_session_detected() -> None:
    bars = make_bars("QQQ", [100, 101])
    saturday = replace(bars[1], session_date=date(2026, 1, 10))
    issues = check_daily_bars([*bars, bars[1], saturday], CAL)
    assert "duplicate" in kinds(issues)
    assert "non_session" in kinds(issues)


def test_is_completed_waits_for_close_plus_settle() -> None:
    day = date(2026, 1, 5)
    close = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)
    settle = timedelta(minutes=30)
    assert not is_completed(day, CAL, close + timedelta(minutes=29), settle)
    assert is_completed(day, CAL, close + settle, settle)
