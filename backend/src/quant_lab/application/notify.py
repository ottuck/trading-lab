"""이벤트 테이블을 따라가며 사람이 읽을 만한 것만 텔레그램으로 보낸다.

한 번에 생긴 소식(예: 아침 07:00 봇 여러 개의 체결·점검·주간 리포트)은 한 통으로 묶는다.

문장은 application/messages.py가 만든다 (화면의 '최근 활동'과 같은 말).
평가 로직과 분리되어 있어 알림이 실패해도 판단·모의 체결에는 영향이 없다.
Worker 자신이 죽은 경우는 외부 heartbeat ping(HEARTBEAT_PING_URL)으로 감시한다.
"""

import logging
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.application.messages import KST, event_message, telegram_text
from quant_lab.persistence.models import BotRow, EventRow

log = logging.getLogger(__name__)
# 텔레그램 메시지 한 통 최대 4096자. 여유를 두고 자른다.
MAX_TEXT = 3800


def render(event: EventRow, bot: tuple[str, str] | None) -> str | None:
    """텔레그램으로 보낼 문장. 보낼 필요가 없으면 None."""
    name, symbol = bot if bot else (None, None)
    msg = event_message(event.kind, event.level, event.message, event.data, name, symbol)
    if msg is None or not msg.notify:
        return None
    return telegram_text(msg, name, event.at.astimezone(KST).strftime("%m/%d %H:%M"))


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
            bots = {
                bot_id: (name, symbol)
                for bot_id, name, symbol in session.execute(
                    select(BotRow.id, BotRow.name, BotRow.symbol)
                )
            }
        # (마지막 이벤트 id, 묶은 문장, 소식 수) 단위로 보낸다.
        chunks: list[tuple[int, str, int]] = []
        for event in events:
            text = render(event, bots.get(event.bot_id) if event.bot_id else None)
            if text is None:
                continue
            if chunks and len(chunks[-1][1]) + len(text) + 2 <= MAX_TEXT:
                _, joined, n = chunks[-1]
                chunks[-1] = (event.id, f"{joined}\n\n{text}", n + 1)
            else:
                chunks.append((event.id, text, 1))
        for last_id, text, n in chunks:
            try:
                self.send(text)
            except Exception as exc:
                # 다음 주기에 보내지 못한 묶음부터 다시 시도한다.
                log.warning("알림 전송 실패: %s", exc)
                return sent
            sent += n
            self.cursor = last_id
        if events:
            self.cursor = events[-1].id
        return sent
