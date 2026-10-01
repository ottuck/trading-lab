"""이벤트 테이블을 따라가며 중요한 것만 알림으로 보낸다.

평가 로직과 분리되어 있어 알림이 실패해도 판단·모의 체결에는 영향이 없다.
Worker 자신이 죽은 경우는 여기서 알릴 수 없다 (화면의 heartbeat 표시로 확인).
"""

import logging
from collections.abc import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.persistence.models import BotRow, EventRow

KST = ZoneInfo("Asia/Seoul")
ALWAYS_KINDS = {"sim_fill", "restart_pause", "missed_sessions", "config_change", "worker_start"}
TRADE_ACTIONS = {"BUY", "SELL"}
ICON = {"INFO": "ℹ️", "WARN": "⚠️", "ERROR": "🚨"}

log = logging.getLogger(__name__)


def should_notify(event: EventRow) -> bool:
    if event.level in ("WARN", "ERROR") or event.kind in ALWAYS_KINDS:
        return True
    # 판단은 매매 신호(BUY/SELL)일 때만 알린다. HOLD는 매일 나오므로 보내지 않는다.
    return event.kind == "decision" and (event.data or {}).get("action") in TRADE_ACTIONS


def format_event(event: EventRow, bot_name: str | None) -> str:
    when = event.at.astimezone(KST).strftime("%m-%d %H:%M")
    who = f"[{bot_name}] " if bot_name else ""
    return f"{ICON.get(event.level, '')} {who}{event.message}\n{when} KST · {event.kind} · DRY RUN"


class EventNotifier:
    def __init__(self, make_session: Callable[[], Session], send: Callable[[str], None]) -> None:
        self.make_session = make_session
        self.send = send
        self.cursor: int | None = None

    def start(self) -> None:
        """이미 있는 이벤트는 보내지 않고, 이 시점 이후 것부터 보낸다."""
        with self.make_session() as session:
            self.cursor = session.scalar(select(func.max(EventRow.id))) or 0

    def poll(self) -> int:
        if self.cursor is None:
            self.start()
        sent = 0
        with self.make_session() as session:
            events = list(
                session.scalars(
                    select(EventRow)
                    .where(EventRow.id > self.cursor)
                    .order_by(EventRow.id)
                    .limit(50)
                )
            )
            names = {
                bot_id: name for bot_id, name in session.execute(select(BotRow.id, BotRow.name))
            }
        for event in events:
            if should_notify(event):
                try:
                    self.send(
                        format_event(event, names.get(event.bot_id) if event.bot_id else None)
                    )
                except Exception as exc:
                    # 다음 주기에 같은 이벤트부터 다시 시도한다.
                    log.warning("알림 전송 실패: %s", exc)
                    return sent
                sent += 1
            self.cursor = event.id
        return sent
