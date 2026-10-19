"""이벤트(알림·최근 활동) 조회."""

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trading_lab.domain.events import EventKind
from trading_lab.persistence.models import EventRow, RunRow


def latest_event_id(session: Session) -> int:
    return session.scalar(select(func.max(EventRow.id))) or 0


def events_after(session: Session, after_id: int, limit: int) -> list[EventRow]:
    """after_id보다 새 이벤트, 오래된 것부터."""
    return list(
        session.scalars(
            select(EventRow).where(EventRow.id > after_id).order_by(EventRow.id).limit(limit)
        )
    )


def week_base_data(session: Session, bot_id: int, week_start: date) -> dict[str, Any] | None:
    """주간 리포트의 기준점: 지난주 마지막 판단 이벤트의 값. 없으면 이번 주 첫 판단."""
    base = (
        select(EventRow.data)
        .join(RunRow, EventRow.run_id == RunRow.id)
        .where(EventRow.bot_id == bot_id, EventRow.kind == EventKind.DECISION)
    )
    return session.scalar(
        base.where(RunRow.session_date < week_start).order_by(RunRow.session_date.desc())
    ) or session.scalar(base.where(RunRow.session_date >= week_start).order_by(RunRow.session_date))


def latest_events(
    session: Session, limit: int, *, bot_id: int | None = None, kind: str | None = None
) -> list[EventRow]:
    """최근 이벤트 limit개 (id 큰 순서)."""
    stmt = select(EventRow).order_by(EventRow.id.desc()).limit(limit)
    if bot_id is not None:
        stmt = stmt.where(EventRow.bot_id == bot_id)
    if kind:
        stmt = stmt.where(EventRow.kind == kind)
    return list(session.scalars(stmt))


def event_log(
    session: Session,
    limit: int,
    *,
    bot_id: int | None = None,
    level: str | None = None,
    kind: str | None = None,
) -> list[EventRow]:
    """시각 순서로 최근 이벤트 limit개 (확인·디버깅용)."""
    stmt = select(EventRow).order_by(EventRow.at.desc(), EventRow.id.desc()).limit(limit)
    if bot_id is not None:
        stmt = stmt.where(EventRow.bot_id == bot_id)
    if level:
        stmt = stmt.where(EventRow.level == level.upper())
    if kind:
        stmt = stmt.where(EventRow.kind == kind)
    return list(session.scalars(stmt))
