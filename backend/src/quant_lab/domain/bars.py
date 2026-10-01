"""일봉과 일봉 데이터 검증 규칙."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DailyBar:
    """미국 거래일 하루의 정규장 OHLCV. 가격은 수정주가 기준이다."""

    symbol: str
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class TradingCalendar(Protocol):
    """미국 거래소 달력. 구현은 adapters에 둔다."""

    def sessions(self, start: date, end: date) -> list[date]:
        """start~end(포함) 사이의 거래일."""
        ...

    def session_close(self, session: date) -> datetime:
        """해당 거래일 정규장 마감 시각 (UTC aware). 조기 폐장을 반영한다."""
        ...


def is_completed(
    session: date, calendar: TradingCalendar, now: datetime, settle: timedelta
) -> bool:
    """정규장 마감 + 확정 여유 시간이 지난 봉만 완료로 본다 (project.md 3절 원칙 2)."""
    return now >= calendar.session_close(session) + settle


@dataclass(frozen=True, slots=True)
class BarIssue:
    session_date: date | None
    kind: str
    detail: str


def check_daily_bars(
    bars: Sequence[DailyBar], calendar: TradingCalendar, max_abs_return: Decimal = Decimal("0.5")
) -> list[BarIssue]:
    """정렬된 일봉 목록에서 누락·중복·비거래일·OHLC 불일치·이상 변동을 찾는다.

    max_abs_return: 하루 종가 변동률이 이 값을 넘으면 이상치로 본다 (레버리지 ETF는 크게 잡는다).
    """
    if not bars:
        return []
    issues: list[BarIssue] = []
    dates = [b.session_date for b in bars]

    seen: set[date] = set()
    for d in dates:
        if d in seen:
            issues.append(BarIssue(d, "duplicate", "같은 거래일 봉이 두 번 있음"))
        seen.add(d)
    if dates != sorted(dates):
        issues.append(BarIssue(None, "unsorted", "거래일 오름차순이 아님"))

    expected = set(calendar.sessions(min(dates), max(dates)))
    for d in sorted(expected - seen):
        issues.append(BarIssue(d, "missing", "거래일인데 봉이 없음"))
    for d in sorted(seen - expected):
        issues.append(BarIssue(d, "non_session", "거래일이 아닌 날의 봉"))

    prev: DailyBar | None = None
    for b in bars:
        if min(b.open, b.high, b.low, b.close) <= 0 or b.volume < 0:
            issues.append(
                BarIssue(b.session_date, "non_positive", "가격이 0 이하이거나 거래량이 음수")
            )
        elif b.high < max(b.open, b.close) or b.low > min(b.open, b.close) or b.low > b.high:
            issues.append(BarIssue(b.session_date, "ohlc", "고가·저가가 시가·종가를 감싸지 않음"))
        if prev is not None and prev.close > 0:
            change = abs(b.close / prev.close - 1)
            if change > max_abs_return:
                issues.append(
                    BarIssue(b.session_date, "outlier", f"전일 대비 종가 변동 {change:.1%}")
                )
        prev = b
    return issues
