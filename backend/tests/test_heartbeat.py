from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.persistence.heartbeat import latest_heartbeat, record_heartbeat
from quant_lab.persistence.models import WorkerHeartbeat


def test_heartbeat_upserts_one_row_per_worker(session: Session) -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    record_heartbeat(session, "w1", "0.1.0", started_at=start, now=start)
    record_heartbeat(session, "w1", "0.1.0", started_at=start, now=start + timedelta(seconds=15))

    assert session.scalar(select(func.count()).select_from(WorkerHeartbeat)) == 1
    beat = latest_heartbeat(session)
    assert beat is not None
    assert beat.last_seen_at == start + timedelta(seconds=15)


def test_latest_heartbeat_picks_most_recent_worker(session: Session) -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    record_heartbeat(session, "old", "0.1.0", started_at=start, now=start)
    record_heartbeat(session, "new", "0.1.0", started_at=start, now=start + timedelta(minutes=1))

    beat = latest_heartbeat(session)
    assert beat is not None
    assert beat.worker_id == "new"
