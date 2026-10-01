from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from quant_lab.domain.bars import BarIssue, check_daily_bars, is_completed
from tests.fakes import WeekdayCalendar, make_bars

CAL = WeekdayCalendar()


def kinds(issues: list[BarIssue]) -> list[str]:
    return [i.kind for i in issues]


def test_clean_bars_have_no_issues() -> None:
    assert check_daily_bars(make_bars("QQQ", [100, 101, 102, 103]), CAL) == []


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


def test_ohlc_inconsistency_detected() -> None:
    bars = make_bars("QQQ", [100, 101])
    bars[1] = replace(bars[1], high=Decimal(50))
    assert "ohlc" in kinds(check_daily_bars(bars, CAL))


def test_outlier_threshold() -> None:
    bars = make_bars("QQQ", [100, 170])
    assert "outlier" in kinds(check_daily_bars(bars, CAL))
    assert "outlier" not in kinds(check_daily_bars(bars, CAL, max_abs_return=Decimal("0.9")))


def test_is_completed_waits_for_close_plus_settle() -> None:
    day = date(2026, 1, 5)
    close = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)
    settle = timedelta(minutes=30)
    assert not is_completed(day, CAL, close + timedelta(minutes=29), settle)
    assert is_completed(day, CAL, close + settle, settle)
