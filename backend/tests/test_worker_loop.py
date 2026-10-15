import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from tests.fakes import WeekdayCalendar, make_bars
from trading_lab.application.market import StoredMarket
from trading_lab.domain.bars import DailyBar
from trading_lab.domain.bot import BotState, CommandKind
from trading_lab.domain.broker import (
    AccountSnapshot,
    BrokerAccessError,
    ExchangeRate,
    Instrument,
    Quote,
)
from trading_lab.domain.portfolio import CostModel, RiskLimits
from trading_lab.persistence.bars import upsert_daily_bars
from trading_lab.persistence.bots import create_bot, enqueue_command, get_bot
from trading_lab.persistence.heartbeat import latest_heartbeat
from trading_lab.persistence.models import (
    BrokerAccountRow,
    CommandRow,
    DecisionRow,
    EventRow,
    ExchangeRateRow,
    InstrumentRow,
    LiveBarRow,
    QuoteRow,
)
from trading_lab.worker.heartbeat import HeartbeatThread
from trading_lab.worker.loop import Worker, release_worker_lock, try_acquire_worker_lock

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
        strategy="dip_saver",
        params={"deposit": 500, "day": 1, "dip": 5, "hot": 5, "high": 10, "sma": 5},
        initial_cash=Decimal(500),
        costs=CostModel(),
        limits=RiskLimits(),
        now=NOW,
    )
    bot.state = state
    session.commit()
    return bot.id


def test_restart_resumes_running_bots(worker: Worker, session: Session) -> None:
    running = new_bot(session, BotState.RUNNING)
    stopped = new_bot(session, BotState.STOPPED)
    worker.recover_after_restart()
    session.expire_all()
    assert get_bot(session, running).state == BotState.RUNNING  # type: ignore[union-attr]
    assert get_bot(session, stopped).state == BotState.STOPPED  # type: ignore[union-attr]
    assert session.scalars(select(EventRow.kind)).all() == ["restart_resume"]


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


class FakeLive:
    source = "test"

    def __init__(self) -> None:
        self.quote_calls = 0

    def instruments(self, symbols: list[str]) -> list[Instrument]:
        return [Instrument(s, s, "NASDAQ", "ETF", "ACTIVE", "USD", Decimal(3)) for s in symbols]

    def quotes(self, symbols: list[str]) -> list[Quote]:
        self.quote_calls += 1
        return [Quote(s, Decimal("123.45"), NOW) for s in symbols]

    def live_bars(self, symbols: list[str]) -> list[DailyBar]:
        return make_bars(symbols[0], [123])

    def exchange_rate(self, base: str, quote: str) -> ExchangeRate:
        return ExchangeRate(base, quote, Decimal("1400.5"), None, NOW)


def test_live_quotes_only_for_bot_symbols_in_trading_hours(
    make_session: Callable[[], Session], session: Session
) -> None:
    new_bot(session, BotState.RUNNING)
    live = FakeLive()
    clock = [datetime(2026, 10, 2, 14, 0, tzinfo=UTC)]  # 금요일 10:00 뉴욕
    worker = Worker(make_session, StoredMarket(), CAL, now=lambda: clock[0], live=live)

    worker.refresh_live()
    worker.refresh_live()  # 30초가 지나지 않았다
    clock[0] = datetime(2026, 10, 3, 14, 0, tzinfo=UTC)  # 토요일: 거래 시간 아님
    worker.refresh_live()

    assert live.quote_calls == 1
    assert session.get_one(QuoteRow, "QQQ").price == Decimal("123.45")
    assert session.get_one(InstrumentRow, "QQQ").leverage_factor == 3
    assert session.get_one(LiveBarRow, "QQQ").close == 123
    # 원/달러는 거래 시간과 상관없이 한 시간마다, 출처 코드와 함께 (W1)
    fx = session.get_one(ExchangeRateRow, ("USD", "KRW"))
    assert (fx.mid_rate, fx.source, fx.fetched_at) == (Decimal("1400.5"), "test", clock[0])


def test_new_bot_symbol_gets_instrument_info_without_waiting_a_day(
    make_session: Callable[[], Session], session: Session
) -> None:
    new_bot(session, BotState.RUNNING)
    clock = [datetime(2026, 10, 2, 14, 0, tzinfo=UTC)]
    worker = Worker(make_session, StoredMarket(), CAL, now=lambda: clock[0], live=FakeLive())
    worker.refresh_live()
    assert session.get(InstrumentRow, "VOO") is None

    create_bot(
        session,
        name="voo",
        symbol="VOO",
        strategy="dip_saver",
        params={"deposit": 500, "day": 1, "dip": 5, "hot": 5, "high": 10, "sma": 5},
        initial_cash=Decimal(500),
        costs=CostModel(),
        limits=RiskLimits(),
        now=clock[0],
    )
    session.commit()
    clock[0] += timedelta(seconds=15)  # 하루가 지나지 않았어도 새 종목 정보는 바로 받는다
    worker.refresh_live()
    assert session.get_one(InstrumentRow, "VOO").leverage_factor == 3


def test_account_read_hourly_and_keeps_last_value_on_failure(
    make_session: Callable[[], Session], session: Session
) -> None:
    clock = [NOW]
    calls: list[date] = []

    def read(since: date) -> AccountSnapshot:
        calls.append(since)
        if len(calls) > 1:
            raise BrokerAccessError("HTTP 403 edge-blocked")
        return AccountSnapshot("test", Decimal("12.5"), Decimal("10000"), [], [])

    worker = Worker(make_session, StoredMarket(), CAL, now=lambda: clock[0], account=read)
    worker.refresh_account()
    clock[0] = NOW + timedelta(minutes=5)
    worker.refresh_account()
    assert len(calls) == 1
    clock[0] = NOW + timedelta(hours=1, seconds=-1)
    worker.refresh_account()
    assert len(calls) == 1
    clock[0] = NOW + timedelta(hours=1)
    worker.refresh_account()

    assert len(calls) == 2
    row = session.scalars(select(BrokerAccountRow)).one()
    assert row.cash_usd == Decimal("12.5") and row.fetched_at == NOW
    assert row.error == "access" and row.error_at == clock[0]


def test_heartbeat_beats_apart_from_long_ticks_but_not_when_stuck(
    engine: Engine, session: Session
) -> None:
    # 평가가 오래 걸려도(AI 판단) 따로 생존 신호를 남기고, 메인 루프가 멈추면 남기지 않는다
    now = [0.0]
    started = datetime(2026, 10, 7, tzinfo=UTC)
    heart = HeartbeatThread(
        sessionmaker(engine), "w1", "0", started, 15, threading.Event(), 600, lambda: now[0]
    )
    now[0] = 300  # 한 바퀴가 5분째 (예: 느린 AI 판단)
    assert heart.beat()
    beat = latest_heartbeat(session)
    assert beat is not None and beat.worker_id == "w1"
    now[0] = 601  # 10분 넘게 다음 바퀴를 시작하지 못함
    assert not heart.beat()
    heart.loop_started()
    assert heart.beat()
