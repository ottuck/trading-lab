"""매매일지 보관 (journal_archives): 봇을 지우거나 처음부터 다시 시작하기 전의 일지.

지우지 않는다.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trading_lab.persistence.models import JournalArchiveRow, SimOrderRow


def save_archive(
    session: Session,
    bot_id: int,
    bot_name: str,
    strategy: str,
    why: str,
    days: list[dict[str, Any]],
    now: datetime,
) -> None:
    """days는 오래된 날부터. 비어 있으면(판단 전) 남기지 않는다."""
    if not days:
        return
    session.add(
        JournalArchiveRow(
            bot_id=bot_id,
            bot_name=bot_name,
            strategy=strategy,
            why=why,
            first_date=date.fromisoformat(days[0]["date"]),
            last_date=date.fromisoformat(days[-1]["date"]),
            days=days,
            created_at=now,
        )
    )
    session.flush()


def archives_of(session: Session, bot_id: int | None) -> list[JournalArchiveRow]:
    """그 봇이 처음부터 다시 시작하며 남긴 일지. None이면 지운 봇의 일지. 최근 것부터."""
    where = (
        JournalArchiveRow.bot_id.is_(None) if bot_id is None else JournalArchiveRow.bot_id == bot_id
    )
    return list(
        session.scalars(
            select(JournalArchiveRow).where(where).order_by(JournalArchiveRow.created_at.desc())
        )
    )


def get_archive(session: Session, archive_id: int) -> JournalArchiveRow | None:
    return session.get(JournalArchiveRow, archive_id)


def sim_orders_of(session: Session, bot_id: int) -> list[SimOrderRow]:
    """봇의 모든 모의 주문 (체결 전·안 됨 포함), 판단일 순서."""
    return list(
        session.scalars(
            select(SimOrderRow)
            .where(SimOrderRow.bot_id == bot_id)
            .order_by(SimOrderRow.signal_date, SimOrderRow.id)
        )
    )
