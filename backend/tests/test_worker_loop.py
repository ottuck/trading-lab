from collections.abc import Callable
from datetime import UTC, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application.market import StoredMarket
from quant_lab.domain.bot import BotState, CommandKind
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.persistence.bars import upsert_daily_bars
from quant_lab.persistence.bots import create_bot, enqueue_command, get_bot
from quant_lab.persistence.models import CommandRow, DecisionRow, EventRow
from quant_lab.worker.loop import Worker, release_worker_lock, try_acquire_worker_lock
from tests.fakes import WeekdayCalendar, make_bars

CAL = WeekdayCalendar()
BARS = make_bars("QQQ", [100 + (i % 7) for i in range(30)])
NOW = datetime.combine(BARS[20].session_date, time(22, 30), tzinfo=UTC)


@pytest.fixture
def make_session(engine: Engine, session: Session) -> Callable[[], Session]:
    upsert_daily_bars(session, BARS, "test", NOW)
    session.commit()
    return sessionmaker(engine)


@pytest.fixture
def worker(make_session: Callable[[], Session]) -> Worker:
    return Worker(make_session, StoredMarket(), CAL, now=lambda: NOW)


def new_bot(session: Session, state: BotState = BotState.STOPPED) -> int:
    bot = create_bot(
        session,
        name=f"b{state}",
        symbol="QQQ",
        strategy="sma_cross",
        params={"fast": 3, "slow": 5},
        initial_cash=Decimal(10_000),
        costs=CostModel(),
        limits=RiskLimits(),
        now=NOW,
    )
    bot.state = state
    session.commit()
    return bot.id


def test_restart_pauses_running_bots(worker: Worker, session: Session) -> None:
    running = new_bot(session, BotState.RUNNING)
    stopped = new_bot(session, BotState.STOPPED)
    worker.recover_after_restart()
    session.expire_all()
    assert get_bot(session, running).state == BotState.PAUSED  # type: ignore[union-attr]
    assert get_bot(session, stopped).state == BotState.STOPPED  # type: ignore[union-attr]
    assert "restart_pause" in session.scalars(select(EventRow.kind)).all()


def test_start_command_runs_evaluation_once(worker: Worker, session: Session) -> None:
    bot_id = new_bot(session)
    enqueue_command(session, bot_id, CommandKind.START, NOW)
    session.commit()

    worker.tick()
    worker.tick()  # 같은 명령·같은 봉을 다시 처리하지 않는다

    session.expire_all()
    bot = get_bot(session, bot_id)
    assert bot is not None and bot.state == BotState.RUNNING
    assert session.scalars(select(CommandRow.result)).all() == ["OK"]
    decisions = session.scalars(select(DecisionRow)).all()
    assert [d.session_date for d in decisions] == [BARS[20].session_date]


def test_only_one_worker_gets_the_lock(engine: Engine) -> None:
    with engine.connect() as first, engine.connect() as second:
        assert try_acquire_worker_lock(first)
        assert not try_acquire_worker_lock(second)
        release_worker_lock(first)
        assert try_acquire_worker_lock(second)  # 잠금을 풀면 다른 Worker가 넘겨받는다
        release_worker_lock(second)


def test_watchlist_sync_refreshes_only_stale_symbols(make_session: Callable[[], Session]) -> None:
    refreshed: list[str] = []

    class RecordingMarket(StoredMarket):
        def refresh(self, session: Session, symbol: str, now: datetime) -> None:
            refreshed.append(symbol)

    worker = Worker(make_session, RecordingMarket(), CAL, now=lambda: NOW, watchlist=["QQQ", "VOO"])
    worker.sync_watchlist()
    worker.sync_watchlist()  # 30분 안에는 다시 확인하지 않는다
    assert refreshed == ["VOO"]  # QQQ는 이미 최신 거래일까지 있음
