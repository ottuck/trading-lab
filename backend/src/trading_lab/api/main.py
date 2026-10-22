import mimetypes
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.base import RequestResponseEndpoint

from trading_lab import __version__
from trading_lab.adapters.error_reporting import init_error_reporting
from trading_lab.api.access import AccessGuard
from trading_lab.api.routes import router
from trading_lab.api.schemas import HealthResponse, WorkerStatus
from trading_lab.application.errors import AppError, Conflict, Invalid, NotFound
from trading_lab.config import get_settings
from trading_lab.persistence.db import get_session, ping
from trading_lab.persistence.heartbeat import evaluating, latest_heartbeat

# 접근 제어는 Tailscale과 Cloudflare Access가 맡는다 (공개 포트 없음, project.md 6절).
# 공개 인터넷에 직접 노출하지 않는다.
app = FastAPI(title="Trading Lab", version=__version__)
app.include_router(router)

# 서비스 오류 → HTTP 상태. 메시지는 화면에 그대로 보여줘도 되는 문장이다 (application/errors.py).
ERROR_STATUS = {NotFound: 404, Invalid: 400, Conflict: 409}


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError) -> JSONResponse:
    code = next((c for t, c in ERROR_STATUS.items() if isinstance(exc, t)), 400)
    return JSONResponse({"detail": str(exc)}, status_code=code)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """예상 못 한 오류도 화면이 읽는 {"detail"} 모양으로 돌려준다 (자세한 내용은 서버 로그)."""
    return JSONResponse(
        {"detail": "서버에 문제가 생겼어요. 잠시 뒤에 다시 해 주세요."}, status_code=500
    )


_settings = get_settings()
# 예상 못 한 500은 uvicorn이 ERROR로 남기고, 그 로그가 Sentry로 간다 (adapters/error_reporting.py).
init_error_reporting(_settings.sentry_dsn, _settings.sentry_release)
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
async def same_origin_writes(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """다른 사이트가 사용자의 브라우저로 보낸 바꾸기 요청을 거절한다 (주문 승인·비상 중지 등).

    브라우저는 Sec-Fetch-Site를 꼭 붙인다. 이 화면에서 보낸 요청은 same-origin이고, 헤더가
    없으면 브라우저가 아닌 도구(curl·서버끼리)라 통과시킨다. 접근 제어는 그대로
    Tailscale·Cloudflare Access다.
    """
    own_site = request.headers.get("sec-fetch-site") in (None, "same-origin", "none")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not own_site:
        return JSONResponse({"detail": "다른 사이트에서 보낸 요청은 받지 않아요"}, status_code=403)
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
        ping(session)
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
