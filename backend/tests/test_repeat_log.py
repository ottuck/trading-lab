import logging
from datetime import UTC, datetime, timedelta

import pytest

from trading_lab.worker.repeat_log import RepeatedErrorLog

LOG = logging.getLogger("test.repeat_log")
T0 = datetime(2026, 10, 21, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def __call__(self) -> datetime:
        return self.at


def fail(errors: RepeatedErrorLog, exc: Exception, message: str = "주문 실패") -> None:
    try:
        raise exc
    except Exception:
        errors.exception(message)


def levels(caplog: pytest.LogCaptureFixture) -> list[tuple[str, bool]]:
    """(수준, 스택 포함 여부)"""
    return [(r.levelname, r.exc_info is not None) for r in caplog.records]


def test_same_error_is_logged_in_full_once_then_briefly(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    errors = RepeatedErrorLog(LOG, now=clock)
    with caplog.at_level(logging.INFO, logger=LOG.name):
        for i in range(3):
            # 메시지에 매번 다른 요청 ID가 붙어도 같은 오류로 본다
            fail(errors, RuntimeError(f"HTTP 500 (requestId={i})"))
            clock.at += timedelta(seconds=15)
    assert levels(caplog) == [("ERROR", True), ("WARNING", False), ("WARNING", False)]
    assert "같은 오류 3번째" in caplog.records[-1].getMessage()


def test_repeating_error_is_logged_in_full_again_every_hour(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    errors = RepeatedErrorLog(LOG, now=clock)
    with caplog.at_level(logging.INFO, logger=LOG.name):
        fail(errors, RuntimeError("x"))
        clock.at += timedelta(minutes=59)
        fail(errors, RuntimeError("x"))
        clock.at += timedelta(minutes=1)
        fail(errors, RuntimeError("x"))
    assert levels(caplog) == [("ERROR", True), ("WARNING", False), ("ERROR", True)]


def test_different_error_or_recovery_starts_over(caplog: pytest.LogCaptureFixture) -> None:
    errors = RepeatedErrorLog(LOG, now=Clock())
    with caplog.at_level(logging.INFO, logger=LOG.name):
        fail(errors, RuntimeError("x"))
        fail(errors, ValueError("x"))  # 다른 종류
        fail(errors, ValueError("x"), message="DB 오류")  # 다른 곳
        fail(errors, ValueError("x"), message="DB 오류")
        errors.ok()
        fail(errors, ValueError("x"), message="DB 오류")
        errors.ok()  # 한 번만 난 오류는 복구를 따로 남기지 않는다
    assert levels(caplog) == [
        ("ERROR", True),
        ("ERROR", True),
        ("ERROR", True),
        ("WARNING", False),
        ("INFO", False),
        ("ERROR", True),
    ]
    assert caplog.records[4].getMessage() == "DB 오류: 멈췄어요 (2번 반복)"
