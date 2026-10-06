"""저장된 일봉으로 과거 거래일마다 정기 평가를 재생한다.

정기 DRY RUN 경로(evaluate_bot)가 백테스트와 같은 체결을 만드는지 확인하는 용도다.
"""

from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy.orm import Session

from quant_lab.application.ai_judge import AiConfig
from quant_lab.application.bar_sync import DEFAULT_SETTLE
from quant_lab.application.dry_run import EvaluationOutcome, Trigger, evaluate_bot
from quant_lab.application.market import StoredMarket
from quant_lab.domain.bars import TradingCalendar


def replay_bot(
    make_session: Callable[[], Session],
    bot_id: int,
    calendar: TradingCalendar,
    start: date,
    end: date,
    ai: AiConfig | None = None,
) -> list[EvaluationOutcome]:
    outcomes = []
    for day in calendar.sessions(start, end):
        now = calendar.session_close(day) + DEFAULT_SETTLE + timedelta(minutes=1)
        with make_session() as session:
            outcomes.append(
                evaluate_bot(
                    session,
                    bot_id,
                    market=StoredMarket(),
                    calendar=calendar,
                    now=now,
                    trigger=Trigger.SCHEDULED,
                    ai=ai,
                )
            )
    return outcomes
