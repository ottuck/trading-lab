import mimetypes
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.base import RequestResponseEndpoint

from quant_lab import __version__
from quant_lab.api.access import AccessGuard
from quant_lab.api.routes import router
from quant_lab.api.schemas import HealthResponse, WorkerStatus
from quant_lab.application.errors import AppError, Conflict, Invalid, NotFound
from quant_lab.config import get_settings
from quant_lab.persistence.db import get_session
from quant_lab.persistence.heartbeat import evaluating, latest_heartbeat

# 접근 제어는 Tailscale과 Cloudflare Access가 맡는다 (공개 포트 없음, project.md 6절).
# 공개 인터넷에 직접 노출하지 않는다.
app = FastAPI(title="Quant Lab", version=__version__)
app.include_router(router)

# 서비스 오류 → HTTP 상태. 메시지는 화면에 그대로 보여줘도 되는 문장이다 (application/errors.py).
ERROR_STATUS = {NotFound: 404, Invalid: 400, Conflict: 409}


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError) -> JSONResponse:
    code = next((c for t, c in ERROR_STATUS.items() if isinstance(exc, t)), 400)
    return JSONResponse({"detail": str(exc)}, status_code=code)


_settings = get_settings()
access = (
    AccessGuard(_settings.cf_access_team, _settings.cf_access_aud)
    if _settings.cf_access_team and _settings.cf_access_aud
    else None
)


# 데모에서 받는 바꾸기 요청: 계산만 하는 것 (시험해 보기는 저장하되 오래된 것은 지운다)
DEMO_ALLOWED = {("POST", "/api/backtests"), ("POST", "/api/parallel")}


@app.middleware("http")
async def demo_read_only(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """데모(D2)는 보기·계산만. 봇 만들기·명령·설정 바꾸기는 막는다."""
    if (
        _settings.demo_mode
        and request.method not in ("GET", "HEAD", "OPTIONS")
        and (request.method, request.url.path) not in DEMO_ALLOWED
    ):
        return JSONResponse({"detail": "데모에서는 바꿀 수 없어요"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def cloudflare_access(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """도메인(Cloudflare)으로 온 요청은 Access 로그인 토큰이 있어야 한다 (Tailscale은 그대로)."""
    if access is not None and "cf-ray" in request.headers:
        token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get(
            "CF_Authorization"
        )
        if not await run_in_threadpool(access.allows, token):
            return JSONResponse({"detail": "로그인이 필요해요"}, status_code=403)
    return await call_next(request)


@app.get("/api/health")
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        beat = latest_heartbeat(session)
        busy = evaluating(session, datetime.now(UTC))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(version=__version__, db="down", worker=None, demo=_settings.demo_mode)

    if beat is None:
        worker = WorkerStatus(alive=False, worker_id=None, last_seen_at=None)
    else:
        # heartbeat 주기의 3배 동안 소식이 없으면 Worker 정지로 본다.
        limit = timedelta(seconds=get_settings().worker_heartbeat_interval_s * 3)
        alive = datetime.now(UTC) - beat.last_seen_at <= limit
        worker = WorkerStatus(alive=alive, worker_id=beat.worker_id, last_seen_at=beat.last_seen_at)
    return HealthResponse(
        version=__version__, db="ok", worker=worker, demo=_settings.demo_mode, evaluating=busy
    )


# 빌드된 화면이 있으면 같은 서버에서 제공한다 (운영 이미지). API 경로 뒤에 둔다.
# PWA 매니페스트는 Python 기본 MIME 표에 없다.
mimetypes.add_type("application/manifest+json", ".webmanifest")
_dist = get_settings().frontend_dist
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")


@app.middleware("http")
async def fresh_index(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """배포하면 바로 새 화면이 보이게 한다. index.html은 매번 확인하고(no-cache),
    이름에 해시가 붙은 assets는 내용이 바뀌면 이름도 바뀌므로 오래 둔다."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif not path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
