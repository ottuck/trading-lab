"""텔레그램 알림 설정 API: application.notify_settings를 부르기만 한다. 전송은 Worker가 한다."""

from datetime import UTC, datetime

from fastapi import APIRouter, status

from quant_lab.api.deps import SessionDep
from quant_lab.api.schemas import NotifyUpdate, NotifyView
from quant_lab.application import notify_settings

router = APIRouter()


@router.get("/notify")
def notify(session: SessionDep) -> NotifyView:
    return NotifyView.model_validate(notify_settings.current(session), from_attributes=True)


@router.put("/notify")
def update_notify(session: SessionDep, body: NotifyUpdate) -> NotifyView:
    settings = notify_settings.update(session, body.enabled, body.scope, datetime.now(UTC))
    return NotifyView.model_validate(settings, from_attributes=True)


@router.post("/notify/test", status_code=status.HTTP_202_ACCEPTED)
def notify_test(session: SessionDep) -> None:
    notify_settings.send_test(session, datetime.now(UTC))
