"""실제로 따라 사기 (실거래 R2): 승인 순서, 먼저 적고 보내기, 같은 키로만 다시, 모르면 멈추기."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application.live import LiveDesk, check_holdings, live_position
from quant_lab.application.live_admin import approve
from quant_lab.domain.broker import (
    AccountOrder,
    AccountSnapshot,
    AmountOrder,
    BrokerError,
    Holding,
    Instrument,
    OrderStatus,
    SellOrder,
)
from quant_lab.domain.live import LiveState, partial_sell_qty
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.persistence.bots import create_bot
from quant_lab.persistence.broker_account import save_snapshot
from quant_lab.persistence.market_info import upsert_instruments
from quant_lab.persistence.models import (
    BotRow,
    DecisionRow,
    EventRow,
    LiveOrderRow,
    RunRow,
    SimOrderRow,
)
from tests.fakes import WeekdayCalendar

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

    def available_cash(self) -> Decimal:
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
    """모의 판단이 만든 주문 (dry_run이 남기는 것과 같은 모양). 사고팔기 봇은 예산이 없다."""
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


def test_trading_bot_buys_a_hundredth_of_cash_and_sells_only_what_it_bought(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = create_bot(
        session, name="TQQQ 봇", symbol="TQQQ", strategy="sma_cross",
        params={"fast": 50, "slow": 200}, initial_cash=Decimal(10_000), costs=CostModel(),
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
    sim_buy(session, bot, None, date(2026, 9, 29), symbol="SOXL").status = "FILLED"
    sim_buy(session, bot, None, symbol="TQQQ")  # 현금 $10,000의 1/100로 산다 (TQQQ는 허용)
    desk.plan(SEND)
    session.expire_all()
    orders = list(session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id)))
    assert [(o.symbol, o.side, o.state, o.reason) for o in orders] == [
        ("TQQQ", "SELL", LiveState.SKIPPED, "nothing_held"),
        ("SOXL", "BUY", LiveState.SKIPPED, "leveraged"),
        ("TQQQ", "BUY", LiveState.APPROVED, None),
    ]
    assert orders[2].amount == Decimal("100.00")

    desk.tick(SEND)  # 사서 체결 (0.0048주)
    session.scalars(select(SimOrderRow).where(SimOrderRow.symbol == "TQQQ")).all()[
        -1
    ].status = "FILLED"
    session.commit()
    sim_buy(session, bot, None, TRADE, symbol="TQQQ", side="SELL")  # 다음 판단에서 팔 신호
    desk.plan(SEND)
    sell = session.scalars(select(LiveOrderRow).order_by(LiveOrderRow.id.desc())).first()
    assert sell is not None and sell.side == "SELL" and sell.quantity == Decimal("0.0048")
    desk.tick(SEND + timedelta(days=3))  # 월요일 장이 열리고 5분 뒤
    assert [(s.symbol, s.quantity) for s in trader.sold] == [("TQQQ", Decimal("0.0048"))]
    assert live_position(session, bot.id, "TQQQ") == 0  # 산 만큼 모두 팔았다


def test_ai_bot_sells_the_same_share_of_what_it_really_bought() -> None:
    """AI 봇의 일부 팔기: 모의 보유 2주 중 $100어치($200 종가, 1/4)를 팔면 실제로 산 수량도 1/4."""
    live = Decimal("0.02")
    assert partial_sell_qty(live, Decimal(2), Decimal(100), Decimal(200)) == Decimal("0.005")
    assert partial_sell_qty(live, Decimal(2), Decimal(1000), Decimal(200)) == live  # 넘치면 모두
    assert partial_sell_qty(live, Decimal(0), Decimal(100), Decimal(200)) == live  # 모르면 모두
