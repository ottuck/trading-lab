from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from quant_lab import __version__
from quant_lab.config import get_settings
from quant_lab.persistence.db import get_session
from quant_lab.persistence.heartbeat import latest_heartbeat

app = FastAPI(title="Quant Lab", version=__version__)


class WorkerStatus(BaseModel):
    alive: bool
    worker_id: str | None
    last_seen_at: datetime | None


class HealthResponse(BaseModel):
    version: str
    db: Literal["ok", "down"]
    worker: WorkerStatus | None


@app.get("/api/health")
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        beat = latest_heartbeat(session)
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(version=__version__, db="down", worker=None)

    if beat is None:
        worker = WorkerStatus(alive=False, worker_id=None, last_seen_at=None)
    else:
        # heartbeat 주기의 3배 동안 소식이 없으면 Worker 정지로 본다.
        limit = timedelta(seconds=get_settings().worker_heartbeat_interval_s * 3)
        alive = datetime.now(UTC) - beat.last_seen_at <= limit
        worker = WorkerStatus(alive=alive, worker_id=beat.worker_id, last_seen_at=beat.last_seen_at)
    return HealthResponse(version=__version__, db="ok", worker=worker)
