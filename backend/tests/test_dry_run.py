from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.adapters.toss.client import TossError, TossForbiddenError
from quant_lab.application.bar_sync import SyncResult
from quant_lab.application.dry_run import RunStatus, Trigger, evaluate_bot
from quant_lab.application.replay import replay_bot
from quant_lab.domain.backtest import run_backtest
from quant_lab.domain.bars import DailyBar
from quant_lab.domain.bot import BotState
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import SmaCross
from quant_lab.persistence.bars import upsert_daily_bars
from quant_lab.persistence.bots import create_bot, get_bot, load_account
from quant_lab.persistence.models import DecisionRow, EventRow, SimOrderRow
from tests.fakes import WeekdayCalendar, make_bars

CAL = WeekdayCalendar()
COSTS = CostModel()
# 오르내림이 있어 SMA 3/5 교차가 여러 번 나오는 종가
CLOSES = [100 + (i % 9) * 2 - (i % 4) * 3 for i in range(60)]


@dataclass
class FakeMarket:
    error: Exception | None = None
    confirmed: bool | None = None

    def refresh(self, session: Session, symbol: str, now: datetime) -> SyncResult | None:
        if self.error is not None:
            raise self.error
        return None

    def confirm_session(self, day: date) -> bool | None:
        return self.confirmed


def after_close(day: date) -> datetime:
    """정규장 마감(20:00 UTC) + 2시간 여유 이후."""
    return datetime.combine(day, time(22, 30), tzinfo=UTC)


@pytest.fixture
def make_session(engine: Engine, session: Session) -> Callable[[], Session]:
    return sessionmaker(engine)


@pytest.fixture
def bars(session: Session) -> list[DailyBar]:
    data = make_bars("QQQ", CLOSES)
    upsert_daily_bars(session, data, "test", datetime(2026, 1, 1, tzinfo=UTC))
    session.commit()
    return data


@pytest.fixture
def bot_id(session: Session, bars: list[DailyBar]) -> int:
    bot = create_bot(
        session,
        name="t",
        symbol="QQQ",
        strategy="sma_cross",
        params={"fast": 3, "slow": 5},
        initial_cash=Decimal(10_000),
        costs=COSTS,
        limits=RiskLimits(),
        now=datetime.now(UTC),
    )
    bot.state = BotState.RUNNING
    session.commit()
    return bot.id


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_evaluates_latest_completed_bar_once(
    session: Session, bars: list[DailyBar], bot_id: int
) -> None:
    day = bars[10].session_date
    first = evaluate_bot(
        session,
        bot_id,
        market=FakeMarket(),
        calendar=CAL,
        now=after_close(day),
        trigger=Trigger.SCHEDULED,
    )
    again = evaluate_bot(
        session,
        bot_id,
        market=FakeMarket(),
        calendar=CAL,
        now=after_close(day) + timedelta(minutes=5),
        trigger=Trigger.MANUAL,
    )

    assert first.status is RunStatus.OK and first.session_date == day
    assert again.status is RunStatus.OK and "이미" in again.detail
    assert count(session, DecisionRow) == 1
    bot = get_bot(session, bot_id)
    assert bot is not None
    assert bot.next_evaluation_at == datetime.combine(bars[11].session_date, time(22), tzinfo=UTC)


def test_bar_before_settle_time_is_not_used(
    session: Session, bars: list[DailyBar], bot_id: int
) -> None:
    day = bars[10].session_date
    # 마감 30분 뒤: 아직 확정 여유 시간 전이므로 전날 봉으로 판단한다
    out = evaluate_bot(
        session,
        bot_id,
        market=FakeMarket(),
        calendar=CAL,
        now=datetime.combine(day, time(20, 30), tzinfo=UTC),
        trigger=Trigger.SCHEDULED,
    )
    assert out.session_date == bars[9].session_date


def test_missing_latest_bar_skips_and_retries(
    session: Session, bars: list[DailyBar], bot_id: int
) -> None:
    after_last = bars[-1].session_date + timedelta(days=3)  # 저장된 봉보다 뒤의 거래일
    now = after_close(after_last)
    out = evaluate_bot(
        session, bot_id, market=FakeMarket(), calendar=CAL, now=now, trigger=Trigger.SCHEDULED
    )
    assert out.status is RunStatus.SKIPPED
    assert count(session, DecisionRow) == 0
    bot = get_bot(session, bot_id)
    assert bot is not None and bot.state == BotState.RUNNING
    assert bot.next_evaluation_at == now + timedelta(minutes=15)

    # 같은 이유로 다시 건너뛰면 경고(알림)는 처음 한 번만
    evaluate_bot(
        session,
        bot_id,
        market=FakeMarket(),
        calendar=CAL,
        now=now + timedelta(minutes=15),
        trigger=Trigger.SCHEDULED,
    )
    levels = session.scalars(
        select(EventRow.level).where(EventRow.kind == "run_skipped").order_by(EventRow.id)
    ).all()
    assert levels == ["WARN", "INFO"]


def test_forbidden_puts_bot_in_error(session: Session, bars: list[DailyBar], bot_id: int) -> None:
    market = FakeMarket(error=TossForbiddenError(403, "edge-blocked", "blocked", "r1"))
    out = evaluate_bot(
        session,
        bot_id,
        market=market,
        calendar=CAL,
        now=after_close(bars[10].session_date),
        trigger=Trigger.SCHEDULED,
    )
    assert out.status is RunStatus.ERROR
    bot = get_bot(session, bot_id)
    assert bot is not None and bot.state == BotState.ERROR
    assert count(session, DecisionRow) == 0


def test_transient_toss_error_keeps_running(
    session: Session, bars: list[DailyBar], bot_id: int
) -> None:
    market = FakeMarket(error=TossError(500, "internal-error", "x", "r1"))
    out = evaluate_bot(
        session,
        bot_id,
        market=market,
        calendar=CAL,
        now=after_close(bars[10].session_date),
        trigger=Trigger.SCHEDULED,
    )
    assert out.status is RunStatus.SKIPPED
    bot = get_bot(session, bot_id)
    assert bot is not None and bot.state == BotState.RUNNING


def test_replay_matches_backtest(
    make_session: Callable[[], Session],
    session: Session,
    bars: list[DailyBar],
    bot_id: int,
) -> None:
    start, end = bars[4].session_date, bars[-1].session_date
    replay_bot(make_session, bot_id, CAL, start, end)

    filled = list(
        session.scalars(
            select(SimOrderRow).where(SimOrderRow.status == "FILLED").order_by(SimOrderRow.id)
        )
    )
    expected = run_backtest(bars, SmaCross(fast=3, slow=5), Decimal(10_000), COSTS).fills
    assert len(expected) >= 4
    assert [(o.side, o.signal_date, o.fill_date, o.qty, o.price) for o in filled] == [
        (f.side, f.signal_date, f.fill_date, f.qty, f.price) for f in expected
    ]
    pf = load_account(session, bot_id)
    last_fill = expected[-1]
    assert pf.qty == (last_fill.qty if last_fill.side == "BUY" else 0)

    # 주간 리포트: 금요일 판단마다 한 번, 그 주 체결 수와 함께
    reports: list[dict[str, Any]] = list(
        session.scalars(select(EventRow.data).where(EventRow.kind == "weekly_report"))
    )
    fridays = [
        b.session_date
        for b in bars
        if start <= b.session_date <= end and b.session_date.weekday() == 4
    ]
    assert [r["week_end"] for r in reports] == [d.isoformat() for d in fridays]
    assert sum(r["buys"] + r["sells"] for r in reports) == sum(
        1 for f in expected if f.fill_date <= fridays[-1]
    )


def test_db_rejects_duplicate_decision_for_same_bar(
    session: Session, bars: list[DailyBar], bot_id: int
) -> None:
    evaluate_bot(
        session,
        bot_id,
        market=FakeMarket(),
        calendar=CAL,
        now=after_close(bars[10].session_date),
        trigger=Trigger.SCHEDULED,
    )
    original = session.scalars(select(DecisionRow)).one()
    dup = DecisionRow(
        bot_id=original.bot_id,
        symbol=original.symbol,
        session_date=original.session_date,
        mode=original.mode,
        run_id=original.run_id,
        strategy={},
        action="HOLD",
        target_long=False,
        holding=False,
        reason="dup",
        indicators={},
        created_at=original.created_at,
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
