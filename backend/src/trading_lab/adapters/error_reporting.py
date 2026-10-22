"""예상 못 한 오류를 Sentry로 보낸다 (SENTRY_DSN이 있을 때만, project.md 6절).

ERROR로 남긴 로그(uvicorn이 남기는 API의 500 포함)와 처리 안 된 예외만 보낸다. 오류 하나를
이해하는 데 필요한 것(종류, 스택, 짧은 메시지)만 남기고, 이 서비스가 다루는 비밀값과 금융 정보가
섞일 수 있는 것은 모두 뺀다: 지역 변수, 요청, 사용자, breadcrumb, 로그의 추가 값, SQL과 그 값.
메시지에 든 토큰·키·이메일·긴 숫자(계좌 번호 등)는 가린다. 같은 오류는 한 시간에 한 번만 보내
무료 한도(월 5,000건)를 아낀다.
"""

import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.threading import ThreadingIntegration

REPEAT_WINDOW_S = 3600.0
MAX_KEYS = 200
TEXT_LIMIT = 300

# 가릴 것. 순서가 중요하다: URL 안의 계정 정보를 이메일보다 먼저 가린다.
_SCRUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<=://)[^/@\s]+@"), "[removed]@"),
    (re.compile(r"bot\d{6,}:[\w-]{20,}"), "bot[removed]"),
    (re.compile(r"(?i)bearer\s+[\w.~+/=-]+"), "Bearer [removed]"),
    (re.compile(r"sk-ant-[\w-]+"), "[removed]"),
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "[removed]"),
    (
        re.compile(r"(?i)\b(token|secret|password|api[_-]?key)(\"?\s*[:=]\s*\"?)[^\s\",}]+"),
        r"\1\2[removed]",
    ),
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[email]"),
    (re.compile(r"\b\d{9,}\b"), "[number]"),
)
# SQLAlchemy의 오류 메시지는 뒤에 실행한 SQL과 바인딩 값을 붙인다.
_SQL_TAIL = re.compile(r"\s*\[(SQL|parameters):.*", re.DOTALL)


def clean(text: str) -> str:
    text = _SQL_TAIL.sub("", text)
    for pattern, replacement in _SCRUBS:
        text = pattern.sub(replacement, text)
    return text[:TEXT_LIMIT]


class ErrorReportFilter:
    """Sentry의 before_send: 같은 오류는 한 시간에 한 번만 보내고, 나가는 내용을 정리한다."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._last_sent: dict[str, float] = {}

    def __call__(self, event: Any, hint: Any) -> Any | None:
        if not self._due(_key(event)):
            return None
        for name in ("request", "user", "extra", "breadcrumbs", "server_name"):
            event.pop(name, None)
        for value in event.get("exception", {}).get("values", []):
            if isinstance(value.get("value"), str):
                value["value"] = clean(value["value"])
            # 스택은 파일·함수·줄 번호만 남긴다 (소스 줄·지역 변수는 설정으로 껐고 한 번 더 지운다).
            for frame in value.get("stacktrace", {}).get("frames", []):
                for name in ("pre_context", "context_line", "post_context", "vars"):
                    frame.pop(name, None)
        entry = event.get("logentry")
        if entry:
            # 템플릿("... %s")은 남기고 값(params)은 버린다. 값이 들어간 완성 문장은 정리해서 둔다.
            entry.pop("params", None)
            for field in ("message", "formatted"):
                if isinstance(entry.get(field), str):
                    entry[field] = clean(entry[field])
        if isinstance(event.get("message"), str):
            event["message"] = clean(event["message"])
        return event

    def _due(self, key: str) -> bool:
        now = self._now()
        with self._lock:
            if len(self._last_sent) >= MAX_KEYS:
                self._last_sent.clear()
            previous = self._last_sent.get(key)
            if previous is not None and now - previous < REPEAT_WINDOW_S:
                return False
            self._last_sent[key] = now
            return True


def _key(event: Any) -> str:
    """예외 종류와 그것이 난 곳. 예외 없이 남긴 로그는 로거와 문장 틀로 구분한다."""
    values = event.get("exception", {}).get("values") or []
    if values:
        last = values[-1]
        frames = last.get("stacktrace", {}).get("frames") or []
        where = f"{frames[-1].get('filename')}:{frames[-1].get('lineno')}" if frames else ""
        return f"{last.get('type')}@{where}"
    entry = event.get("logentry") or {}
    return f"{event.get('logger')}|{entry.get('message') or event.get('message')}"


def init_error_reporting(
    dsn: str | None,
    release: str | None = None,
    *,
    transport: Any | None = None,
) -> bool:
    """DSN이 있으면 Sentry를 켠다. 없으면 아무것도 하지 않는다."""
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        release=release,
        environment="production",
        server_name="quant-lab",
        # SDK가 스스로 모을 수 있는 것은 모두 끈다: 사용자, 쿠키·헤더·본문·쿼리, DB 값, 지역 변수.
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {"request": {"mode": "off"}},
            "http_bodies": [],
            "url_query_params": {"mode": "off"},
            "database_query_data": False,
            "queues": False,
            "stack_frame_variables": False,
            # 스택 줄마다 붙는 소스 코드 줄도 보내지 않는다 (코드에 적힌 값이 새지 않게).
            "frame_context_lines": 0,
        },
        include_local_variables=False,
        include_source_context=False,
        max_breadcrumbs=0,
        max_value_length=TEXT_LIMIT,
        # 기본 연동은 쓰지 않는다: 요청·모듈 목록·인자 등을 모은다. 필요한 것만 하나씩 고른다.
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[
            LoggingIntegration(level=None, event_level=logging.ERROR),
            ExcepthookIntegration(),
            ThreadingIntegration(propagate_scope=False),
            DedupeIntegration(),
            AtexitIntegration(),
        ],
        before_send=ErrorReportFilter(),
        transport=transport,
    )
    return True
