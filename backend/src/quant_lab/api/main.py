import mimetypes
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from quant_lab import __version__
from quant_lab.api.routes import router
from quant_lab.api.schemas import HealthResponse, WorkerStatus
from quant_lab.config import get_settings
from quant_lab.persistence.db import get_session
from quant_lab.persistence.heartbeat import latest_heartbeat

# 접근 제어는 Tailscale이 맡는다 (공개 포트 없음, project.md 6절).
# 공개 인터넷에 직접 노출하지 않는다.
app = FastAPI(title="Quant Lab", version=__version__)
app.include_router(router)


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


# 빌드된 화면이 있으면 같은 서버에서 제공한다 (운영 이미지). API 경로 뒤에 둔다.
# PWA 매니페스트는 Python 기본 MIME 표에 없다.
mimetypes.add_type("application/manifest+json", ".webmanifest")
_dist = get_settings().frontend_dist
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
