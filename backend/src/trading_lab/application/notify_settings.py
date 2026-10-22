"""텔레그램 알림 설정 (화면의 설정 → 계좌와 알림).

켜기·끄기와 받을 알림 범위만 DB에 둔다. 봇 토큰·채팅 ID는 비밀값이라 .secrets/worker.env에만 두고,
Worker가 시작할 때 토큰이 있는지(available)만 적는다. 실제 전송은 Worker의 EventNotifier가 한다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from trading_lab.application.errors import Conflict, Invalid
from trading_lab.domain.events import EventKind
from trading_lab.persistence.bots import add_event
from trading_lab.persistence.models import NotifySettingsRow

Scope = Literal["live", "all"]
SCOPES = ("live", "all")
# "실제 주문만": 승인 요청·체결·실제 주문 문제·비상 중지, 그리고 봇이 멈춘 문제
LIVE_KINDS = {
    EventKind.LIVE_ORDER,
    EventKind.LIVE_CONTROL,
    EventKind.LIVE_RECONCILE,
    EventKind.LIVE_FUNDS,
    EventKind.RUN_ERROR,
    EventKind.AI_BUDGET_NEAR,  # 돈이 드는 일이라 실제로 따라 하지 않는 AI 봇도 보낸다
    EventKind.NOTIFY_TEST,
}
# 실제로 따라 하는 봇이면 "실제 주문만"에서도 보낸다: 그날 판단이 없으면 실제 주문도 나가지 않는다
FOLLOW_KINDS = {EventKind.AI_JUDGMENT}


@dataclass(frozen=True)
class NotifySettings:
    available: bool  # Worker에 텔레그램 토큰이 있음
    enabled: bool
    scope: str


def _row(session: Session, now: datetime, *, default_enabled: bool = False) -> NotifySettingsRow:
    row = session.get(NotifySettingsRow, 1, with_for_update=True)
    if row is None:
        row = NotifySettingsRow(
            id=1, enabled=default_enabled, scope="live", available=False, updated_at=now
        )
        session.add(row)
        session.flush()
    return row


def current(session: Session) -> NotifySettings:
    row = session.get(NotifySettingsRow, 1)
    if row is None:
        return NotifySettings(available=False, enabled=False, scope="live")
    return NotifySettings(row.available, row.enabled, row.scope)


def announce(session: Session, available: bool, default_enabled: bool, now: datetime) -> None:
    """Worker 시작 때: 토큰이 있는지 적는다. 처음이면 TELEGRAM_ENABLED를 시작 값으로 쓴다."""
    row = _row(session, now, default_enabled=default_enabled)
    row.available, row.updated_at = available, now
    session.commit()


def update(session: Session, enabled: bool, scope: str, now: datetime) -> NotifySettings:
    if scope not in SCOPES:
        raise Invalid("받을 알림은 live 또는 all 중에서 골라 주세요")
    row = _row(session, now)
    if enabled and not row.available:
        raise Conflict("텔레그램 봇 정보가 없어 켤 수 없어요")
    row.enabled, row.scope, row.updated_at = enabled, scope, now
    session.commit()
    return current(session)


def send_test(session: Session, now: datetime) -> None:
    """Worker가 다음 주기에 테스트 메시지를 보낸다 (알림을 꺼 두었어도 보낸다)."""
    if not _row(session, now).available:
        raise Conflict("텔레그램 봇 정보가 없어 보낼 수 없어요")
    add_event(session, now, "INFO", EventKind.NOTIFY_TEST, "알림 테스트")
    session.commit()


def wants(settings: NotifySettings, kind: str, *, follows: bool = False) -> bool:
    """이 종류의 소식을 텔레그램으로 보낼지. follows: 실제로 따라 하는 봇의 소식."""
    if kind == EventKind.NOTIFY_TEST:
        return settings.available
    if not (settings.available and settings.enabled):
        return False
    return settings.scope == "all" or kind in LIVE_KINDS or (follows and kind in FOLLOW_KINDS)
