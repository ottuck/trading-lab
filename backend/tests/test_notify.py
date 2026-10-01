from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application.notify import EventNotifier
from quant_lab.persistence.bots import add_event

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def test_only_important_new_events_are_sent(engine: Engine, session: Session) -> None:
    make_session: Callable[[], Session] = sessionmaker(engine)
    add_event(session, NOW, "ERROR", "run_error", "시작 전 오류")
    session.commit()
    sent: list[str] = []
    notifier = EventNotifier(make_session, sent.append)
    notifier.start()  # 시작 전 이벤트는 보내지 않는다

    add_event(session, NOW, "INFO", "decision", "HOLD 판단", data={"action": "HOLD"})
    add_event(session, NOW, "INFO", "decision", "BUY 판단", data={"action": "BUY"})
    add_event(session, NOW, "INFO", "sim_fill", "BUY 10주 체결")
    add_event(session, NOW, "WARN", "run_skipped", "데이터 지연")
    session.commit()

    assert notifier.poll() == 3
    assert notifier.poll() == 0
    assert [m.split("\n")[0] for m in sent] == ["ℹ️ BUY 판단", "ℹ️ BUY 10주 체결", "⚠️ 데이터 지연"]
