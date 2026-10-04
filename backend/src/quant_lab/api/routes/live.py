"""실제로 따라 사기 API (실거래 R2): application.live_admin을 부르고 응답 형식으로 옮겨 담기만 한다.

DB만 바꾼다. 실제 주문은 Worker가 낸다 (원칙 6).
"""

from datetime import UTC, datetime

from fastapi import APIRouter

from quant_lab.api.deps import SessionDep
from quant_lab.api.schemas import BotView, LiveHalt, LiveRatioUpdate, LiveView
from quant_lab.application import bot_status, live_admin

router = APIRouter()


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/live")
def live(session: SessionDep) -> LiveView:
    return LiveView.model_validate(live_admin.overview(session), from_attributes=True)


@router.put("/bots/{bot_id}/live")
def set_live_ratio(session: SessionDep, bot_id: int, body: LiveRatioUpdate) -> BotView:
    bot = live_admin.set_bot_ratio(session, bot_id, body.ratio, _now())
    return BotView.model_validate(bot_status.bot_status(session, bot), from_attributes=True)


@router.post("/live-orders/{order_id}/approve")
def approve(session: SessionDep, order_id: int) -> LiveView:
    live_admin.approve(session, order_id, _now())
    return live(session)


@router.post("/live-orders/{order_id}/decline")
def decline(session: SessionDep, order_id: int) -> LiveView:
    live_admin.decline(session, order_id, _now())
    return live(session)


@router.post("/live/halt")
def halt(session: SessionDep, body: LiveHalt) -> LiveView:
    live_admin.set_halted(session, body.halted, _now())
    return live(session)
