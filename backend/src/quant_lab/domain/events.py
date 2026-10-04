"""이벤트 종류와 내용 형식 (events 테이블의 규약).

엔진·API·Worker가 이벤트를 남기고, 알림(텔레그램)과 화면 "최근 활동"이 읽는다.
읽는 쪽은 사람이 읽는 message 칸을 해석하지 않고 여기 정의한 data 값만 쓴다.
message 칸은 로그·디버깅용 원문이라 문구를 바꿔도 알림이 깨지지 않는다.
종류를 추가하면 tests/test_notify.py의 SAMPLES에도 예시를 넣어야 테스트가 통과한다.
"""

from enum import StrEnum
from typing import Any, NotRequired, TypedDict


class EventKind(StrEnum):
    WORKER_START = "worker_start"
    RESTART_RESUME = "restart_resume"
    RESTART_PAUSE = "restart_pause"  # 2026-10-02 이전 기록만 (지금은 만들지 않음)
    COMMAND = "command"
    CONFIG_CHANGE = "config_change"
    BOT_RESET = "bot_reset"
    BOT_DELETED = "bot_deleted"
    DECISION = "decision"
    DECISION_REPEAT = "decision_repeat"  # 같은 봉을 다시 평가함 (내부 기록)
    DEPOSIT = "deposit"
    SIM_FILL = "sim_fill"
    WEEKLY_REPORT = "weekly_report"
    MISSED_SESSIONS = "missed_sessions"
    RUN_SKIPPED = "run_skipped"
    RUN_ERROR = "run_error"
    WATCHLIST_SYNC = "watchlist_sync"  # 내부 기록
    LIVE_ORDER = "live_order"  # 실제 주문 상태가 바뀜 (실거래 R2)
    LIVE_CONTROL = "live_control"  # 비상 중지·재개
    NOTIFY_TEST = "notify_test"  # 화면의 "테스트 메시지 보내기"


class SkipReason(StrEnum):
    """판단을 미룬 이유. 15분 뒤 다시 시도한다."""

    NO_RECENT_SESSION = "no_recent_session"
    BOT_MISSING = "bot_missing"
    CALENDAR_MISMATCH = "calendar_mismatch"  # 거래소 달력과 증권사 달력이 다름
    DATA_NOT_READY = "data_not_ready"  # 판단할 날의 일봉이 아직 없음
    BAD_BARS = "bad_bars"  # 판단 구간 일봉에 누락·이상치
    NOT_ENOUGH_BARS = "not_enough_bars"
    DUPLICATE = "duplicate"  # 같은 봉을 다른 실행이 먼저 판단함
    BROKER_UNAVAILABLE = "broker_unavailable"  # 증권사 일시 장애


class ErrorReason(StrEnum):
    """봇을 멈춘 이유. 사람이 확인해야 한다."""

    BROKER_ACCESS = "broker_access"  # 허용 IP·인증
    UNEXPECTED = "unexpected"


class ConfigChange(StrEnum):
    CREATE = "create"
    SETTINGS = "settings"  # 전략·비용·위험 한도
    SYMBOLS = "symbols"
    RENAME = "rename"
    LIVE = "live"  # 실제로 따라 사기 비율 (after: {"live_ratio": "0.01" | None})


# --- 종류별 data 형식 ---


class RunData(TypedDict):
    reason: str  # SkipReason 또는 ErrorReason


class MissedSessionsData(TypedDict):
    count: int
    first: str  # 거래일 ISO 날짜
    last: str


class CommandData(TypedDict):
    command: str  # START·PAUSE·STOP·RUN_ONCE
    state: str  # 처리 뒤 봇 상태


class ConfigChangeData(TypedDict):
    change: str  # ConfigChange
    before: NotRequired[dict[str, Any]]
    after: dict[str, Any]  # symbols면 {"symbols": [{"symbol", "weight"}, ...]}
    dropped: NotRequired[list[str]]  # symbols: 더 사지 않고 들고만 있는 종목


class BotDeletedData(TypedDict):
    name: str
    symbol: str


class DepositData(TypedDict):
    symbol: str
    amount: str
    contributed: str


class FillData(TypedDict):
    symbol: str
    side: str  # BUY·SELL
    signal_date: str
    fill_date: str
    qty: str
    price: str
    commission: str
    realized_pnl: str | None


class LiveOrderData(TypedDict):
    symbol: str
    amount: str  # USD
    state: str  # domain/live.py LiveState
    reason: NotRequired[
        str
    ]  # 건너뜀(domain/live.py SkipReason)·거절(domain/broker.py RejectReason)
    filled_qty: NotRequired[str]
    auto: NotRequired[bool]  # 사람에게 묻지 않고 자동으로 내기로 함


class LiveControlData(TypedDict):
    halted: bool


class BalanceSummary(TypedDict):
    """판단일 종가로 계산한 모의 잔고 요약."""

    equity: str
    contributed: str  # 지금까지 넣은 돈 (시작 금액 + 입금)
    total_return: str
    qty: str  # 대표 종목 보유 수량
    close: str  # 대표 종목 종가
    closes: dict[str, str]  # 종목별 종가


class DecisionData(BalanceSummary):
    symbol: str
    action: str  # BUY·SELL·HOLD
    target_long: bool
    holding: bool
    strategy: str
    params: dict[str, Any]
    indicators: dict[str, Any]


class DecisionRepeatData(BalanceSummary):
    symbol: str


class WeeklyData(TypedDict):
    symbol: str
    week_start: str
    week_end: str
    equity: str
    total_return: str
    week_return: str
    hold_return: str
    buys: int
    sells: int
