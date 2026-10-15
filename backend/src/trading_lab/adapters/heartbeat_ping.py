"""외부 감시 서비스(예: Healthchecks.io)에 주기적으로 생존 신호를 보낸다.

Worker나 PC·서버 전체가 멈추면 신호가 끊기고, 외부 서비스가 그 사실을 알린다.
URL에 비밀 식별자가 들어가므로 로그에 남기지 않는다.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

log = logging.getLogger(__name__)


class HeartbeatPinger:
    def __init__(
        self,
        url: str,
        *,
        interval: timedelta = timedelta(minutes=5),
        http: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._url = url
        self._interval = interval
        self._http = http or httpx.Client(timeout=10)
        self._now = now
        self._last: datetime | None = None

    def maybe_ping(self) -> bool:
        now = self._now()
        if self._last is not None and now - self._last < self._interval:
            return False
        try:
            self._http.get(self._url).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("외부 heartbeat 전송 실패: %s", type(exc).__name__)
            return False
        self._last = now
        return True
