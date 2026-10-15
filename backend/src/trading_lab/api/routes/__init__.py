"""API 라우터. 각 파일은 요청 해석 → application 서비스 호출 → 응답 형식 변환만 한다.

업무 규칙과 계산은 application/에 있다 (bots: 관리, bot_status: 상태 계산, queries: 조회,
research: 계산해 보기). 서비스 오류(NotFound·Invalid·Conflict)는 api/main.py가 HTTP 상태로 바꾼다.
"""

from fastapi import APIRouter

from trading_lab.api.routes import bots, live, market, notify, research

router = APIRouter(prefix="/api")
router.include_router(bots.router)
router.include_router(live.router)
router.include_router(market.router)
router.include_router(notify.router)
router.include_router(research.router)
