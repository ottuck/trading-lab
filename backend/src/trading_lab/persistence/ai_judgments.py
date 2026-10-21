"""AI 판단 기록 (ai_judgments). 재현의 원본이라 고치거나 지우지 않는다."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trading_lab.domain.advisor import Judgment
from trading_lab.persistence.models import AiJudgmentRow


def save_judgment(
    session: Session, bot_id: int | None, judgment: Judgment, now: datetime, strategy: str
) -> AiJudgmentRow:
    advice, usage = judgment.advice, judgment.usage
    row = AiJudgmentRow(
        bot_id=bot_id,
        strategy=strategy,
        session_date=judgment.session_date,
        status=judgment.status.value,
        source=judgment.source,
        model=usage.model if usage else None,
        prompt_version=judgment.prompt_version,
        request=judgment.request.as_dict() if judgment.request else None,
        weights=dict(advice.weights) if advice else None,
        reasons=dict(advice.reasons) if advice else None,
        summary=advice.summary if advice else None,
        sources=[{"url": s.url, "title": s.title, "used": s.used} for s in advice.sources]
        if advice
        else None,
        queries=list(advice.queries) if advice else None,
        decision=(advice.decision or None) if advice else None,
        basis=(list(advice.basis) or None) if advice else None,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        web_searches=usage.web_searches if usage else None,
        cost=usage.cost if usage else None,
        error=judgment.error,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row


def spent(session: Session, start: datetime, end: datetime, strategy: str) -> Decimal:
    """[start, end)에 부른 그 전략 판단의 비용 합 (지운 봇·시험 판단 포함). 한 달 상한에 쓴다."""
    total = session.scalar(
        select(func.sum(AiJudgmentRow.cost)).where(
            AiJudgmentRow.strategy == strategy,
            AiJudgmentRow.created_at >= start,
            AiJudgmentRow.created_at < end,
        )
    )
    return Decimal(total or 0)


def judgment_for(session: Session, bot_id: int, day: date) -> AiJudgmentRow | None:
    return session.scalars(
        select(AiJudgmentRow).where(
            AiJudgmentRow.bot_id == bot_id, AiJudgmentRow.session_date == day
        )
    ).first()


def recent_ok(session: Session, bot_id: int, before: date, n: int) -> list[AiJudgmentRow]:
    """before 전 마지막으로 받은 판단 n개, 오래된 것부터 (마지막이 "지난 판단", 모두 피드백)."""
    rows = session.scalars(
        select(AiJudgmentRow)
        .where(
            AiJudgmentRow.bot_id == bot_id,
            AiJudgmentRow.session_date < before,
            AiJudgmentRow.status == "OK",
        )
        .order_by(AiJudgmentRow.session_date.desc())
        .limit(n)
    )
    return list(reversed(list(rows)))


def has_judgment(session: Session, bot_id: int, day: date) -> bool:
    return (
        session.scalar(
            select(AiJudgmentRow.id).where(
                AiJudgmentRow.bot_id == bot_id, AiJudgmentRow.session_date == day
            )
        )
        is not None
    )


def over_budget_since(session: Session, bot_id: int, since: datetime) -> bool:
    """since 이후 이 봇이 비용 상한으로 판단하지 못한 적이 있는가."""
    return (
        session.scalar(
            select(AiJudgmentRow.id).where(
                AiJudgmentRow.bot_id == bot_id,
                AiJudgmentRow.status == "OVER_BUDGET",
                AiJudgmentRow.created_at >= since,
            )
        )
        is not None
    )


def latest_judgments(session: Session, bot_id: int, n: int) -> list[AiJudgmentRow]:
    """가장 최근 판단 n개, 최근 것부터."""
    return list(
        session.scalars(
            select(AiJudgmentRow)
            .where(AiJudgmentRow.bot_id == bot_id)
            .order_by(AiJudgmentRow.session_date.desc())
            .limit(n)
        )
    )


def all_judgments(session: Session, bot_id: int) -> list[AiJudgmentRow]:
    return list(session.scalars(select(AiJudgmentRow).where(AiJudgmentRow.bot_id == bot_id)))
