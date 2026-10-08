from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application.bar_sync import SyncResult
from quant_lab.application.dry_run import RunStatus, Trigger, evaluate_bot
from quant_lab.application.messages import event_message
from quant_lab.application.replay import replay_bot
from quant_lab.domain.backtest import run_backtest
from quant_lab.domain.bars import DailyBar
from quant_lab.domain.bot import BotState
from quant_lab.domain.broker import BrokerAccessError, BrokerError
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import DipSaver
from quant_lab.persistence.bars import upsert_daily_bars
from quant_lab.persistence.bots import create_bot, get_bot, load_account
from quant_lab.persistence.models import BotDepositRow, DecisionRow, EventRow, SimOrderRow
from tests.fakes import WeekdayCalendar, make_bars

CAL = WeekdayCalendar()
COSTS = CostModel()
# 오르내림이 있어 하락장·고점이 여러 번 나오는 종가
CLOSES = [100 + (i % 9) * 2 - (i % 4) * 3 for i in range(60)]
DIP = DipSaver(deposit=500, day=1, dip=5, hot=5, high=10, sma=5)


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
        strategy="dip_saver",
        params=DIP.params,
        initial_cash=Decimal(500),
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
    market = FakeMarket(error=BrokerAccessError("허용 IP 아님"))
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
    market = FakeMarket(error=BrokerError("일시 장애"))
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


def test_replay_writes_weekly_reports_and_readable_events(
    make_session: Callable[[], Session],
    session: Session,
    bars: list[DailyBar],
    bot_id: int,
) -> None:
    start, end = bars[DIP.warmup - 1].session_date, bars[-1].session_date
    replay_bot(make_session, bot_id, CAL, start, end)

    expected = run_backtest({bars[0].symbol: bars}, DIP, Decimal(500), COSTS).fills
    assert len(expected) >= 3

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
    # 엔진이 실제로 남긴 이벤트는 모두 형식에 맞아 알림 문장으로 바뀐다 (domain/events.py)
    for kind, level, message, data in session.execute(
        select(EventRow.kind, EventRow.level, EventRow.message, EventRow.data)
    ):
        event_message(kind, level, message, data, "t", "QQQ")


@pytest.mark.parametrize("weights", [{"QQQ": 100}, {"QQQ": 60, "VOO": 40}])
def test_dip_saver_replay_matches_backtest(
    make_session: Callable[[], Session],
    session: Session,
    bars: list[DailyBar],
    weights: dict[str, int],
) -> None:
    """모으기 전략도 정기 평가 재생이 백테스트와 같은 입금·추가 매수를 만든다.

    두 종목이면 현금을 함께 쓰며 고점 종목의 몫은 모아 두고, 하락장 종목이 몰아 산다.
    """
    voo = make_bars("VOO", [80 + (i % 7) * 3 - (i % 5) * 2 for i in range(len(CLOSES))])
    upsert_daily_bars(session, voo, "test", datetime(2026, 1, 1, tzinfo=UTC))
    strategy = DIP
    bot = create_bot(
        session,
        name="dip",
        symbol="QQQ",
        strategy="dip_saver",
        params=strategy.params,
        initial_cash=Decimal(500),
        costs=COSTS,
        limits=RiskLimits(),
        now=datetime.now(UTC),
        weights=weights,
    )
    bot.state = BotState.RUNNING
    session.commit()
    replay_bot(
        make_session, bot.id, CAL, bars[strategy.warmup - 1].session_date, bars[-1].session_date
    )

    series = {"QQQ": bars, "VOO": voo}
    expected = run_backtest(
        {s: series[s] for s in weights}, strategy, Decimal(500), COSTS, weights=weights
    )
    filled = session.scalars(
        select(SimOrderRow).where(SimOrderRow.status == "FILLED").order_by(SimOrderRow.id)
    )
    assert len(expected.fills) >= 3 and all(f.side == "BUY" for f in expected.fills)
    assert {f.symbol for f in expected.fills} == set(weights)
    assert [(o.symbol, o.signal_date, o.fill_date, o.qty, o.price) for o in filled] == [
        (f.symbol, f.signal_date, f.fill_date, f.qty, f.price) for f in expected.fills
    ]
    deposits = session.scalars(select(BotDepositRow.session_date).order_by(BotDepositRow.month))
    assert list(deposits) == [p.session_date for p in expected.equity if p.deposit > 0]
    pf = load_account(session, bot.id)
    assert pf.contributed == expected.metrics.contributed
    assert pf.cash == expected.equity[-1].cash


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
