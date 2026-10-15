"""주간 리포트: 한 주의 마지막 거래일 판단과 함께 그 주를 요약한다.

판단은 거래일마다 한 번만 생기므로(유일 제약) 리포트도 주마다 한 번만 생긴다.
금요일이 휴장이면 그 주의 마지막 거래일(목요일 등)에 만든다.
"""

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trading_lab.domain.bars import TradingCalendar
from trading_lab.domain.events import BalanceSummary, EventKind, WeeklyData
from trading_lab.persistence.bots import bot_weights
from trading_lab.persistence.models import BotRow, EventRow, RunRow, SimOrderRow


def is_week_end(calendar: TradingCalendar, session_date: date) -> bool:
    """다음 거래일이 다른 주(월요일 시작)에 있으면 이번 주 마지막 거래일이다."""
    upcoming = calendar.sessions(
        session_date + timedelta(days=1), session_date + timedelta(days=14)
    )
    week_start = session_date - timedelta(days=session_date.weekday())
    return not upcoming or upcoming[0] >= week_start + timedelta(days=7)


def weekly_summary(
    session: Session, bot: BotRow, session_date: date, end: BalanceSummary
) -> WeeklyData:
    """이번 주 자산·그냥 보유 대비·거래 횟수. end는 이번 판단의 잔고 요약(equity, close)."""
    week_start = session_date - timedelta(days=session_date.weekday())
    base_q = (
        select(EventRow.data)
        .join(RunRow, EventRow.run_id == RunRow.id)
        .where(EventRow.bot_id == bot.id, EventRow.kind == EventKind.DECISION)
    )
    # 기준점: 지난주 마지막 판단. 이번 주에 처음 시작했으면 이번 주 첫 판단.
    base = session.scalar(
        base_q.where(RunRow.session_date < week_start).order_by(RunRow.session_date.desc())
    ) or session.scalar(
        base_q.where(RunRow.session_date >= week_start).order_by(RunRow.session_date)
    )
    start = base if base and "equity" in base and "close" in base else end
    fills = session.execute(
        select(SimOrderRow.side, func.count())
        .where(
            SimOrderRow.bot_id == bot.id,
            SimOrderRow.status == "FILLED",
            SimOrderRow.fill_date >= week_start,
            SimOrderRow.fill_date <= session_date,
        )
        .group_by(SimOrderRow.side)
    ).all()
    counts = {side: n for side, n in fills}

    def change(a: Any, b: Any) -> str:
        return str(round(Decimal(str(b)) / Decimal(str(a)) - 1, 6))

    def hold_change(a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
        """그냥 들고 있었다면의 이번 주 변화. 여러 종목이면 종목 비율로 가중 평균한다."""
        if "closes" not in a or "closes" not in b:
            return change(a["close"], b["close"])
        # 주중에 종목을 바꿨으면 두 날 모두 가격이 있는 종목만 그 비율로 본다.
        both = {
            s: w
            for s, w in bot_weights(bot).items()
            if w > 0 and s in a["closes"] and s in b["closes"]
        }
        if not both:
            return change(a["close"], b["close"])
        total = sum(
            Decimal(w) * (Decimal(b["closes"][s]) / Decimal(a["closes"][s]) - 1)
            for s, w in both.items()
        )
        return str(round(total / sum(both.values()), 6))

    # 이번 주에 들어온 입금은 수익이 아니므로 뺀다 (모으기 전략).
    added = Decimal(str(end.get("contributed", 0))) - Decimal(
        str(start.get("contributed", end.get("contributed", 0)))
    )

    return {  # WeeklyData
        "symbol": bot.symbol,
        "week_start": week_start.isoformat(),
        "week_end": session_date.isoformat(),
        "equity": end["equity"],
        "total_return": end["total_return"],
        "week_return": change(start["equity"], Decimal(str(end["equity"])) - added),
        "hold_return": hold_change(start, end),
        "buys": counts.get("BUY", 0),
        "sells": counts.get("SELL", 0),
    }
