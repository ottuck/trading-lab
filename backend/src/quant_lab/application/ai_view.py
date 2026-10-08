"""AI 봇 화면 (마일스톤 4 A3): 오늘의 판단·출처·판단 기록·이번 달 비용, 그리고 세 봇 비교.

비교는 AI 봇이 처음 판단한 날부터 같은 날·같은 돈으로 계산한다. AI 봇은 기록된 판단으로 다시
돌린 값이라 모의 기록과 같고(원칙 3·9), 나 카피 봇 규칙과 매달 그냥 사기는 평행세계와 같은
방식으로 그때그때 계산한다. 점수·판정은 붙이지 않는다 (project.md 1절).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.application.ai_judge import month_of
from quant_lab.application.backtesting import load_series
from quant_lab.application.bots import require_bot
from quant_lab.application.errors import Invalid
from quant_lab.application.parallel import copy_world, dca_world, world
from quant_lab.application.research import COPY_STRATEGY, BotParallel
from quant_lab.domain.advisor import JudgmentStatus
from quant_lab.domain.backtest import run_backtest
from quant_lab.domain.strategy import STRATEGIES, AiJudge, is_ai
from quant_lab.persistence.ai_judgments import spent
from quant_lab.persistence.bots import active_weights, bot_costs, bot_limits, bot_weights
from quant_lab.persistence.models import AiJudgmentRow, BotRow, DecisionRow

HISTORY = 60  # 판단 기록에 보여줄 날 수


@dataclass(frozen=True)
class AiDay:
    session_date: date
    status: str
    summary: str | None
    weights: dict[str, int] | None  # 목표 비중 (현금은 CASH)
    weights_before: dict[str, str]  # 판단할 때의 비중 % (현금은 CASH)
    reasons: dict[str, str] | None
    sources: list[dict[str, Any]]  # [{url, title, used}] 근거로 쓴 기사(used)가 앞
    queries: list[str]
    model: str | None
    cost: Decimal | None
    error: str | None
    created_at: datetime


@dataclass(frozen=True)
class AiOverview:
    latest: AiDay | None
    history: list[AiDay]  # 최근 판단부터
    spent: Decimal  # 이번 달(UTC) 이 봇 전략의 AI 비용 (시장분석·캔들분석은 따로 센다)
    budget: Decimal


def _before(request: dict[str, Any] | None) -> dict[str, str]:
    if not request:
        return {}
    out = {s["symbol"]: s["weight_now"] for s in request.get("symbols", [])}
    return out | {"CASH": request.get("cash_weight", "0")}


def _day(row: AiJudgmentRow) -> AiDay:
    return AiDay(
        session_date=row.session_date,
        status=row.status,
        summary=row.summary,
        weights=row.weights,
        weights_before=_before(row.request),
        reasons=row.reasons,
        sources=row.sources or [],
        queries=row.queries or [],
        model=row.model,
        cost=row.cost,
        error=row.error,
        created_at=row.created_at,
    )


def _ai_bot(session: Session, bot_id: int) -> BotRow:
    bot = require_bot(session, bot_id)
    if not is_ai(bot.strategy):
        raise Invalid("AI 봇만 볼 수 있어요")
    return bot


def ai_overview(
    session: Session, bot_id: int, budgets: dict[str, Decimal], now: datetime
) -> AiOverview:
    """budgets는 전략마다의 한 달 비용 상한."""
    bot = _ai_bot(session, bot_id)
    rows = list(
        session.scalars(
            select(AiJudgmentRow)
            .where(AiJudgmentRow.bot_id == bot_id)
            .order_by(AiJudgmentRow.session_date.desc())
            .limit(HISTORY)
        )
    )
    days = [_day(r) for r in rows]
    start, end = month_of(now)
    used = spent(session, start, end, bot.strategy)
    return AiOverview(days[0] if days else None, days, used, budgets[bot.strategy])


def _copy_bot(session: Session) -> BotRow | None:
    """비교에 쓸 나 카피 봇 (실행 중인 것부터, 여럿이면 먼저 만든 것)."""
    return session.scalars(
        select(BotRow)
        .where(BotRow.strategy == COPY_STRATEGY)
        .order_by((BotRow.state != "RUNNING"), BotRow.id)
        .limit(1)
    ).first()


def ai_compare(session: Session, bot_id: int) -> BotParallel:
    """AI 봇 vs 나 카피 봇 규칙 vs 매달 그냥 사기 (AI 봇이 처음 판단한 날부터, 같은 돈)."""
    bot = _ai_bot(session, bot_id)
    first = session.scalar(
        select(func.min(DecisionRow.session_date)).where(DecisionRow.bot_id == bot_id)
    )
    if first is None:
        return BotParallel(None, note="아직 첫 판단 전이에요.")
    rows = session.scalars(select(AiJudgmentRow).where(AiJudgmentRow.bot_id == bot_id))
    judgments = {
        r.session_date: (r.weights if r.status == JudgmentStatus.OK else None) for r in rows
    }
    strategy = cast(AiJudge, STRATEGIES[bot.strategy](**bot.params))
    weights = bot_weights(bot)
    costs = bot_costs(bot)
    try:
        series = load_series(session, weights, strategy.warmup, first, None)
        result = run_backtest(
            series,
            strategy,
            bot.initial_cash,
            costs,
            bot_limits(bot),
            weights=weights,
            judgments=judgments,
        )
    except ValueError:
        return BotParallel(first, note="시작한 지 얼마 안 돼서 아직 비교할 날이 없어요.")
    worlds = [world("me", "AI 봇", None, result, daily=True)]
    me = _copy_bot(session)
    if me is None:
        # 나 카피 봇이 없으면 AI 봇 종목을 똑같이 나눠 매달 그냥 산 것과만 비교한다
        return BotParallel(first, [*worlds, dca_world(result, "매달 그냥 사기", daily=True)])
    params = {**me.params, "deposit": strategy.deposit, "day": strategy.day}
    copy, dca = copy_world(
        session,
        active_weights(me),
        params,
        start=first,
        initial_cash=bot.initial_cash,
        costs=bot_costs(me),
    )
    return BotParallel(first, [*worlds, copy, dca])
