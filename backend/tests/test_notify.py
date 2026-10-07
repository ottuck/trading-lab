from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application import notify_settings
from quant_lab.application.messages import event_message
from quant_lab.application.notify import EventNotifier
from quant_lab.domain.events import (
    AiJudgmentData,
    BalanceSummary,
    BotDeletedData,
    CommandData,
    ConfigChange,
    ConfigChangeData,
    DecisionData,
    DecisionRepeatData,
    DepositData,
    ErrorReason,
    EventKind,
    FillData,
    LiveControlData,
    LiveFundsData,
    LiveOrderData,
    LiveReconcileData,
    MissedSessionsData,
    RunData,
    ShortfallItem,
    SkipReason,
    WeeklyData,
)
from quant_lab.persistence.bots import add_event

NOW = datetime(2026, 10, 1, tzinfo=UTC)
BALANCE = BalanceSummary(
    equity="10000",
    contributed="10000",
    total_return="0",
    qty="0",
    close="715",
    closes={"QQQ": "715"},
)


def decision(action: str, holding: bool) -> DecisionData:
    return DecisionData(
        **BALANCE,
        symbol="QQQ",
        action=action,
        target_long=True,
        holding=holding,
        strategy="sma_cross",
        params={"fast": 50, "slow": 200},
        indicators={"sma50": "714.93", "sma200": "667.27"},
    )


FILL = FillData(
    symbol="QQQ",
    side="BUY",
    signal_date="2026-09-30",
    fill_date="2026-10-01",
    qty="13",
    price="715.30",
    commission="9.29",
    realized_pnl=None,
)

# 이벤트 종류마다 예시 하나. 종류를 추가하면 여기에도 넣어야 아래 테스트가 통과한다.
SAMPLES: dict[EventKind, Mapping[str, Any] | None] = {
    EventKind.WORKER_START: None,
    EventKind.RESTART_RESUME: None,
    EventKind.RESTART_PAUSE: None,
    EventKind.COMMAND: CommandData(command="PAUSE", state="PAUSED"),
    EventKind.CONFIG_CHANGE: ConfigChangeData(
        change=ConfigChange.SYMBOLS,
        before={"symbols": [{"symbol": "QQQ", "weight": 100}]},
        after={"symbols": [{"symbol": "QQQ", "weight": 60}, {"symbol": "TQQQ", "weight": 40}]},
        dropped=[],
    ),
    EventKind.BOT_RESET: None,
    EventKind.BOT_DELETED: BotDeletedData(name="qqq-sma", symbol="QQQ"),
    EventKind.DECISION: decision("SELL", True),
    EventKind.DECISION_REPEAT: DecisionRepeatData(**BALANCE, symbol="QQQ"),
    EventKind.DEPOSIT: DepositData(symbol="QQQ", amount="500", contributed="10500"),
    EventKind.SIM_FILL: FILL,
    EventKind.WEEKLY_REPORT: WeeklyData(
        symbol="QQQ",
        week_start="2026-09-28",
        week_end="2026-10-02",
        equity="10100",
        total_return="0.01",
        week_return="0.01",
        hold_return="0.012",
        buys=1,
        sells=0,
    ),
    EventKind.MISSED_SESSIONS: MissedSessionsData(count=2, first="2026-09-28", last="2026-09-29"),
    EventKind.RUN_SKIPPED: RunData(reason=SkipReason.BAD_BARS),
    EventKind.RUN_ERROR: RunData(reason=ErrorReason.BROKER_ACCESS),
    EventKind.WATCHLIST_SYNC: None,
    EventKind.LIVE_ORDER: LiveOrderData(
        symbol="VOO", amount="3.37", state="FILLED", filled_qty="0.004812"
    ),
    EventKind.LIVE_CONTROL: LiveControlData(halted=True),
    EventKind.NOTIFY_TEST: None,
    EventKind.LIVE_FUNDS: LiveFundsData(
        needed="6.75", available="2.86", trade_date="2026-10-26", deadline="10/26 22:35"
    ),
    EventKind.AI_JUDGMENT: AiJudgmentData(status="FAILED", session_date="2026-10-05"),
    EventKind.LIVE_RECONCILE: LiveReconcileData(
        shortfall=[ShortfallItem(symbol="VOO", held="0.002", bought="0.0048")]
    ),
}
HIDDEN = {EventKind.WORKER_START, EventKind.DECISION_REPEAT, EventKind.WATCHLIST_SYNC}


def test_every_event_kind_has_a_message() -> None:
    assert set(SAMPLES) == set(EventKind)
    for kind, data in SAMPLES.items():
        # 사람이 읽는 message 칸("로그 원문")은 해석하지 않는다
        msg = event_message(
            kind, "INFO", "로그 원문", dict(data) if data else None, "qqq-sma", "QQQ"
        )
        assert (msg is None) == (kind in HIDDEN), kind
        assert msg is None or ("로그 원문" not in msg.title + msg.body), kind


def test_quiet_restart_and_followed_ai_failure() -> None:
    # 배포로 다시 켜져도 판단할 때가 지나지 않았으면 텔레그램은 보내지 않는다 (앱 기록에는 남는다)
    quiet = event_message(EventKind.RESTART_RESUME, "INFO", "", {"overdue": False}, "qqq", "QQQ")
    late = event_message(EventKind.RESTART_RESUME, "INFO", "", {"overdue": True}, "qqq", "QQQ")
    assert quiet is not None and not quiet.notify and late is not None and late.notify
    # 실제로 따라 하는 봇의 AI 판단 실패는 "실제 주문만"에서도 보낸다
    live = notify_settings.NotifySettings(available=True, enabled=True, scope="live")
    assert not notify_settings.wants(live, EventKind.AI_JUDGMENT)
    assert notify_settings.wants(live, EventKind.AI_JUDGMENT, follows=True)


def test_events_become_plain_messages_sent_once(engine: Engine, session: Session) -> None:
    make_session: Callable[[], Session] = sessionmaker(engine)
    notify_settings.announce(session, True, False, NOW)  # Worker에 토큰이 있음
    notify_settings.update(session, True, "all", NOW)  # 화면: 켜기, 모의 투자 소식까지
    add_event(session, NOW, "ERROR", EventKind.RUN_ERROR, "시작 전 오류")
    session.commit()
    sent: list[str] = []
    notifier = EventNotifier(make_session, sent.append)
    notifier.start()  # 시작 전 이벤트는 보내지 않는다

    add_event(session, NOW, "INFO", EventKind.WORKER_START, "Worker 시작")  # 내부 기록
    hold = decision("HOLD", True)
    add_event(session, NOW, "INFO", EventKind.DECISION, "x", data=hold)  # 점검은 앱에만
    repeat = DecisionRepeatData(**BALANCE, symbol="QQQ")
    add_event(session, NOW, "INFO", EventKind.DECISION_REPEAT, "이미 있음", data=repeat)
    add_event(session, NOW, "INFO", EventKind.DECISION, "x", data=decision("BUY", False))
    add_event(session, NOW, "INFO", EventKind.SIM_FILL, "x", data=FILL)
    skipped = RunData(reason=SkipReason.DATA_NOT_READY)
    add_event(session, NOW, "WARN", EventKind.RUN_SKIPPED, "문구가 바뀌어도", data=skipped)
    session.commit()

    assert notifier.poll() == 3
    assert notifier.poll() == 0
    # 한 번에 생긴 소식은 한 통으로 묶는다
    assert len(sent) == 1
    parts = sent[0].split("\n\n")
    assert [p.split("\n")[0] for p in parts] == [
        "🔴 매수 신호 · QQQ",
        "✅ QQQ 13주를 샀어요",
        "⏳ 오늘 판단을 잠시 미뤘어요",
    ]
    assert "상승 흐름이에요" in parts[0] and "내일 장이 열리면 QQQ를 사요" in parts[0]
    assert "아직 최신 시세가 도착하지 않았어요" in parts[2]

    # "실제 주문만"을 고르면 모의 투자 소식은 보내지 않는다
    notify_settings.update(session, True, "live", NOW)
    add_event(session, NOW, "INFO", EventKind.DECISION, "x", data=decision("BUY", False))
    live = LiveOrderData(symbol="VOO", amount="3.37", state="WAITING_APPROVAL")
    add_event(session, NOW, "INFO", EventKind.LIVE_ORDER, "x", data=live)
    session.commit()
    assert notifier.poll() == 1
    assert sent[-1].startswith("🙋 실제로 살까요? · VOO")
