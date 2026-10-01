from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from quant_lab.persistence.models import WorkerHeartbeat


def record_heartbeat(
    session: Session, worker_id: str, version: str, started_at: datetime, now: datetime
) -> None:
    stmt = insert(WorkerHeartbeat).values(
        worker_id=worker_id, version=version, started_at=started_at, last_seen_at=now
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[WorkerHeartbeat.worker_id],
        set_={"version": version, "started_at": started_at, "last_seen_at": now},
    )
    session.execute(stmt)
    session.commit()


def latest_heartbeat(session: Session) -> WorkerHeartbeat | None:
    stmt = select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
    return session.scalars(stmt).first()
