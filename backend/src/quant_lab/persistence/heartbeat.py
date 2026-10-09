from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from quant_lab.persistence.models import RunRow, WorkerHeartbeat


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


def evaluating(session: Session, now: datetime, within: timedelta = timedelta(minutes=30)) -> bool:
    """봇이 지금 판단 중인지 (AI 판단 포함). 배포가 Worker를 다시 띄우기 전에 묻는다.

    판단은 시작할 때 RUNNING으로 먼저 남기고 끝나면 바꾼다. Worker가 죽어 RUNNING으로 남은
    옛 기록 때문에 영원히 기다리지 않게, within 안에 시작한 것만 본다.
    """
    stmt = select(exists().where(RunRow.status == "RUNNING", RunRow.started_at > now - within))
    return bool(session.scalar(stmt))


def latest_heartbeat(session: Session) -> WorkerHeartbeat | None:
    stmt = select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
    return session.scalars(stmt).first()
