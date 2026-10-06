"""AI 판단 1회: 입력 요약 → AI 호출 → 규칙 검사 → 기록할 판단 (project.md 14절).

실패·형식 오류도 판단으로 남긴다 (그날은 사고팔지 않는다, 원칙 5).
"""

from quant_lab.domain.advisor import (
    AdviceRequest,
    Advisor,
    AdvisorError,
    Judgment,
    JudgmentStatus,
    check_advice,
)


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
