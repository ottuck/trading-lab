"""이벤트 테이블을 따라가며 중요한 것만 알림으로 보낸다.

평가 로직과 분리되어 있어 알림이 실패해도 판단·모의 체결에는 영향이 없다.
Worker 자신이 죽은 경우는 여기서 알릴 수 없어 외부 heartbeat ping(HEARTBEAT_PING_URL)으로 감시한다.
"""

import logging
from collections.abc import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.persistence.models import BotRow, EventRow

KST = ZoneInfo("Asia/Seoul")
ALWAYS_KINDS = {"sim_fill", "restart_pause", "missed_sessions", "config_change", "worker_start"}
TRADE_ACTIONS = {"BUY", "SELL"}  # 알림 아이콘 구분용
ICON = {"INFO": "ℹ️", "WARN": "⚠️", "ERROR": "🚨"}

log = logging.getLogger(__name__)


def should_notify(event: EventRow) -> bool:
    if event.level in ("WARN", "ERROR") or event.kind in ALWAYS_KINDS:
        return True
    # 판단은 매일 한 번 보낸다. HOLD도 "오늘도 정상 동작"을 알려주는 일일 점검 역할을 한다.
    return event.kind == "decision"


def format_event(event: EventRow, bot_name: str | None) -> str:
    when = event.at.astimezone(KST).strftime("%m-%d %H:%M")
    who = f"[{bot_name}] " if bot_name else ""
    data = event.data or {}
    icon = ICON.get(event.level, "")
    if event.kind == "decision":
        icon = "📈" if data.get("action") in TRADE_ACTIONS else "✅"
    lines = [f"{icon} {who}{event.message}"]
    if "equity" in data:
        ret = float(data.get("total_return", 0)) * 100
        lines.append(
            f"평가 자산 ${float(data['equity']):,.2f} ({ret:+.2f}%) · 보유 {data.get('qty', 0)}주"
        )
    lines.append(f"{when} KST · {event.kind} · DRY RUN")
    return "\n".join(lines)


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
