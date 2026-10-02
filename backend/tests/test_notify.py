from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application.notify import EventNotifier
from quant_lab.persistence.bots import add_event

NOW = datetime(2026, 10, 1, tzinfo=UTC)
DECISION = {
    "symbol": "QQQ",
    "strategy": "sma_cross",
    "params": {"fast": 50, "slow": 200},
    "indicators": {"sma50": "714.93", "sma200": "667.27"},
    "target_long": True,
    "equity": "10000",
    "total_return": "0",
}


def test_events_become_plain_messages_sent_once(engine: Engine, session: Session) -> None:
    make_session: Callable[[], Session] = sessionmaker(engine)
    add_event(session, NOW, "ERROR", "run_error", "시작 전 오류")
    session.commit()
    sent: list[str] = []
    notifier = EventNotifier(make_session, sent.append)
    notifier.start()  # 시작 전 이벤트는 보내지 않는다

    add_event(session, NOW, "INFO", "worker_start", "Worker 시작")  # 내부 기록
    add_event(
        session, NOW, "INFO", "decision", "x", data={**DECISION, "action": "HOLD", "holding": True}
    )
    add_event(session, NOW, "INFO", "decision_repeat", "이미 있음", data=DECISION)  # 내부 기록
    add_event(
        session, NOW, "INFO", "decision", "x", data={**DECISION, "action": "BUY", "holding": False}
    )
    add_event(
        session,
        NOW,
        "INFO",
        "sim_fill",
        "x",
        data={"symbol": "QQQ", "side": "BUY", "qty": 13, "price": "715.30", "commission": "9.29"},
    )
    add_event(
        session, NOW, "WARN", "run_skipped", "2026-10-01 일봉이 아직 없습니다 (마지막 2026-09-30)"
    )
    session.commit()

    assert notifier.poll() == 4
    assert notifier.poll() == 0
    assert [m.split("\n")[0] for m in sent] == [
        "📋 오늘의 점검 · QQQ",
        "🔴 매수 신호 · QQQ",
        "✅ QQQ 13주를 샀어요",
        "⏳ 오늘 판단을 잠시 미뤘어요",
    ]
    assert "상승 흐름이에요" in sent[1] and "내일 장이 열리면 QQQ를 사요" in sent[1]
    assert "아직 최신 시세가 도착하지 않았어요" in sent[3]
