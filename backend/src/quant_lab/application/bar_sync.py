"""토스 일봉을 DB 캐시와 맞춘다.

- 처음에는 상장일부터 전부 받는다.
- 이후에는 최신 페이지부터 저장된 마지막 거래일까지만 받는다.
- 겹치는 구간의 값이 저장값과 다르면 수정주가가 바뀐 것(분할·배당 등)으로 보고 전체를 다시 받는다.
- 정규장 마감 + 여유 시간이 지나지 않은 봉은 저장하지 않는다.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from quant_lab.adapters.toss.client import CandlePage
from quant_lab.domain.bars import (
    BarIssue,
    DailyBar,
    TradingCalendar,
    check_daily_bars,
    is_completed,
)
from quant_lab.persistence.bars import (
    delete_daily_bars,
    latest_session_date,
    load_daily_bars,
    upsert_daily_bars,
)

SOURCE = "toss"
# 정규장 마감 후 이만큼 지난 봉만 완료로 본다. 일봉 전략은 다음 날 시가에 체결하므로 넉넉히 둔다.
# 저장 뒤에 값이 바뀌면 증분 동기화의 겹침 비교가 감지해 "resync"로 남긴다 (tossApi.md 6절 #6).
DEFAULT_SETTLE = timedelta(hours=2)


class DailyBarSource(Protocol):
    def iter_daily_pages(self, symbol: str, since: date | None = None) -> Iterator[CandlePage]: ...


@dataclass
class SyncResult:
    symbol: str
    mode: Literal["full", "incremental", "resync"]
    saved: int = 0
    latest: date | None = None
    skipped_incomplete: list[date] = field(default_factory=list)
    issues: list[BarIssue] = field(default_factory=list)


def _collect(pages: Iterable[CandlePage]) -> list[DailyBar]:
    by_date: dict[date, DailyBar] = {}
    for page in pages:
        for bar in page.bars:
            by_date.setdefault(bar.session_date, bar)
    return [by_date[d] for d in sorted(by_date)]


def sync_daily_bars(
    source: DailyBarSource,
    session: Session,
    calendar: TradingCalendar,
    symbol: str,
    now: datetime,
    *,
    settle: timedelta = DEFAULT_SETTLE,
    max_abs_return: Decimal = Decimal("0.5"),
) -> SyncResult:
    latest = latest_session_date(session, symbol)
    if latest is None:
        return _full_sync(source, session, calendar, symbol, now, settle, max_abs_return, "full")

    fetched = _collect(source.iter_daily_pages(symbol, since=latest))
    completed = [b for b in fetched if is_completed(b.session_date, calendar, now, settle)]
    done = {b.session_date for b in completed}
    incomplete = [b.session_date for b in fetched if b.session_date not in done]

    overlap = [b for b in completed if b.session_date <= latest]
    if overlap:
        stored = {
            b.session_date: b
            for b in load_daily_bars(session, symbol, start=overlap[0].session_date, end=latest)
        }
        if any(stored.get(b.session_date) != b for b in overlap):
            return _full_sync(
                source, session, calendar, symbol, now, settle, max_abs_return, "resync"
            )

    new = [b for b in completed if b.session_date > latest]
    anchor = load_daily_bars(session, symbol, start=latest, end=latest)
    issues = check_daily_bars(anchor + new, calendar, max_abs_return) if new else []
    upsert_daily_bars(session, new, SOURCE, now)
    session.commit()
    return SyncResult(
        symbol=symbol,
        mode="incremental",
        saved=len(new),
        latest=new[-1].session_date if new else latest,
        skipped_incomplete=incomplete,
        issues=issues,
    )


def _full_sync(
    source: DailyBarSource,
    session: Session,
    calendar: TradingCalendar,
    symbol: str,
    now: datetime,
    settle: timedelta,
    max_abs_return: Decimal,
    mode: Literal["full", "resync"],
) -> SyncResult:
    fetched = _collect(source.iter_daily_pages(symbol))
    completed = [b for b in fetched if is_completed(b.session_date, calendar, now, settle)]
    done = {b.session_date for b in completed}
    incomplete = [b.session_date for b in fetched if b.session_date not in done]
    issues = check_daily_bars(completed, calendar, max_abs_return)
    # 지우고 다시 넣는 것을 한 트랜잭션으로 처리한다.
    delete_daily_bars(session, symbol)
    upsert_daily_bars(session, completed, SOURCE, now)
    session.commit()
    return SyncResult(
        symbol=symbol,
        mode=mode,
        saved=len(completed),
        latest=completed[-1].session_date if completed else None,
        skipped_incomplete=incomplete,
        issues=issues,
    )
