"""테스트용 합성 데이터와 가짜 의존성. 실제 토스 응답은 쓰지 않는다 (project.md 3절 원칙 8)."""

from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.broker import CandlePage


class WeekdayCalendar:
    """평일은 모두 거래일, 정규장 마감은 20:00 UTC로 단순화한 달력."""

    def __init__(self, holidays: Sequence[date] = ()) -> None:
        self.holidays = set(holidays)

    def sessions(self, start: date, end: date) -> list[date]:
        days = (start + timedelta(n) for n in range((end - start).days + 1))
        return [d for d in days if d.weekday() < 5 and d not in self.holidays]

    def session_close(self, session: date) -> datetime:
        return datetime.combine(session, time(20, 0), tzinfo=UTC)


def make_bars(
    symbol: str, closes: Sequence[float | str], start: date = date(2026, 1, 5)
) -> list[DailyBar]:
    """평일마다 하나씩 종가를 받아 일봉을 만든다. 시가는 전일 종가, 고가·저가는 ±1%."""
    calendar = WeekdayCalendar()
    days = calendar.sessions(start, start + timedelta(days=len(closes) * 2 + 7))[: len(closes)]
    bars = []
    prev = Decimal(str(closes[0]))
    for day, raw in zip(days, closes, strict=True):
        close = Decimal(str(raw))
        open_ = prev
        bars.append(
            DailyBar(
                symbol=symbol,
                session_date=day,
                open=open_,
                high=max(open_, close) * Decimal("1.01"),
                low=min(open_, close) * Decimal("0.99"),
                close=close,
                volume=Decimal(1000),
            )
        )
        prev = close
    return bars


class FakeBarSource:
    """iter_daily_pages를 흉내 낸다. 최신 페이지부터 page_size씩 돌려준다."""

    def __init__(self, bars: Sequence[DailyBar], page_size: int = 200) -> None:
        self.bars = sorted(bars, key=lambda b: b.session_date)
        self.page_size = page_size
        self.requests = 0

    def iter_daily_pages(self, symbol: str, since: date | None = None) -> Iterator[CandlePage]:
        end = len(self.bars)
        while end > 0:
            chunk = self.bars[max(0, end - self.page_size) : end]
            end -= self.page_size
            self.requests += 1
            yield CandlePage(bars=list(chunk), next_before="x" if end > 0 else None)
            if since is not None and chunk[0].session_date <= since:
                return
