"""실제로 따라 사기 (실거래 R2): 모의 매수 → 실제 주문 계획 → 승인 → 보내기 → 체결 확인.

판단은 모의(dry_run)가 하고, 여기서는 그 결과를 비율만큼 줄여 실제 계좌로 옮기기만 한다 (원칙 3).
증권사는 domain/broker.py의 Trader 규약으로만 안다. 실거래 스위치가 꺼져 있으면 Trader가 없고
아무 주문도 만들지 않는다.

중복 방지 (roadmap "실거래 트랙"):
- 모의 매수 1건에 실제 주문은 최대 하나 (live_orders.sim_order_id 유일).
- 보내기 전에 SENDING으로 먼저 적고(commit) 보낸다. 같은 판단은 늘 같은 키(order_key)다.
- 결과를 모르는 주문은 Trader.idempotency_window 안에서만 같은 키로 다시 보낸다.
  그 뒤에는 다시 보내지 않고 find_orders로 찾고, 못 찾으면 UNKNOWN으로 두고 사람에게 알린다.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.domain.bars import TradingCalendar
from quant_lab.domain.broker import (
    AmountOrder,
    BrokerError,
    OrderRejected,
    OrderStatus,
    Trader,
)
from quant_lab.domain.events import EventKind, LiveOrderData
from quant_lab.domain.live import (
    MIN_AMOUNT,
    SEND_DELAY_MINUTES,
    LiveLimits,
    LiveState,
    SkipReason,
    needs_approval,
    order_key,
    scaled_amount,
)
from quant_lab.persistence.bots import add_event
from quant_lab.persistence.market_info import leverage_of
from quant_lab.persistence.models import BotRow, LiveControlRow, LiveOrderRow, SimOrderRow

KST = ZoneInfo("Asia/Seoul")
RETRY_MARGIN = timedelta(minutes=1)  # 멱등 유효 시간이 끝나기 이만큼 전까지만 같은 키로 다시 보낸다
CHECK_INTERVAL = timedelta(minutes=1)  # 보낸 주문의 체결 확인 간격
COMMITTED = (LiveState.APPROVED, LiveState.SENDING, LiveState.SENT, LiveState.FILLED)

LIMITS = LiveLimits()

log = logging.getLogger(__name__)


def control(session: Session, now: datetime) -> LiveControlRow:
    row = session.get(LiveControlRow, 1, with_for_update=True)
    if row is None:
        row = LiveControlRow(id=1, halted=False, trader=None, updated_at=now)
        session.add(row)
        session.flush()
    return row


def live_event(
    session: Session, now: datetime, order: LiveOrderRow, level: str = "INFO", **extra: Any
) -> None:
    data = LiveOrderData(symbol=order.symbol, amount=str(order.amount), state=order.state)
    if order.reason:
        data["reason"] = order.reason
    if order.filled_qty is not None:
        data["filled_qty"] = str(order.filled_qty)
    data.update(extra)  # type: ignore[typeddict-item]
    message = f"실제 주문 {order.symbol} ${order.amount} {order.state} {order.reason or ''}"
    add_event(session, now, level, EventKind.LIVE_ORDER, message, bot_id=order.bot_id, data=data)


class LiveDesk:
    """Worker가 tick마다 부른다.

    trader가 없으면(실거래 스위치 꺼짐) 상태만 알리고 아무것도 하지 않는다.
    """

    def __init__(
        self,
        make_session: Callable[[], Session],
        trader: Trader | None,
        calendar: TradingCalendar,
        limits: LiveLimits = LIMITS,
    ) -> None:
        self.make_session = make_session
        self.trader = trader
        self.calendar = calendar
        self.limits = limits
        self._windows: dict[date, tuple[datetime, datetime] | None] = {}
        self._checked_at: dict[int, datetime] = {}

    def announce(self, now: datetime) -> None:
        """화면이 실거래 스위치 상태를 알 수 있게 Worker 시작 때 적는다."""
        with self.make_session() as session:
            row = control(session, now)
            row.trader = self.trader.source if self.trader else None
            row.updated_at = now
            session.commit()

    def tick(self, now: datetime) -> None:
        if self.trader is None:
            return
        self.plan(now)
        self.send_due(now)
        self.check_sent(now)

    # --- 1) 모의 매수 → 실제 주문 계획 ---

    def plan(self, now: datetime) -> list[LiveOrderRow]:
        """따라 사기를 켠 봇의 새 모의 매수마다 실제 주문을 하나 만든다."""
        made: list[LiveOrderRow] = []
        with self.make_session() as session:
            halted = control(session, now).halted
            rows = session.execute(
                select(SimOrderRow, BotRow)
                .join(BotRow, BotRow.id == SimOrderRow.bot_id)
                .outerjoin(LiveOrderRow, LiveOrderRow.sim_order_id == SimOrderRow.id)
                .where(
                    BotRow.live_ratio.is_not(None),
                    SimOrderRow.side == "BUY",
                    SimOrderRow.budget.is_not(None),
                    SimOrderRow.created_at >= BotRow.live_since,
                    LiveOrderRow.id.is_(None),
                )
                .order_by(SimOrderRow.id)
            ).all()
            for sim, bot in rows:
                assert sim.budget is not None and bot.live_ratio is not None
                order = LiveOrderRow(
                    bot_id=bot.id,
                    sim_order_id=sim.id,
                    symbol=sim.symbol,
                    signal_date=sim.signal_date,
                    trade_date=self._next_session(sim.signal_date),
                    amount=scaled_amount(sim.budget, bot.live_ratio),
                    key=order_key(bot.id, sim.symbol, sim.signal_date),
                    state=LiveState.APPROVED,
                    created_at=now,
                    updated_at=now,
                )
                auto = False
                leverage = leverage_of(session, sim.symbol)
                if leverage is not None and leverage > 1:
                    order.state, order.reason = LiveState.SKIPPED, SkipReason.LEVERAGED
                elif halted:
                    order.state, order.reason = LiveState.SKIPPED, SkipReason.HALTED
                else:
                    carried = self._carried(session, bot.id, sim.symbol)
                    total = order.amount + sum((c.amount for c in carried), Decimal(0))
                    if total < MIN_AMOUNT:
                        # 작은 몫은 버리지 않고 모아 둔다. 같은 종목 다음 주문에 더해 함께 산다.
                        order.state, order.reason = LiveState.SKIPPED, SkipReason.CARRIED
                    else:
                        order.amount = total
                        session.add(order)
                        session.flush()
                        for c in carried:
                            c.carried_into, c.updated_at = order.id, now
                        month = self._month_total(session, bot.id, order.trade_date)
                        if needs_approval(order.amount, month, bot.live_streak, self.limits):
                            order.state = LiveState.WAITING_APPROVAL
                        else:
                            auto = True
                session.add(order)
                session.flush()
                warn = order.reason in (SkipReason.HALTED, SkipReason.LEVERAGED)
                live_event(
                    session,
                    now,
                    order,
                    "WARN" if warn else "INFO",
                    **({"auto": True} if auto else {}),
                )
                made.append(order)
            session.commit()
        return made

    @staticmethod
    def _carried(session: Session, bot_id: int, symbol: str) -> list[LiveOrderRow]:
        """아직 더하지 않은, 작아서 모아 둔 몫."""
        return list(
            session.scalars(
                select(LiveOrderRow).where(
                    LiveOrderRow.bot_id == bot_id,
                    LiveOrderRow.symbol == symbol,
                    LiveOrderRow.reason == SkipReason.CARRIED,
                    LiveOrderRow.carried_into.is_(None),
                )
            )
        )

    def _next_session(self, signal_date: date) -> date:
        return self.calendar.sessions(
            signal_date + timedelta(days=1), signal_date + timedelta(days=10)
        )[0]

    @staticmethod
    def _month_total(session: Session, bot_id: int, trade_date: date) -> Decimal:
        start = trade_date.replace(day=1)
        total = session.scalar(
            select(func.coalesce(func.sum(LiveOrderRow.amount), 0)).where(
                LiveOrderRow.bot_id == bot_id,
                LiveOrderRow.state.in_(COMMITTED),
                LiveOrderRow.trade_date >= start,
            )
        )
        return Decimal(total or 0)

    # --- 2) 접수 시간에 보내기 ---

    def _window(self, day: date) -> tuple[datetime, datetime] | None:
        if day not in self._windows:
            assert self.trader is not None
            self._windows[day] = self.trader.order_window(day)
        return self._windows[day]

    def send_due(self, now: datetime) -> None:
        with self.make_session() as session:
            halted = control(session, now).halted
            ids = list(
                session.scalars(
                    select(LiveOrderRow.id)
                    .where(
                        LiveOrderRow.state.in_(
                            [LiveState.WAITING_APPROVAL, LiveState.APPROVED, LiveState.SENDING]
                        )
                    )
                    .order_by(LiveOrderRow.id)
                )
            )
        for order_id in ids:
            try:
                self._advance(order_id, now, halted)
            except BrokerError as exc:  # 접수 시간 조회 실패 등: 다음 tick에 다시
                log.warning("실제 주문 %s 처리 보류: %s", order_id, exc)

    def _advance(self, order_id: int, now: datetime, halted: bool) -> None:
        assert self.trader is not None
        with self.make_session() as session:
            order = session.get_one(LiveOrderRow, order_id, with_for_update=True)
            window = self._window(order.trade_date)
            if window is None:
                if order.state != LiveState.SENDING:
                    self._skip(session, order, SkipReason.NO_SESSION, now)
                return
            start, end = window
            if order.state == LiveState.SENDING:
                self._resend_or_resolve(session, order, now, end, halted)
                return
            if now >= end:  # 승인을 못 받았거나, 멈춰 있었거나, PC가 꺼져 있었다
                self._skip(session, order, SkipReason.HALTED if halted else SkipReason.MISSED, now)
                return
            if order.state != LiveState.APPROVED or halted:
                return
            if now < start + timedelta(minutes=SEND_DELAY_MINUTES):
                return
            # 보내기 전에 먼저 적는다. 여기서 Worker가 죽어도 다음 tick이 같은 키로 이어 간다.
            order.state, order.sent_at, order.source = LiveState.SENDING, now, self.trader.source
            order.updated_at = now
            session.commit()
            self._place(session, order, now)

    def _place(self, session: Session, order: LiveOrderRow, now: datetime) -> None:
        assert self.trader is not None
        request = AmountOrder(key=order.key, symbol=order.symbol, amount=order.amount)
        try:
            broker_id = self.trader.place_amount_buy(request)
        except OrderRejected as exc:
            order.state, order.reason, order.note = LiveState.REJECTED, exc.reason, str(exc)
            self._reset_streak(session, order)
            order.updated_at = now
            live_event(session, now, order, "WARN")
            session.commit()
            return
        except BrokerError as exc:
            # 결과를 모른다. SENDING으로 두고 다음 tick에 같은 키로 다시 보내거나 찾는다.
            order.note, order.updated_at = str(exc), now
            session.commit()
            log.warning("실제 주문 %s 결과 모름, 다시 확인: %s", order.id, exc)
            return
        order.state, order.broker_order_id, order.updated_at = LiveState.SENT, broker_id, now
        session.commit()

    def _resend_or_resolve(
        self, session: Session, order: LiveOrderRow, now: datetime, end: datetime, halted: bool
    ) -> None:
        assert self.trader is not None and order.sent_at is not None
        within = now - order.sent_at < self.trader.idempotency_window - RETRY_MARGIN
        if within and now < end and not halted:
            self._place(session, order, now)  # 같은 키라 이미 접수됐으면 같은 주문이 돌아온다
            return
        # 같은 키로 다시 보내면 새 주문이 될 수 있다. 다시 보내지 않고 찾는다.
        sent_day = order.sent_at.astimezone(KST).date()
        matches = [
            o
            for o in self.trader.find_orders(order.symbol, sent_day)
            if o.side == "BUY"
            and o.order_amount == order.amount
            and o.ordered_at >= order.sent_at - RETRY_MARGIN
        ]
        if len(matches) == 1:
            order.state, order.broker_order_id = LiveState.SENT, matches[0].order_id
        else:
            order.state = LiveState.UNKNOWN
            order.note = f"주문 조회로 {len(matches)}건을 찾음"
            self._reset_streak(session, order)
            live_event(session, now, order, "WARN")
        order.updated_at = now
        session.commit()

    def _skip(self, session: Session, order: LiveOrderRow, reason: str, now: datetime) -> None:
        order.state, order.reason, order.updated_at = LiveState.SKIPPED, reason, now
        level = "WARN" if reason in (SkipReason.MISSED, SkipReason.HALTED) else "INFO"
        live_event(session, now, order, level)
        session.commit()

    @staticmethod
    def _reset_streak(session: Session, order: LiveOrderRow) -> None:
        """문제가 생기면 그 봇은 다시 승인부터 (자동 끄기)."""
        bot = session.get(BotRow, order.bot_id) if order.bot_id else None
        if bot is not None:
            bot.live_streak = 0

    # --- 3) 체결 확인 ---

    def check_sent(self, now: datetime) -> None:
        assert self.trader is not None
        with self.make_session() as session:
            ids = list(
                session.scalars(select(LiveOrderRow.id).where(LiveOrderRow.state == LiveState.SENT))
            )
        for order_id in ids:
            last = self._checked_at.get(order_id)
            if last is not None and now - last < CHECK_INTERVAL:
                continue
            self._checked_at[order_id] = now
            with self.make_session() as session:
                order = session.get_one(LiveOrderRow, order_id, with_for_update=True)
                assert order.broker_order_id is not None
                try:
                    found = self.trader.get_order(order.broker_order_id)
                except BrokerError as exc:
                    log.warning("실제 주문 %s 체결 확인 보류: %s", order_id, exc)
                    continue
                if found.status in (OrderStatus.OPEN, OrderStatus.PARTIAL, OrderStatus.OTHER):
                    continue
                order.filled_qty, order.filled_amount = found.filled_quantity, found.filled_amount
                order.updated_at = now
                if found.status == OrderStatus.FILLED:
                    order.state = LiveState.FILLED
                    bot = session.get(BotRow, order.bot_id) if order.bot_id else None
                    if bot is not None:
                        bot.live_streak += 1
                    live_event(session, now, order)
                else:
                    order.state = (
                        LiveState.CANCELED
                        if found.status == OrderStatus.CANCELED
                        else LiveState.REJECTED
                    )
                    self._reset_streak(session, order)
                    live_event(session, now, order, "WARN")
                session.commit()
                self._checked_at.pop(order_id, None)
