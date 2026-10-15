"""exchange_calendars(XNYS) 기반 미국 거래소 달력."""

from datetime import UTC, date, datetime
from functools import lru_cache

import exchange_calendars as xc
import pandas as pd

# QQQ 상장(1999-03-10) 이전부터 다룰 수 있게 시작일을 넉넉히 잡는다. 기본값은 20년 전이다.
CALENDAR_START = "1990-01-01"


class XnysCalendar:
    def __init__(self) -> None:
        self._cal = xc.get_calendar("XNYS", start=CALENDAR_START)

    def sessions(self, start: date, end: date) -> list[date]:
        return [ts.date() for ts in self._cal.sessions_in_range(start, end)]

    def session_close(self, session: date) -> datetime:
        close = pd.Timestamp(self._cal.session_close(pd.Timestamp(session)))
        return close.to_pydatetime().astimezone(UTC)

    def is_session(self, day: date) -> bool:
        return bool(self._cal.is_session(pd.Timestamp(day)))

    @property
    def last_session(self) -> date:
        return self._cal.last_session.date()  # type: ignore[no-any-return]


@lru_cache
def get_calendar() -> XnysCalendar:
    return XnysCalendar()
