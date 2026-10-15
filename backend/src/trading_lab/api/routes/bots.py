"""봇 API: 요청을 해석해 application.bots·bot_status를 부르고 응답 형식으로 옮겨 담기만 한다."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from trading_lab.adapters.market_calendar import get_calendar
from trading_lab.api.deps import SessionDep
from trading_lab.api.routes.research import parallel_view
from trading_lab.api.schemas import (
    AiView,
    BotConfig,
    BotCreate,
    BotRename,
    BotView,
    CommandAccepted,
    CommandRequest,
    DecisionView,
    EquityPoint,
    OrderView,
    ParallelView,
    PlanView,
    SymbolsUpdate,
    SymbolWeight,
)
from trading_lab.application import ai_view, bot_status, bots, queries, research
from trading_lab.application.bot_status import BotStatus
from trading_lab.application.bots import BotSettings
from trading_lab.config import get_settings
from trading_lab.domain.strategy import AI_STRATEGY, CANDLE_STRATEGY

router = APIRouter()


def _now() -> datetime:
    return datetime.now(UTC)


def _view(status_: BotStatus) -> BotView:
    return BotView.model_validate(status_, from_attributes=True)


def _status(session: SessionDep, bot_id: int) -> BotView:
    return _view(bot_status.bot_status(session, bots.require_bot(session, bot_id)))


def _settings(body: BotConfig) -> BotSettings:
    return BotSettings(
        strategy=body.strategy,
        params=body.params,
        commission_rate=body.commission_rate,
        slippage_bps=body.slippage_bps,
        max_position_value=body.max_position_value,
        max_order_value=body.max_order_value,
    )


def _pairs(symbols: list[SymbolWeight] | None) -> list[tuple[str, int]] | None:
    return [(s.symbol, s.weight) for s in symbols] if symbols else None


@router.get("/bots")
def list_bots(session: SessionDep) -> list[BotView]:
    return [_view(s) for s in bot_status.all_bot_statuses(session)]


@router.post("/bots", status_code=status.HTTP_201_CREATED)
def create(session: SessionDep, body: BotCreate) -> BotView:
    bot = bots.create(
        session,
        name=body.name,
        symbol=body.symbol,
        symbols=_pairs(body.symbols),
        settings=_settings(body),
        initial_cash=body.initial_cash,
        request=body.model_dump(mode="json"),
        now=_now(),
    )
    return _status(session, bot.id)


@router.get("/bots/{bot_id}")
def get(session: SessionDep, bot_id: int) -> BotView:
    return _status(session, bot_id)


@router.put("/bots/{bot_id}/config")
def update_config(session: SessionDep, bot_id: int, body: BotConfig) -> BotView:
    """실행 중에도 바꿀 수 있다. 다음 판단부터 적용된다."""
    bots.update_settings(session, bot_id, _settings(body), _now())
    return _status(session, bot_id)


@router.put("/bots/{bot_id}/symbols")
def update_symbols(session: SessionDep, bot_id: int, body: SymbolsUpdate) -> BotView:
    bots.update_symbols(session, bot_id, _pairs(body.symbols) or [], _now())
    return _status(session, bot_id)


@router.patch("/bots/{bot_id}")
def rename(session: SessionDep, bot_id: int, body: BotRename) -> BotView:
    bots.rename(session, bot_id, body.name, _now())
    return _status(session, bot_id)


@router.post("/bots/{bot_id}/reset")
def reset(session: SessionDep, bot_id: int) -> BotView:
    bots.reset(session, bot_id, _now())
    return _status(session, bot_id)


@router.delete("/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(session: SessionDep, bot_id: int) -> None:
    bots.remove(session, bot_id, _now())


@router.post("/bots/{bot_id}/commands", status_code=status.HTTP_202_ACCEPTED)
def command(session: SessionDep, bot_id: int, body: CommandRequest) -> CommandAccepted:
    """명령은 DB에 기록만 한다. Worker가 다음 주기(15초 이내)에 처리한다."""
    cmd = bots.send_command(session, bot_id, body.kind, _now())
    return CommandAccepted(id=cmd.id, bot_id=bot_id, kind=body.kind, created_at=cmd.created_at)


@router.get("/bots/{bot_id}/decisions")
def decisions(
    session: SessionDep, bot_id: int, limit: Annotated[int, Query(le=500)] = 50
) -> list[DecisionView]:
    return [
        DecisionView.model_validate(bot_status.decision_status(r), from_attributes=True)
        for r in queries.decisions(session, bot_id, limit)
    ]


@router.get("/bots/{bot_id}/orders")
def orders(
    session: SessionDep, bot_id: int, limit: Annotated[int, Query(le=500)] = 50
) -> list[OrderView]:
    return [
        OrderView.model_validate(r, from_attributes=True)
        for r in queries.orders(session, bot_id, limit)
    ]


@router.get("/bots/{bot_id}/equity")
def equity(session: SessionDep, bot_id: int) -> list[EquityPoint]:
    """홈 차트용 하루 단위 모의 자산과 '그냥 들고 있었다면'."""
    curve = bot_status.equity_curve(session, bots.require_bot(session, bot_id))
    return [EquityPoint.model_validate(p, from_attributes=True) for p in curve]


@router.get("/bots/{bot_id}/plan")
def plan(session: SessionDep, bot_id: int) -> PlanView | None:
    """따라 하기: 다음 입금일에 할 일 (나 카피 봇만)."""
    result = research.bot_plan(session, bot_id, get_calendar())
    return PlanView.model_validate(result, from_attributes=True) if result else None


@router.get("/bots/{bot_id}/ai")
def ai(session: SessionDep, bot_id: int) -> AiView:
    """AI 봇: 오늘의 판단·출처·판단 기록·이번 달 비용."""
    settings = get_settings()
    budgets = {
        AI_STRATEGY: settings.ai_monthly_budget,
        CANDLE_STRATEGY: settings.ai_candle_monthly_budget,
    }
    result = ai_view.ai_overview(session, bot_id, budgets, _now())
    return AiView.model_validate(result, from_attributes=True)


@router.get("/bots/{bot_id}/ai/compare")
def ai_compare(session: SessionDep, bot_id: int) -> ParallelView:
    """AI 봇 vs 나 카피 봇 규칙 vs 매달 그냥 사기 (AI 봇이 처음 판단한 날부터, 같은 돈)."""
    result = ai_view.ai_compare(session, bot_id)
    if not result.worlds:
        return ParallelView(start=result.start, end=None, worlds=[], note=result.note)
    return parallel_view(result.worlds)


@router.get("/bots/{bot_id}/parallel")
def parallel(session: SessionDep, bot_id: int) -> ParallelView:
    """운영 중인 나 카피 봇의 평행세계."""
    result = research.bot_parallel(session, bot_id)
    if not result.worlds:
        return ParallelView(start=result.start, end=None, worlds=[], note=result.note)
    return parallel_view(result.worlds)
