"""주기마다 같은 예외가 되풀이될 때 로그를 줄인다.

Worker는 15초마다 돌고 실패해도 다음 주기에 다시 시도한다. 그대로 두면 같은 오류가
하루 수천 번 스택과 함께 ERROR로 남는다(오류 수집 서비스를 붙이면 그 한도도 다 쓴다).
그래서 처음 한 번과 그 뒤 1시간마다는 스택과 함께 ERROR로, 그 사이에는 한 줄 WARNING으로
남긴다. 같은 오류는 같은 곳에서 난 같은 종류의 예외로 본다(메시지에는 요청 ID처럼 매번
달라지는 값이 들어갈 수 있어 비교하지 않는다).
"""

import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

REMIND_EVERY = timedelta(hours=1)

type _Key = tuple[str, str, str, int]


class RepeatedErrorLog:
    def __init__(
        self,
        logger: logging.Logger,
        *,
        remind_every: timedelta = REMIND_EVERY,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._log = logger
        self._remind_every = remind_every
        self._now = now
        self._key: _Key | None = None
        self._count = 0
        self._last_full = datetime.min.replace(tzinfo=UTC)

    def exception(self, message: str) -> None:
        """except 블록 안에서 부른다."""
        exc = sys.exc_info()[1]
        key = _key(message, exc)
        now = self._now()
        if key != self._key:
            self._key, self._count, self._last_full = key, 1, now
            self._log.exception("%s", message)
            return
        self._count += 1
        if now - self._last_full >= self._remind_every:
            self._last_full = now
            self._log.exception("%s (같은 오류 %d번째)", message, self._count)
        else:
            self._log.warning("%s (같은 오류 %d번째): %s", message, self._count, type(exc).__name__)

    def ok(self) -> None:
        """이번 주기가 성공했을 때 부른다. 다음 오류는 다시 처음부터 자세히 남긴다."""
        if self._key is not None and self._count > 1:
            self._log.info("%s: 멈췄어요 (%d번 반복)", self._key[0], self._count)
        self._key, self._count = None, 0


def _key(message: str, exc: BaseException | None) -> _Key:
    if exc is None:
        return (message, "", "", 0)
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    where = (tb.tb_frame.f_code.co_filename, tb.tb_lineno) if tb is not None else ("", 0)
    return (message, type(exc).__qualname__, *where)
