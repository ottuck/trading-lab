"""실제로 따라 사기 (실거래 R2): 승인 순서, 먼저 적고 보내기, 같은 키로만 다시, 모르면 멈추기."""

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from tests.fakes import WeekdayCalendar
from trading_lab.application.errors import Conflict
from trading_lab.application.live import LiveDesk, check_holdings, live_position, month_bought
from trading_lab.application.live_admin import approve, overview, resolve_unknown, set_halted
from trading_lab.application.market import StoredMarket
from trading_lab.domain.broker import (
    AccountOrder,
    AccountSnapshot,
    AmountOrder,
    BrokerError,
    Holding,
    Instrument,
    OrderStatus,
    SellOrder,
)
from trading_lab.domain.live import LiveState, RealFill, partial_sell_qty, real_ledger
from trading_lab.domain.portfolio import CostModel, RiskLimits
from trading_lab.persistence.bots import create_bot
from trading_lab.persistence.broker_account import save_snapshot
from trading_lab.persistence.market_info import upsert_instruments
from trading_lab.persistence.models import (
    BotPositionRow,
    BotRow,
    BrokerAccountRow,
    DailyBarRow,
    DecisionRow,
    EventRow,
    LiveOrderRow,
    RunRow,
    SimOrderRow,
)
from trading_lab.worker.loop import Worker

SIGNAL = date(2026, 10, 1)  # 목요일 판단 → 금요일에 산다
TRADE = date(2026, 10, 2)
OPEN = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)
CLOSE_CUTOFF = datetime(2026, 10, 2, 19, 0, tzinfo=UTC)
SEND = OPEN + timedelta(minutes=5)


class FakeTrader:
    source = "test"
    idempotency_window = timedelta(minutes=10)

    def __init__(self) -> None:
        self.placed: list[AmountOrder] = []
        self.sold: list[SellOrder] = []
        self.fail_next = 0
        self.orders: dict[str, AccountOrder] = {}

    def order_window(self, day: date) -> tuple[datetime, datetime] | None:
        """평일마다 같은 시각에 열린다 (TRADE 날 기준으로 옮김)."""
        if day.weekday() >= 5:
            return None
        shift = day - TRADE
        return OPEN + shift, CLOSE_CUTOFF + shift

    cash = Decimal("100")
    cash_error = False

    def available_cash(self) -> Decimal:
        if self.cash_error:
            raise BrokerError("계좌 조회 실패")
        return self.cash

    def place_amount_buy(self, order: AmountOrder) -> str:
        self.placed.append(order)
        if self.fail_next:
            self.fail_next -= 1
            raise BrokerError("연결 끊김 (접수됐는지 모름)")
        order_id = f"o-{order.key}"
        self.orders[order_id] = AccountOrder(
            order_id, order.symbol, "BUY", OrderStatus.FILLED, "USD", SEND,
            order.amount, Decimal("0.0048"), order.amount,
        )  # fmt: skip
        return order_id

    def place_quantity_sell(self, order: SellOrder) -> str:
        self.sold.append(order)
        order_id = f"o-{order.key}"
        self.orders[order_id] = AccountOrder(
            order_id, order.symbol, "SELL", OrderStatus.FILLED, "USD", SEND,
            None, order.quantity, Decimal("1.2"), order.quantity,
        )  # fmt: skip
        return order_id

    def get_order(self, order_id: str) -> AccountOrder:
        return self.orders[order_id]

    def find_orders(self, symbol: str, day: date) -> list[AccountOrder]:
        return [o for o in self.orders.values() if o.symbol == symbol]


@pytest.fixture
def make_session(engine: Engine, session: Session) -> Callable[[], Session]:
    return sessionmaker(engine)


def live_bot(session: Session) -> BotRow:
    bot = create_bot(
        session,
        name="나 카피 봇",
        symbol="VOO",
        strategy="dip_saver",
        params={"deposit": 675},
        initial_cash=Decimal(675),
        costs=CostModel(),
        limits=RiskLimits(),
        now=OPEN - timedelta(days=3),
    )
    bot.live_ratio, bot.live_since = Decimal("0.01"), OPEN - timedelta(days=2)
    session.flush()
    return bot


def sim_buy(
    session: Session,
    bot: BotRow,
    budget: str | None,
    signal: date = SIGNAL,
    *,
    symbol: str = "VOO",
    side: str = "BUY",
) -> SimOrderRow:
    """모의 판단이 만든 주문 (dry_run이 남기는 것과 같은 모양). 모두 파는 주문은 예산이 없다."""
    run = RunRow(id=uuid.uuid4(), bot_id=bot.id, trigger="SCHEDULED", started_at=OPEN, status="OK")
    session.add(run)
    session.flush()
    decision = DecisionRow(
        bot_id=bot.id, symbol=symbol, session_date=signal, mode="DRY_RUN", run_id=run.id,
        strategy={}, action=side, target_long=side == "BUY", holding=False, reason="",
        indicators={}, created_at=OPEN - timedelta(hours=12),
    )  # fmt: skip
    session.add(decision)
    session.flush()
    sim = SimOrderRow(
        bot_id=bot.id, symbol=symbol, decision_id=decision.id, side=side, status="PENDING",
        signal_date=signal, created_at=OPEN - timedelta(hours=12),
        budget=Decimal(budget) if budget else None,
    )  # fmt: skip
    session.add(sim)
    session.commit()
    return sim


def live_order(session: Session) -> LiveOrderRow:
    session.expire_all()
    return session.scalars(select(LiveOrderRow)).one()


class PendingTrader(FakeTrader):
    def place_amount_buy(self, order: AmountOrder) -> str:
        order_id = super().place_amount_buy(order)
        self.orders[order_id] = replace(
            self.orders[order_id],
            status=OrderStatus.OPEN,
            filled_quantity=Decimal(0),
            filled_amount=Decimal(0),
        )
        return order_id


@pytest.mark.parametrize(
    "terminal", [OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED]
)
def test_worker_refreshes_account_after_acceptance_partial_and_terminal_changes(
    make_session: Callable[[], Session], session: Session, terminal: OrderStatus
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "337.5")
    trader = PendingTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())
    clock = [SEND - timedelta(seconds=15)]
    reads: list[datetime] = []

    def read(since: date) -> AccountSnapshot:
        reads.append(clock[0])
        return AccountSnapshot("test", Decimal(100 - len(reads)), Decimal(0), [], [])

    worker = Worker(
        make_session, StoredMarket(), WeekdayCalendar(), now=lambda: clock[0], account=read,
        desk=desk,
    )  # fmt: skip
    worker.refresh_account()
    clock[0] = SEND
    worker.tick()
    order = live_order(session)
    assert order.state == LiveState.SENT
    assert reads == [SEND - timedelta(seconds=15), SEND]
    assert not desk.account_refresh_pending
    assert order.broker_order_id is not None
    broker_id = order.broker_order_id

    clock[0] += timedelta(minutes=1)
    trader.orders[broker_id] = replace(
        trader.orders[broker_id], status=OrderStatus.PARTIAL,
        filled_quantity=Decimal("0.002"), filled_amount=Decimal("1.5"),
    )  # fmt: skip
    worker.tick()
    assert len(reads) == 3
    assert live_order(session).filled_qty == Decimal("0.002")
    clock[0] += timedelta(minutes=1)
    worker.tick()  # 같은 부분 체결을 다시 확인해도 계좌를 더 읽지 않는다
    assert len(reads) == 3

    clock[0] += timedelta(minutes=1)
    trader.orders[broker_id] = replace(trader.orders[broker_id], status=terminal)
    worker.tick()
    assert len(reads) == 4
    session.expire_all()
    account = session.scalars(select(BrokerAccountRow)).one()
    assert account.cash_usd == Decimal(96) and account.fetched_at == clock[0]
    assert not desk.account_refresh_pending


def test_order_refresh_failure_keeps_pending_and_retries_after_one_minute(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "337.5")
    desk = LiveDesk(make_session, PendingTrader(), WeekdayCalendar())
    clock = [SEND - timedelta(seconds=15)]
    calls: list[datetime] = []

    def read(since: date) -> AccountSnapshot:
        calls.append(clock[0])
        if len(calls) == 2:
            raise BrokerError("temporary")
        return AccountSnapshot("test", Decimal(100 - len(calls)), Decimal(0), [], [])

    worker = Worker(
        make_session, StoredMarket(), WeekdayCalendar(), now=lambda: clock[0], account=read,
        desk=desk,
    )  # fmt: skip
    worker.refresh_account()
    clock[0] = SEND
    worker.tick()
    assert desk.account_refresh_pending and len(calls) == 2
    account = session.scalars(select(BrokerAccountRow)).one()
    assert account.cash_usd == Decimal(99) and account.error == "temporary"
    clock[0] += timedelta(seconds=59)
    worker.tick()
    assert desk.account_refresh_pending and len(calls) == 2
    clock[0] += timedelta(seconds=1)
    worker.tick()
    assert not desk.account_refresh_pending and len(calls) == 3
    session.expire_all()
    account = session.scalars(select(BrokerAccountRow)).one()
    assert account.cash_usd == Decimal(97) and account.error is None


def test_worker_coalesces_multiple_order_acceptances_and_fills_into_one_refresh(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "337.5")
    session.add(
        LiveOrderRow(
            bot_id=bot.id,
            symbol="QQQ",
            signal_date=SIGNAL,
            trade_date=TRADE,
            amount=Decimal(1),
            key="second",
            state=LiveState.APPROVED,
            created_at=OPEN,
            updated_at=OPEN,
        )
    )
    session.commit()
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())
    clock = [SEND - timedelta(seconds=15)]
    calls: list[datetime] = []

    def read(since: date) -> AccountSnapshot:
        calls.append(clock[0])
        return AccountSnapshot("test", Decimal(100), Decimal(0), [], [])

    worker = Worker(
        make_session, StoredMarket(), WeekdayCalendar(), now=lambda: clock[0], account=read,
        desk=desk,
    )  # fmt: skip
    worker.refresh_account()
    clock[0] = SEND
    worker.tick()
    assert len(trader.placed) == 2
    session.expire_all()
    assert all(o.state == LiveState.FILLED for o in session.scalars(select(LiveOrderRow)))
    assert calls == [SEND - timedelta(seconds=15), SEND]
    assert not desk.account_refresh_pending


def test_order_within_limit_goes_out_without_asking_and_resends_only_with_same_key(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "337.5")
    trader = FakeTrader()
    trader.fail_next = 1
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    desk.tick(SEND)  # 한도 안의 주문은 묻지 않고 바로 보낸다. 결과를 모름: SENDING으로 남는다
    order = live_order(session)
    assert (order.state, order.amount, order.trade_date) == (
        LiveState.SENDING, Decimal("3.37"), TRADE,
    )  # fmt: skip
    desk.tick(SEND + timedelta(minutes=2))  # 멱등 유효 시간 안: 같은 키로 다시 → 접수 → 체결 확인
    assert [p.key for p in trader.placed] == [order.key, order.key]
    assert live_order(session).state == LiveState.FILLED
    desk.tick(SEND + timedelta(minutes=10))
    assert len(trader.placed) == 2  # 같은 모의 매수로 다시 주문하지 않는다


def test_order_over_limit_waits_for_approval(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "3000")  # 실제 주문 $30: 한 건 한도 $20을 넘는다
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    desk.tick(SEND)
    order = live_order(session)
    assert (order.state, order.amount) == (LiveState.WAITING_APPROVAL, Decimal("30.00"))
    assert trader.placed == []  # 사람이 승인하기 전에는 보내지 않는다

    approve(session, order.id, SEND)
    desk.tick(SEND)
    assert live_order(session).state == LiveState.FILLED


def test_unknown_result_is_never_resent_after_window(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "337.5")
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    trader.fail_next = 2
    desk.tick(SEND)
    assert live_order(session).state == LiveState.SENDING
    desk.tick(SEND + timedelta(minutes=30))  # 멱등 시간이 지났다: 다시 보내지 않고 찾기만
    assert len(trader.placed) == 1
    assert live_order(session).state == LiveState.UNKNOWN


def stalled_alerts(session: Session) -> list[str]:
    session.expire_all()
    rows = session.scalars(select(EventRow).where(EventRow.kind == "live_order")).all()
    return [r.data["state"] for r in rows if r.data and r.data.get("stalled")]


def test_long_disconnect_while_sending_alerts_once(
    make_session: Callable[[], Session], session: Session
) -> None:
    sim_buy(session, live_bot(session), "337.5")
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    trader.fail_next = 9  # 보낸 결과를 계속 모른다
    desk.tick(SEND)
    assert stalled_alerts(session) == []  # 잠깐 끊긴 것은 알리지 않는다
    desk.tick(SEND + timedelta(minutes=4))
    desk.tick(SEND + timedelta(minutes=5))
    assert stalled_alerts(session) == ["SENDING"]  # 오래 모르면 한 번만 알린다


def test_long_disconnect_while_checking_fill_alerts_once(
    make_session: Callable[[], Session], session: Session
) -> None:
    sim_buy(session, live_bot(session), "337.5")
    trader = PendingTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())
    desk.tick(SEND)
    assert live_order(session).state == LiveState.SENT

    def disconnected(order_id: str) -> AccountOrder:
        raise BrokerError("연결 끊김")

    trader.get_order = disconnected  # type: ignore[method-assign]
    for minutes in (1, 5, 7):
        desk.tick(SEND + timedelta(minutes=minutes))
    assert stalled_alerts(session) == ["SENT"]


def unknown_order(session: Session, *, side: str = "BUY", amount: str = "70") -> LiveOrderRow:
    order = LiveOrderRow(
        bot_id=None, symbol="VOO", side=side, signal_date=SIGNAL, trade_date=TRADE,
        amount=Decimal(amount), quantity=Decimal("0.1") if side == "SELL" else None,
        key="unknown", state=LiveState.UNKNOWN, source="test", sent_at=SEND,
        created_at=OPEN, updated_at=OPEN,
    )  # fmt: skip
    session.add(order)
    session.commit()
    return order


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_unknown_blocks_account_planning_approval_and_already_approved_orders(
    make_session: Callable[[], Session], session: Session, side: str
) -> None:
    bot = live_bot(session)
    sim = sim_buy(session, bot, "3000")
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())
    desk.plan(SEND)
    waiting = live_order(session)
    unknown = unknown_order(session, side=side)
    assert month_bought(session, TRADE) == (Decimal(70) if side == "BUY" else Decimal(0))
    with pytest.raises(Conflict, match="결과"):
        approve(session, waiting.id, SEND)
    session.rollback()
    # 이미 승인된 주문도 막고, 비상 중지를 껐다 켜도 UNKNOWN 차단을 풀지 못한다.
    waiting = session.get_one(LiveOrderRow, waiting.id)
    waiting.state = LiveState.APPROVED
    session.commit()
    set_halted(session, True, SEND)
    set_halted(session, False, SEND)
    desk.tick(SEND + timedelta(minutes=30))
    assert trader.placed == [] and trader.sold == []
    sim.status = "FILLED"
    session.commit()
    sim_buy(session, bot, "1000", TRADE)
    assert desk.plan(SEND + timedelta(days=3)) == []
    # 달이 바뀌고 원래 봇이 삭제된 주문이어도 차단은 남는다.
    assert desk.plan(datetime(2026, 11, 2, tzinfo=UTC)) == []
    assert overview(session).unknown_order_ids == [unknown.id]


def test_unknown_in_same_send_batch_blocks_later_orders(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "1000")
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())
    desk.plan(SEND)
    first = live_order(session)
    first.state, first.sent_at, first.source = LiveState.SENDING, SEND, "test"
    session.add(
        LiveOrderRow(
            bot_id=bot.id,
            symbol="QQQ",
            signal_date=SIGNAL,
            trade_date=TRADE,
            amount=Decimal(10),
            key="second",
            state=LiveState.APPROVED,
            created_at=OPEN,
            updated_at=OPEN,
        )
    )
    session.commit()
    desk.send_due(SEND + timedelta(minutes=30))
    session.expire_all()
    assert session.get_one(LiveOrderRow, first.id).state == LiveState.UNKNOWN
    assert month_bought(session, TRADE) == Decimal(20)
    assert trader.placed == []


def found_order(order_id: str, status: OrderStatus = OrderStatus.FILLED) -> AccountOrder:
    return AccountOrder(
        order_id, "VOO", "BUY", status, "USD", SEND,
        Decimal(70), Decimal("0.1"), Decimal(70),
    )  # fmt: skip


@pytest.mark.parametrize(
    "filled_amount, reserved", [(Decimal(12), Decimal(12)), (None, Decimal(70))]
)
def test_unknown_recovers_by_query_without_resending_and_retains_partial_fill_cost(
    make_session: Callable[[], Session],
    session: Session,
    filled_amount: Decimal | None,
    reserved: Decimal,
) -> None:
    unknown = unknown_order(session)
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())
    desk.tick(SEND + timedelta(minutes=30))  # 조회 지연: 모르는 동안은 그대로
    assert not desk.account_refresh_pending
    trader.orders["found"] = AccountOrder(
        "found", "VOO", "BUY", OrderStatus.CANCELED, "USD", SEND,
        Decimal(70), Decimal("0.02"), filled_amount,
    )  # fmt: skip
    desk.tick(SEND + timedelta(minutes=32))
    session.expire_all()
    assert session.get_one(LiveOrderRow, unknown.id).state == LiveState.CANCELED
    assert (
        month_bought(session, TRADE) == reserved
    )  # 체결 금액이 없으면 원래 금액을 보수적으로 예약
    assert overview(session).unknown_order_ids == []
    assert desk.account_refresh_pending
    assert trader.placed == []
    bot = live_bot(session)
    sim_buy(session, bot, "1000")
    desk.tick(SEND + timedelta(minutes=34))
    assert len(trader.placed) == 1  # 확인한 주문을 재전송하지 않고 새 주문은 이어간다


def test_manual_order_number_is_only_a_hint_until_broker_confirms(
    make_session: Callable[[], Session], session: Session
) -> None:
    order = unknown_order(session)
    trader = FakeTrader()
    trader.orders = {"a": found_order("a"), "b": found_order("b")}
    desk = LiveDesk(make_session, trader, WeekdayCalendar())
    desk.tick(SEND + timedelta(minutes=30))  # 동액 주문 두 개면 임의로 고르지 않는다
    assert live_order(session).state == LiveState.UNKNOWN
    resolve_unknown(session, order.id, SEND, broker_order_id="wrong")
    desk.tick(SEND + timedelta(minutes=32))
    assert live_order(session).state == LiveState.UNKNOWN
    resolve_unknown(session, order.id, SEND, broker_order_id="b")
    assert live_order(session).state == LiveState.UNKNOWN  # API만으로 차단을 풀지 않는다
    desk.tick(SEND + timedelta(minutes=34))
    assert (live_order(session).state, live_order(session).broker_order_id) == (
        LiveState.FILLED,
        "b",
    )
    assert trader.placed == []
    with pytest.raises(Conflict):
        resolve_unknown(session, order.id, SEND, broker_order_id=None)


def test_unknown_cannot_reuse_an_order_linked_to_another_record(
    make_session: Callable[[], Session], session: Session
) -> None:
    unknown = unknown_order(session)
    session.add(
        LiveOrderRow(
            symbol="VOO",
            signal_date=SIGNAL,
            trade_date=TRADE,
            amount=Decimal(70),
            key="linked",
            state=LiveState.FILLED,
            source="test",
            broker_order_id="used",
            created_at=OPEN,
            updated_at=OPEN,
        )
    )
    session.commit()
    trader = FakeTrader()
    trader.orders["used"] = found_order("used")
    LiveDesk(make_session, trader, WeekdayCalendar()).tick(SEND + timedelta(minutes=30))
    session.expire_all()
    assert session.get_one(LiveOrderRow, unknown.id).state == LiveState.UNKNOWN
    with pytest.raises(Conflict, match="다른 실제 주문"):
        resolve_unknown(session, unknown.id, SEND, broker_order_id="used")
    assert trader.placed == []


def test_old_unknown_remains_visible_and_manual_no_order_releases_reservation(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim = sim_buy(session, bot, "7000")
    order = unknown_order(session)
    order.bot_id, order.sim_order_id = bot.id, sim.id
    session.add_all(
        [
            LiveOrderRow(
                symbol="QQQ",
                signal_date=SIGNAL,
                trade_date=TRADE,
                amount=Decimal(1),
                key=f"later-{i}",
                state=LiveState.SKIPPED,
                created_at=OPEN,
                updated_at=OPEN,
            )
            for i in range(25)
        ]
    )
    session.commit()
    info = overview(session)
    assert info.unknown_order_ids == [order.id]
    assert info.orders[0].id == order.id
    resolve_unknown(session, order.id, SEND, broker_order_id=None)
    assert month_bought(session, TRADE) == 0
    assert overview(session).unknown_order_ids == []
    resolved = session.get_one(LiveOrderRow, order.id)
    assert (resolved.state, resolved.reason) == (LiveState.SKIPPED, "confirmed_not_placed")
    event = session.scalars(select(EventRow).where(EventRow.kind == "live_order")).one()
    assert event.data is not None and event.data["manual_resolution"] is True
    trader = FakeTrader()
    LiveDesk(make_session, trader, WeekdayCalendar()).tick(SEND + timedelta(minutes=30))
    assert trader.placed == []  # 미접수로 정리한 원래 주문은 다시 보내지 않는다


def test_small_shares_are_carried_until_they_reach_the_minimum(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    desk = LiveDesk(make_session, FakeTrader(), WeekdayCalendar())
    first_sim = sim_buy(session, bot, "50", signal=date(2026, 9, 30))  # $0.50: 모아 둔다
    desk.plan(SEND)
    first_sim.status = "FILLED"  # 모의 체결 뒤 다음 매수
    session.commit()
    sim_buy(session, bot, "50")  # 또 $0.50: 모은 몫과 합쳐 $1.00
    desk.plan(SEND)

    session.expire_all()
    first, second = session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id))
    assert (first.state, first.reason, first.carried_into) == ("SKIPPED", "carried", second.id)
    assert (second.state, second.amount) == (LiveState.APPROVED, Decimal("1.00"))


def test_account_with_fewer_shares_than_bot_bought_asks_before_new_orders(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    session.add(
        LiveOrderRow(
            bot_id=bot.id, symbol="VOO", signal_date=SIGNAL, trade_date=TRADE,
            amount=Decimal("3.37"), key="ql-x", state=LiveState.FILLED,
            filled_qty=Decimal("0.0048"), created_at=OPEN, updated_at=OPEN,
        )
    )  # fmt: skip
    session.commit()

    def snap(qty: str) -> AccountSnapshot:
        holding = Holding("VOO", "VOO", "USD", Decimal(qty), Decimal(1), Decimal(1), Decimal(1))
        return AccountSnapshot("test", Decimal(0), Decimal(0), [holding], [])

    later = OPEN + timedelta(hours=1)
    check_holdings(session, snap("0.0050"), later)  # 직접 산 주식이 섞여 더 많으면 맞음
    check_holdings(session, snap("0.0020"), later)  # 봇이 산 것보다 적다
    check_holdings(session, snap("0.0020"), later)  # 같은 부족은 한 번만 알린다
    session.commit()

    kinds = session.scalars(select(EventRow.kind).where(EventRow.kind == "live_reconcile")).all()
    assert len(kinds) == 1
    sim_buy(session, bot, "337.5")  # 부족이 있는 동안의 새 주문은 한도 안이어도 묻는다
    LiveDesk(make_session, FakeTrader(), WeekdayCalendar()).plan(SEND)
    session.expire_all()
    newest = session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id.desc())).first()
    assert newest is not None and newest.state == LiveState.WAITING_APPROVAL


def test_short_of_dollars_warns_early_then_skips(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    snapshot = AccountSnapshot("test", Decimal("2.86"), Decimal(0), [], [])
    save_snapshot(session, snapshot, OPEN - timedelta(hours=13))
    sim_buy(session, bot, "675")  # 실제 주문 $6.75
    trader = FakeTrader()
    trader.cash = Decimal("2.86")
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    desk.plan(OPEN - timedelta(hours=12))  # 만들 때 미리 알린다 (채울 시간을 준다)
    session.expire_all()
    warned = session.scalars(select(EventRow).where(EventRow.kind == "live_funds")).one()
    assert warned.data == {
        "needed": "6.75", "available": "2.86", "trade_date": "2026-10-02",
        "deadline": "10/02 22:35",
    }  # fmt: skip

    desk.tick(SEND)  # 그때도 모자라면 보내지 않고 이번 몫은 넘긴다
    order = live_order(session)
    assert (order.state, order.reason) == (LiveState.SKIPPED, "no_funds")
    assert trader.placed == []


def test_order_is_held_while_cash_cannot_be_checked(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "337.5")
    trader = FakeTrader()
    trader.cash_error = True
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    desk.tick(SEND)  # 달러를 확인하지 못하면 보내지 않고 기다린다
    assert (live_order(session).state, trader.placed) == (LiveState.APPROVED, [])

    trader.cash_error = False
    desk.tick(SEND + timedelta(minutes=1))  # 다시 확인되면 그때 보낸다
    assert live_order(session).state == LiveState.FILLED


def test_account_month_limit_cannot_be_approved_past(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)

    def filled(amount: str, key: str) -> None:
        session.add(
            LiveOrderRow(
                bot_id=bot.id, symbol="VOO", signal_date=SIGNAL, trade_date=TRADE,
                amount=Decimal(amount), key=key, state=LiveState.FILLED,
                filled_qty=Decimal(1), created_at=OPEN, updated_at=OPEN,
            )
        )  # fmt: skip
        session.commit()

    filled("60", "ql-a")
    first = sim_buy(session, bot, "3000")  # $30: 봇 한도는 넘지만 계좌 전체 $100 안이라 묻는다
    desk = LiveDesk(make_session, FakeTrader(), WeekdayCalendar())
    desk.plan(SEND)
    waiting = live_order_where(session, LiveState.WAITING_APPROVAL)

    filled("40", "ql-b")  # 그 사이 다른 주문이 늘어 계좌 합계가 $100이 됐다
    with pytest.raises(Conflict):
        approve(session, waiting.id, SEND)

    first.status = "FILLED"  # 모의 체결 뒤 다음 매수
    session.commit()
    sim_buy(session, bot, "1500", date(2026, 10, 2))  # $15: 건당 한도 안이어도 상한을 넘으면 넘긴다
    desk.plan(SEND)
    skipped = live_order_where(session, LiveState.SKIPPED)
    assert skipped.reason == "account_limit"


def live_order_where(session: Session, state: LiveState) -> LiveOrderRow:
    session.expire_all()
    return session.scalars(select(LiveOrderRow).where(LiveOrderRow.state == state)).one()


def test_ai_bot_sells_only_what_it_really_bought_without_asking(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = create_bot(
        session, name="AI 봇", symbol="TQQQ", strategy="ai_judge",
        params={}, initial_cash=Decimal(10_000), costs=CostModel(),
        limits=RiskLimits(), now=OPEN - timedelta(days=3),
    )  # fmt: skip
    bot.live_ratio, bot.live_since = Decimal("0.01"), OPEN - timedelta(days=2)
    upsert_instruments(
        session,
        [
            Instrument("TQQQ", "TQQQ", "NASDAQ", "ETF", "ACTIVE", "USD", Decimal(3)),
            Instrument("SOXL", "SOXL", "AMEX", "ETF", "ACTIVE", "USD", Decimal(3)),
        ],
        OPEN,
    )
    session.commit()
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    # 켜기 전부터 들고 있던 모의 보유를 파는 신호: 실제로는 없으니 넘긴다
    sim_buy(session, bot, None, date(2026, 9, 28), symbol="TQQQ", side="SELL").status = "FILLED"
    # 허용하지 않은 레버리지 ETF는 넘긴다
    sim_buy(session, bot, "1500", date(2026, 9, 29), symbol="SOXL").status = "FILLED"
    sim_buy(session, bot, "1500", symbol="TQQQ")  # 모의 매수 $1,500의 1/100 (한도 $20 안)
    desk.plan(SEND)
    session.expire_all()
    orders = list(session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id)))
    assert [(o.symbol, o.side, o.state, o.reason) for o in orders] == [
        ("TQQQ", "SELL", LiveState.SKIPPED, "nothing_held"),
        ("SOXL", "BUY", LiveState.SKIPPED, "leveraged"),
        ("TQQQ", "BUY", LiveState.APPROVED, None),
    ]
    assert orders[2].amount == Decimal("15.00")

    desk.tick(SEND)  # 사서 체결 (0.0048주)
    session.execute(update(SimOrderRow).values(status="FILLED"))  # 모의도 체결됐다
    # 모의 보유 2주 중 1/4(종가 $2,000에 $1,000어치)를 판다: 실제로 산 수량의 1/4
    session.add_all(
        [
            BotPositionRow(bot_id=bot.id, symbol="TQQQ", qty=Decimal(2), avg_cost=Decimal(1)),
            DailyBarRow(
                symbol="TQQQ", session_date=SIGNAL, open=Decimal(2000), high=Decimal(2000),
                low=Decimal(2000), close=Decimal(2000), volume=Decimal(1), source="test",
                fetched_at=OPEN,
            ),
        ]
    )  # fmt: skip
    session.commit()
    sim_buy(session, bot, "1000", TRADE, symbol="TQQQ", side="SELL")
    desk.plan(SEND)
    session.execute(update(SimOrderRow).values(status="FILLED"))
    session.commit()
    desk.tick(
        SEND + timedelta(days=3)
    )  # 월요일 장이 열리고 5분 뒤: 팔기는 한도를 보지 않고 바로 낸다
    assert [(s.symbol, s.quantity) for s in trader.sold] == [("TQQQ", Decimal("0.0012"))]
    assert live_position(session, bot.id, "TQQQ") == Decimal("0.0036")

    # 모의로 모두 판 신호(예산 없음)는 이 봇이 실제로 산 나머지를 모두 판다
    sim_buy(session, bot, None, date(2026, 10, 5), symbol="TQQQ", side="SELL")
    desk.tick(SEND + timedelta(days=4))
    assert [s.quantity for s in trader.sold] == [Decimal("0.0012"), Decimal("0.0036")]
    assert live_position(session, bot.id, "TQQQ") == 0


def test_ai_bot_sells_the_same_share_of_what_it_really_bought() -> None:
    """AI 봇의 일부 팔기: 모의 보유 2주 중 $100어치($200 종가, 1/4)를 팔면 실제로 산 수량도 1/4."""
    live = Decimal("0.02")
    assert partial_sell_qty(live, Decimal(2), Decimal(100), Decimal(200)) == Decimal("0.005")
    assert partial_sell_qty(live, Decimal(2), Decimal(1000), Decimal(200)) == live  # 넘치면 모두
    assert partial_sell_qty(live, Decimal(0), Decimal(100), Decimal(200)) == live  # 모르면 모두


def test_real_ledger_uses_average_cost_for_realized_profit() -> None:
    fills = [
        RealFill(1, "VOO", "BUY", Decimal(1), Decimal(100), "2026-09"),
        RealFill(1, "VOO", "BUY", Decimal(1), Decimal(120), "2026-10"),  # 평균 단가 $110
        RealFill(1, "VOO", "SELL", Decimal(1), Decimal(130), "2026-10"),  # 확정 +$20
    ]
    ledger = real_ledger(fills)
    assert ledger.bought == {"2026-09": Decimal(100), "2026-10": Decimal(120)}
    assert ledger.sold == {"2026-10": Decimal(130)}
    assert ledger.realized == {"2026-10": Decimal(20)}
    assert ledger.held == {"VOO": (Decimal(1), Decimal(110))}


def test_live_overview_adds_up_bought_sold_and_profit_of_real_orders(session: Session) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from trading_lab.application.live_admin import overview

    bot = live_bot(session)
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()

    def fill(key: str, side: str, qty: str, amount: str) -> LiveOrderRow:
        return LiveOrderRow(
            bot_id=bot.id, symbol="VOO", side=side, signal_date=today, trade_date=today,
            amount=Decimal(amount), key=key, state=LiveState.FILLED, filled_qty=Decimal(qty),
            filled_amount=Decimal(amount), created_at=OPEN, updated_at=OPEN,
        )  # fmt: skip

    session.add_all([fill("ql-a", "BUY", "1", "100"), fill("ql-b", "SELL", "0.5", "70")])
    holding = Holding("VOO", "VOO", "USD", Decimal("0.5"), Decimal(100), Decimal(120), Decimal(60))
    save_snapshot(session, AccountSnapshot("test", Decimal(0), Decimal(0), [holding], []), OPEN)
    session.commit()

    live = overview(session)
    assert (live.bought_this_month, live.sold_this_month) == (Decimal(100), Decimal(70))
    assert (live.realized_this_month, live.realized_total) == (Decimal(20), Decimal(20))
    assert (live.held_cost, live.held_value) == (Decimal(50), Decimal(60))  # 평가 손익 +$10
