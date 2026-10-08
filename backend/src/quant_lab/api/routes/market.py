"""시세·종목·전략·기록 조회 API. DB만 읽는다 (증권사를 부르지 않음, project.md 3절 원칙 6)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from quant_lab.api.deps import SessionDep
from quant_lab.api.schemas import (
    ActivityItem,
    BarView,
    BrokerAccountView,
    ChoiceOption,
    ChoiceView,
    EventView,
    FxView,
    InstrumentView,
    PresetView,
    StrategyInfo,
)
from quant_lab.application import queries
from quant_lab.application.messages import CATALOG
from quant_lab.config import get_settings
from quant_lab.domain.strategy import STRATEGIES, is_ai
from quant_lab.persistence.models import BrokerAccountRow

router = APIRouter()


@router.get("/bars/{symbol}")
def bars(
    session: SessionDep,
    symbol: str,
    start: date | None = None,
    limit: Annotated[int, Query(le=10_000)] = 600,
) -> list[BarView]:
    return [
        BarView.model_validate(b, from_attributes=True)
        for b in queries.price_bars(session, symbol, start, limit)
    ]


@router.get("/instruments")
def instruments(session: SessionDep) -> list[InstrumentView]:
    watch = [s.strip().upper() for s in get_settings().watchlist_symbols.split(",") if s.strip()]
    return [
        InstrumentView.model_validate(i, from_attributes=True)
        for i in queries.instruments(session, watch)
    ]


@router.get("/fx")
def fx(session: SessionDep) -> FxView | None:
    """오늘 원/달러 (화면에서 원화로 바꿔 보기만). 아직 받지 못했으면 null."""
    info = queries.usd_krw(session)
    return FxView.model_validate(info, from_attributes=True) if info else None


@router.get("/broker-account")
def broker_account(session: SessionDep) -> BrokerAccountView | None:
    """실제 증권사 계좌 (Worker가 한 시간마다 읽은 값). 읽기를 켜지 않았으면 null."""
    row = session.get(BrokerAccountRow, 1)
    return BrokerAccountView.model_validate(row, from_attributes=True) if row else None


@router.get("/strategies")
def strategies() -> list[StrategyInfo]:
    """전략 카탈로그 (별명·설명·프리셋·선택지)."""
    out = []
    for name, factory in STRATEGIES.items():
        info = CATALOG[name]
        out.append(
            StrategyInfo(
                name=name,
                nickname=info.nickname,
                summary=info.summary,
                risk=info.risk,
                trades=info.trades,
                presets=[
                    PresetView(key=p.key, label=p.label, params=p.params) for p in info.presets
                ],
                default_params=factory().params,
                ai=is_ai(name),
                preset_label=info.preset_label,
                choices=[
                    ChoiceView(
                        key=c.key,
                        label=c.label,
                        options=[ChoiceOption(value=v, label=t) for v, t in c.options],
                        hint=c.hint,
                        requires=c.requires,
                    )
                    for c in info.choices
                ],
            )
        )
    return out


@router.get("/activity")
def activity(
    session: SessionDep,
    bot_id: int | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(le=100)] = 20,
) -> list[ActivityItem]:
    """최근 활동을 쉬운 말로 (텔레그램과 같은 문장)."""
    return [
        ActivityItem.model_validate(a, from_attributes=True)
        for a in queries.activity(session, bot_id, kind, limit)
    ]


@router.get("/events")
def events(
    session: SessionDep,
    bot_id: int | None = None,
    level: str | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(le=500)] = 100,
) -> list[EventView]:
    return [
        EventView.model_validate(r, from_attributes=True)
        for r in queries.events(session, bot_id, level, kind, limit)
    ]
