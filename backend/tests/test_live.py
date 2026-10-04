"""실제로 따라 사기 (실거래 R2): 승인 순서, 먼저 적고 보내기, 같은 키로만 다시, 모르면 멈추기."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application.live import LiveDesk, check_holdings
from quant_lab.application.live_admin import approve
from quant_lab.domain.broker import (
    AccountOrder,
    AccountSnapshot,
    AmountOrder,
    BrokerError,
    Holding,
    OrderStatus,
)
from quant_lab.domain.live import AUTO_AFTER, LiveState
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.persistence.bots import create_bot
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
        self.fail_next = 0
        self.orders: dict[str, AccountOrder] = {}

    def order_window(self, day: date) -> tuple[datetime, datetime] | None:
        return (OPEN, CLOSE_CUTOFF) if day == TRADE else None

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

    def get_order(self, order_id: str) -> AccountOrder:
        return self.orders[order_id]

    def find_orders(self, symbol: str, day: date) -> list[AccountOrder]:
        return [o for o in self.orders.values() if o.symbol == symbol]


@pytest.fixture
def make_session(engine: Engine, session: Session) -> Callable[[], Session]:
    return sessionmaker(engine)


def live_bot(session: Session, streak: int = 0) -> BotRow:
    bot = create_bot(
        session,
        name=f"나 카피 봇 {streak}",
        symbol="VOO",
        strategy="dip_saver",
        params={"deposit": 675},
        initial_cash=Decimal(675),
        costs=CostModel(),
        limits=RiskLimits(),
        now=OPEN - timedelta(days=3),
    )
    bot.live_ratio, bot.live_since, bot.live_streak = (
        Decimal("0.01"),
        OPEN - timedelta(days=2),
        streak,
    )
    session.flush()
    return bot


def sim_buy(session: Session, bot: BotRow, budget: str, signal: date = SIGNAL) -> SimOrderRow:
    """모의 판단이 만든 매수 주문 (dry_run이 남기는 것과 같은 모양)."""
    run = RunRow(id=uuid.uuid4(), bot_id=bot.id, trigger="SCHEDULED", started_at=OPEN, status="OK")
    session.add(run)
    session.flush()
    decision = DecisionRow(
        bot_id=bot.id, symbol="VOO", session_date=signal, mode="DRY_RUN", run_id=run.id,
        strategy={}, action="BUY", target_long=True, holding=False, reason="", indicators={},
        created_at=OPEN - timedelta(hours=12),
    )  # fmt: skip
    session.add(decision)
    session.flush()
    sim = SimOrderRow(
        bot_id=bot.id, symbol="VOO", decision_id=decision.id, side="BUY", status="PENDING",
        signal_date=signal, created_at=OPEN - timedelta(hours=12), budget=Decimal(budget),
    )  # fmt: skip
    session.add(sim)
    session.commit()
    return sim


def live_order(session: Session) -> LiveOrderRow:
    session.expire_all()
    return session.scalars(select(LiveOrderRow)).one()


def test_first_orders_wait_for_approval_and_resend_only_with_same_key(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session)
    sim_buy(session, bot, "337.5")
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    desk.tick(SEND)  # 처음 몇 번은 승인 없이는 보내지 않는다
    order = live_order(session)
    assert (order.state, order.amount, order.trade_date) == (
        LiveState.WAITING_APPROVAL, Decimal("3.37"), TRADE,
    )  # fmt: skip
    assert trader.placed == []

    approve(session, order.id, SEND)
    trader.fail_next = 1
    desk.tick(SEND)  # 보내다 결과를 모름: 먼저 적어 둔 SENDING으로 남는다
    assert live_order(session).state == LiveState.SENDING
    desk.tick(SEND + timedelta(minutes=2))  # 멱등 유효 시간 안: 같은 키로 다시 → 접수 → 체결 확인
    assert [p.key for p in trader.placed] == [order.key, order.key]
    assert live_order(session).state == LiveState.FILLED
    session.refresh(bot)
    assert bot.live_streak == 1
    desk.tick(SEND + timedelta(minutes=10))
    assert len(trader.placed) == 2  # 같은 모의 매수로 다시 주문하지 않는다


def test_unknown_result_is_never_resent_after_window_and_auto_after_streak(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session, streak=AUTO_AFTER)
    sim_buy(session, bot, "337.5")
    trader = FakeTrader()
    desk = LiveDesk(make_session, trader, WeekdayCalendar())

    trader.fail_next = 2
    desk.tick(SEND)  # 연속 성공이 쌓였으면 묻지 않고 바로 보낸다
    assert live_order(session).state == LiveState.SENDING
    desk.tick(SEND + timedelta(minutes=30))  # 멱등 시간이 지났다: 다시 보내지 않고 찾기만
    assert len(trader.placed) == 1
    order = live_order(session)
    assert order.state == LiveState.UNKNOWN
    session.refresh(bot)
    assert bot.live_streak == 0  # 다음 주문부터 다시 승인


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
    assert (second.state, second.amount) == (LiveState.WAITING_APPROVAL, Decimal("1.00"))


def test_account_with_fewer_shares_than_bot_bought_goes_back_to_approval(
    make_session: Callable[[], Session], session: Session
) -> None:
    bot = live_bot(session, streak=AUTO_AFTER)
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

    session.refresh(bot)
    assert bot.live_streak == 0  # 다시 승인부터
    kinds = session.scalars(select(EventRow.kind).where(EventRow.kind == "live_reconcile")).all()
    assert len(kinds) == 1
