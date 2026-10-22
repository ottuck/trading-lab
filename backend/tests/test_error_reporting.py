import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from trading_lab.adapters.error_reporting import ErrorReportFilter, clean, init_error_reporting

LOG = logging.getLogger("test.error_reporting")
DSN = "https://key@o1.ingest.us.sentry.io/1"


@pytest.fixture(autouse=True)
def _enabled() -> None:
    # 다른 테스트가 마이그레이션을 돌리면 alembic의 fileConfig가 이미 있던 로거를 끈다.
    LOG.disabled = False


class Capture(Transport):
    """보내는 대신 메모리에 담는다."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def sent() -> Iterator[Capture]:
    transport = Capture()
    assert init_error_reporting(DSN, "abc1234", transport=transport)
    yield transport
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # 다른 테스트에 켜진 채로 남지 않게


def event(error_type: str, line: int, value: str = "x") -> dict[str, Any]:
    frame = {"filename": "worker/loop.py", "lineno": line}
    return {
        "exception": {
            "values": [{"type": error_type, "value": value, "stacktrace": {"frames": [frame]}}]
        }
    }


def test_an_error_log_is_sent_without_locals_breadcrumbs_or_secrets(sent: Capture) -> None:
    def fail() -> None:
        account_no = "1234567890123"  # noqa: F841 (지역 변수는 보내지 않는다)
        raise RuntimeError(
            "POST https://api.telegram.org/bot123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/sendMessage"
            " 실패, 계좌 9876543210123, owner@example.com"
        )

    LOG.info("breadcrumb이 될 수 있는 한 줄")
    LOG.warning("경고는 보내지 않는다")
    for _ in range(3):
        try:
            fail()
        except RuntimeError:
            LOG.exception("주문 처리 실패")
    sentry_sdk.flush()

    assert len(sent.events) == 1  # 같은 오류는 한 번만
    report = sent.events[0]
    text = json.dumps(report, ensure_ascii=False)
    assert "RuntimeError" in text
    assert report["release"] == "abc1234"
    assert report["environment"] == "production"
    for leaked in (
        "AAAAAAAAAAAAAAAA",
        "owner@example.com",
        "9876543210123",
        "1234567890123",
        "account_no",
        "breadcrumb이",
        "경고는",
    ):
        assert leaked not in text
    assert "vars" not in text
    assert "server_name" not in report
    assert not report.get("breadcrumbs")


def test_what_leaves_is_cleaned() -> None:
    sql = (
        "(psycopg.errors.UniqueViolation) duplicate key\n"
        "[SQL: INSERT INTO orders VALUES (%(price)s)]\n[parameters: {'price': 'secret-value'}]"
    )
    assert clean(sql) == "(psycopg.errors.UniqueViolation) duplicate key"
    scrubbed = clean(
        "Bearer abc.def-1 eyJhbGciOi.eyJzdWIi.c2ln sk-ant-api03-xyz token=hunter2"
        " postgresql://quant:pw@db/x user@example.com 계좌 12345678901"
    )
    for leaked in (
        "abc.def-1",
        "eyJhbGciOi",
        "sk-ant-api03",
        "hunter2",
        ":pw@",
        "@example",
        "1234567890",
    ):
        assert leaked not in scrubbed
    assert len(clean("x" * 1000)) == 300


def test_the_same_error_is_sent_once_an_hour() -> None:
    now = [0.0]
    only = ErrorReportFilter(now=lambda: now[0])
    assert only(event("TossError", 10), {}) is not None
    assert only(event("TossError", 10, "다른 메시지"), {}) is None
    assert only(event("TossError", 11), {}) is not None  # 다른 곳
    assert only(event("ValueError", 10), {}) is not None  # 다른 종류
    now[0] = 3599
    assert only(event("TossError", 10), {}) is None
    now[0] = 3600
    assert only(event("TossError", 10), {}) is not None
    # 예외 없이 남긴 로그는 로거와 문장 틀로 구분한다
    log_only = {"logger": "a", "logentry": {"message": "디스크 가득 %s", "params": ["/x"]}}
    sent = only(dict(log_only), {})
    assert sent is not None
    assert "params" not in sent["logentry"]
    assert only(dict(log_only), {}) is None
    assert init_error_reporting(None) is False
