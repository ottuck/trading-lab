"""AI 판단 1회: 입력 요약 → AI 호출 → 규칙 검사 → 기록할 판단 (project.md 14절).

실패·형식 오류·비용 상한도 판단으로 남긴다 (그날은 사고팔지 않는다, 원칙 5).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from trading_lab.domain.advisor import (
    AdviceRequest,
    Advisor,
    AdvisorError,
    CandleAdvisor,
    Judgment,
    JudgmentStatus,
    Unmasking,
    check_advice,
)
from trading_lab.domain.events import AiJudgmentData, EventKind
from trading_lab.domain.strategy import AI_STRATEGY, CANDLE_STRATEGY
from trading_lab.persistence.ai_judgments import (
    has_judgment,
    over_budget_since,
    save_judgment,
    spent,
)
from trading_lab.persistence.bots import add_event


@dataclass(frozen=True)
class AiConfig:
    """Worker 조립 지점이 넘긴다. 공급자가 없으면(키 없음) 그 AI 봇은 판단하지 않는다.

    한 달 비용 상한은 시장분석·캔들분석 AI 봇이 따로 센다.
    """

    advisor: Advisor | None
    monthly_budget: Decimal
    candle_advisor: CandleAdvisor | None = None
    candle_budget: Decimal = Decimal(5)

    def pick(self, candles: bool) -> tuple[Advisor | None, Decimal]:
        """판단할 공급자와 그 전략의 한 달 비용 상한. 캔들 공급자는 익명 입력만 받게 감싼다."""
        if candles:
            inner = self.candle_advisor
            return (Unmasking(inner) if inner else None), self.candle_budget
        return self.advisor, self.monthly_budget


def judge(advisor: Advisor | None, request: AdviceRequest) -> Judgment:
    day = request.session_date
    if advisor is None:
        return Judgment(day, JudgmentStatus.FAILED, request, error="AI 키가 없어 판단하지 않음")
    if not request.symbols:
        return Judgment(day, JudgmentStatus.FAILED, request, error="판단할 수 있는 종목이 없음")
    try:
        result = advisor.advise(request)
    except AdvisorError as e:
        return Judgment(
            day, JudgmentStatus.FAILED, request, usage=e.usage, source=advisor.source, error=str(e)
        )
    problem = check_advice(result.advice, [s.symbol for s in request.symbols])
    return Judgment(
        day,
        JudgmentStatus.INVALID if problem else JudgmentStatus.OK,
        request,
        advice=None if problem else result.advice,
        usage=result.usage,
        prompt_version=result.prompt_version,
        source=advisor.source,
        error=problem,
    )


def month_of(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    end = datetime(now.year + now.month // 12, now.month % 12 + 1, 1, tzinfo=UTC)
    return start, end


def judge_bot(
    session: Session, bot_id: int, request: AdviceRequest, ai: AiConfig | None, now: datetime
) -> None:
    """봇의 그날 판단을 받아 기록하고 커밋한다. 받지 못했으면 알린다.

    이번 달(UTC) 그 전략의 비용이 상한 이상이면 부르지 않는다. 같은 판단일은 다시 부르지 않는다
    (매번 비용이 들고 결과가 달라질 수 있어서): 기록이 있으면 아무것도 하지 않는다.
    """
    if has_judgment(session, bot_id, request.session_date):
        return
    candles = request.candles is not None
    strategy = CANDLE_STRATEGY if candles else AI_STRATEGY
    advisor, budget = ai.pick(candles) if ai else (None, Decimal(0))
    start, end = month_of(now)
    used = spent(session, start, end, strategy)
    data = AiJudgmentData(status="", session_date=request.session_date.isoformat())
    if advisor is not None and used >= budget:
        judgment = Judgment(
            request.session_date,
            JudgmentStatus.OVER_BUDGET,
            request,
            error=f"이번 달 AI 비용 ${used:.2f}, 상한 ${budget}",
        )
        data["spent"], data["budget"] = str(used.quantize(Decimal("0.01"))), str(budget)
    else:
        judgment = judge(advisor, request)
    already_over = over_budget_since(session, bot_id, start)
    save_judgment(session, bot_id, judgment, now, strategy)
    if judgment.status is not JudgmentStatus.OK:
        data["status"] = judgment.status.value
        # 비용 상한은 그달 처음 한 번만 알린다
        quiet = judgment.status is JudgmentStatus.OVER_BUDGET and already_over
        add_event(
            session,
            now,
            "INFO" if quiet else "WARN",
            EventKind.AI_JUDGMENT,
            f"{request.session_date} AI 판단 {judgment.status.value}: {judgment.error}",
            bot_id=bot_id,
            data=data,
        )
    session.commit()
