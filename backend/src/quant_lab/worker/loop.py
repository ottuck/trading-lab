"""Worker 루프: heartbeat → 명령 처리 → 예정된 평가."""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from quant_lab.application.dry_run import (
    EvaluationOutcome,
    Trigger,
    evaluate_bot,
    latest_completed_session,
)
from quant_lab.application.live import LiveDesk
from quant_lab.application.market import LiveSource, MarketData
from quant_lab.domain.bars import TradingCalendar
from quant_lab.domain.bot import (
    BotState,
    CommandKind,
    InvalidTransitionError,
    apply_command,
)
from quant_lab.domain.broker import AccountSnapshot, BrokerAccessError
from quant_lab.domain.events import CommandData, EventKind
from quant_lab.persistence.bars import latest_session_date
from quant_lab.persistence.bots import add_event, bot_weights, get_bot, set_bot_state
from quant_lab.persistence.broker_account import save_error, save_snapshot
from quant_lab.persistence.market_info import (
    upsert_exchange_rate,
    upsert_instruments,
    upsert_live_bars,
    upsert_quotes,
)
from quant_lab.persistence.models import BotRow, CommandRow

# 같은 DB에 Worker가 둘 뜨지 않게 하는 PostgreSQL advisory lock 키 ("QLAB")
WORKER_LOCK_KEY = 0x514C4142
WATCHLIST_CHECK_INTERVAL = timedelta(minutes=30)
QUOTE_INTERVAL = timedelta(seconds=30)
INSTRUMENT_INTERVAL = timedelta(days=1)
ACCOUNT_INTERVAL = timedelta(hours=1)
FX_INTERVAL = timedelta(hours=1)  # 화면 원화 환산용 (W1). 참고 값이라 자주 받을 필요 없다
ACCOUNT_ORDER_DAYS = 30  # 화면에 보여줄 최근 주문 기간
KST = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")

log = logging.getLogger(__name__)


def try_acquire_worker_lock(conn: Connection) -> bool:
    """세션 수준 잠금. conn이 열려 있는 동안 유지된다."""
    acquired = bool(conn.execute(select(func.pg_try_advisory_lock(WORKER_LOCK_KEY))).scalar())
    # 트랜잭션을 열어 둔 채 두지 않는다 (idle in transaction 타임아웃에 연결이 끊기지 않게).
    conn.commit()
    return acquired


def us_trading_hours(now: datetime) -> bool:
    """토스 미국 주식 거래 시간(데이마켓~애프터마켓): 뉴욕 기준 일요일 20:00 ~ 금요일 20:00.

    휴장일은 따로 거르지 않는다 (가격이 그대로일 뿐 해가 없다).
    """
    ny = now.astimezone(NEW_YORK)
    day, hour = ny.weekday(), ny.hour  # 월=0 … 일=6
    if day == 5:
        return False
    if day == 6:
        return hour >= 20
    if day == 4:
        return hour < 20
    return True


def release_worker_lock(conn: Connection) -> None:
    """연결 풀에 돌려줘도 세션 잠금은 남으므로 명시적으로 푼다."""
    conn.execute(select(func.pg_advisory_unlock(WORKER_LOCK_KEY)))
    conn.commit()


class Worker:
    def __init__(
        self,
        make_session: Callable[[], Session],
        market: MarketData,
        calendar: TradingCalendar,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        watchlist: Sequence[str] = (),
        live: LiveSource | None = None,
        account: Callable[[date], AccountSnapshot] | None = None,
        desk: LiveDesk | None = None,
    ) -> None:
        self.make_session = make_session
        self.market = market
        self.calendar = calendar
        self.now = now
        self.watchlist = list(watchlist)
        self.live = live
        self.account = account
        self.desk = desk
        self._account_at: datetime | None = None
        self._watchlist_checked_at: datetime | None = None
        self._watchlist_failing: set[str] = set()
        self._quotes_at: datetime | None = None
        self._instruments_at: datetime | None = None
        self._fx_at: datetime | None = None

    def recover_after_restart(self) -> None:
        """실행 중이던 봇은 그대로 이어서 돈다. 밀린 평가는 다음 tick에서 바로 처리된다.

        평가는 같은 봉을 두 번 판단하지 않고(유일 제약) 체결가는 봉 데이터로 정해지므로,
        재시작 시점과 상관없이 결과가 같다. 재개했다는 사실만 알린다.
        """
        now = self.now()
        with self.make_session() as session:
            for bot in session.scalars(select(BotRow).where(BotRow.state == BotState.RUNNING)):
                add_event(
                    session,
                    now,
                    "INFO",
                    EventKind.RESTART_RESUME,
                    "Worker 재시작 후 이어서 실행합니다.",
                    bot_id=bot.id,
                )
            session.commit()

    def tick(self) -> list[EvaluationOutcome]:
        outcomes = self.process_commands()
        outcomes += self.run_due_bots()
        self.sync_watchlist()
        self.refresh_live()
        self.refresh_account()
        self.trade_live()
        return outcomes

    def trade_live(self) -> None:
        """실제로 따라 사기 (실거래 R2). 실패해도 모의 판단과는 무관하다."""
        if self.desk is None:
            return
        try:
            self.desk.tick(self.now())
        except Exception:
            log.exception("실제 주문 처리 실패, 다음 주기에 다시")

    def refresh_account(self) -> None:
        """실제 증권사 계좌를 한 시간마다 읽어 저장한다 (실거래 R1, 읽기만).

        판단·모의 체결과 무관하다. 실패하면 마지막 값은 두고 실패 종류만 적는다 (알림 없음):
        access(인증·권한·허용 IP, 사람이 확인) | temporary(일시 장애, 다음 시간에 다시).
        """
        if self.account is None:
            return
        now = self.now()
        if self._account_at is not None and now - self._account_at < ACCOUNT_INTERVAL:
            return
        self._account_at = now
        since = now.astimezone(KST).date() - timedelta(days=ACCOUNT_ORDER_DAYS)
        try:
            snap = self.account(since)
        except Exception as exc:
            log.warning("계좌 읽기 실패: %s", exc)
            kind = "access" if isinstance(exc, BrokerAccessError) else "temporary"
            with self.make_session() as session:
                save_error(session, kind, now)
                session.commit()
            return
        with self.make_session() as session:
            save_snapshot(session, snap, now)
            session.commit()

    def refresh_live(self) -> None:
        """화면용 종목 정보(하루 한 번), 봇 종목 현재가·진행 중 일봉(거래 시간 중 30초마다),
        원/달러 환율(한 시간마다, W1).

        실패해도 판단·모의 체결과 무관하므로 로그만 남긴다 (알림 없음).
        """
        if self.live is None:
            return
        now = self.now()
        with self.make_session() as session:
            bot_symbols = sorted(
                {s for bot in session.scalars(select(BotRow)) for s in bot_weights(bot)}
            )
        try:
            if self._instruments_at is None or now - self._instruments_at >= INSTRUMENT_INTERVAL:
                self._instruments_at = now
                symbols = sorted(set(self.watchlist) | set(bot_symbols))
                if symbols:
                    infos = self.live.instruments(symbols)
                    with self.make_session() as session:
                        upsert_instruments(session, infos, now)
                        session.commit()
            if (
                bot_symbols
                and us_trading_hours(now)
                and (self._quotes_at is None or now - self._quotes_at >= QUOTE_INTERVAL)
            ):
                self._quotes_at = now
                quotes = self.live.quotes(bot_symbols)
                live_bars = self.live.live_bars(bot_symbols)
                with self.make_session() as session:
                    upsert_quotes(session, quotes, now)
                    upsert_live_bars(session, live_bars, now)
                    session.commit()
        except Exception as exc:
            log.warning("실시간 정보 갱신 실패: %s", exc)
        if self._fx_at is None or now - self._fx_at >= FX_INTERVAL:
            self._fx_at = now
            try:
                fx = self.live.exchange_rate("USD", "KRW")
                with self.make_session() as session:
                    upsert_exchange_rate(session, fx, self.live.source, now)
                    session.commit()
            except Exception as exc:
                log.warning("환율 갱신 실패: %s", exc)

    def sync_watchlist(self) -> list[str]:
        """관심 종목 일봉을 최신 완료 거래일까지 맞춘다 (백테스트용). 30분에 한 번만 확인한다.

        봇 평가와 독립적이며, 실패해도 경고만 남기고 판단·모의 체결에는 영향이 없다.
        """
        now = self.now()
        if not self.watchlist or (
            self._watchlist_checked_at is not None
            and now - self._watchlist_checked_at < WATCHLIST_CHECK_INTERVAL
        ):
            return []
        self._watchlist_checked_at = now
        try:
            target = latest_completed_session(self.calendar, now)
        except Exception:
            return []
        synced: list[str] = []
        with self.make_session() as session:
            for symbol in self.watchlist:
                latest = latest_session_date(session, symbol)
                if latest is not None and latest >= target:
                    continue
                try:
                    result = self.market.refresh(session, symbol, now)
                except Exception as exc:
                    session.rollback()
                    # 같은 종목이 계속 실패하면 경고(알림)는 처음 한 번만 남긴다.
                    level = "INFO" if symbol in self._watchlist_failing else "WARN"
                    self._watchlist_failing.add(symbol)
                    add_event(
                        session,
                        now,
                        level,
                        EventKind.WATCHLIST_SYNC,
                        f"{symbol} 일봉 갱신 실패: {exc}",
                    )
                    session.commit()
                    continue
                self._watchlist_failing.discard(symbol)
                if result is not None:
                    synced.append(f"{symbol}+{result.saved}")
        if synced:
            with self.make_session() as session:
                add_event(
                    session,
                    now,
                    "INFO",
                    EventKind.WATCHLIST_SYNC,
                    f"관심 종목 일봉 갱신 ({target}): {', '.join(synced)}",
                )
                session.commit()
        return synced

    def process_commands(self) -> list[EvaluationOutcome]:
        outcomes: list[EvaluationOutcome] = []
        with self.make_session() as session:
            ids = list(
                session.scalars(
                    select(CommandRow.id)
                    .where(CommandRow.processed_at.is_(None))
                    .order_by(CommandRow.created_at, CommandRow.id)
                )
            )
        for command_id in ids:
            with self.make_session() as session:
                outcome = self._process_command(session, command_id)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes

    def _process_command(self, session: Session, command_id: int) -> EvaluationOutcome | None:
        now = self.now()
        cmd = session.get_one(CommandRow, command_id, with_for_update=True)
        if cmd.processed_at is not None:
            return None
        kind = CommandKind(cmd.kind)
        # 처리 표시를 먼저 저장해서, 처리 중 Worker가 죽어도 같은 명령을 두 번 실행하지 않게 한다.
        cmd.processed_at = now
        bot = get_bot(session, cmd.bot_id, for_update=True)
        if bot is None:
            cmd.result, cmd.detail = "REJECTED", "봇이 없습니다"
            session.commit()
            return None

        if kind is CommandKind.RUN_ONCE:
            cmd.result = "OK"
            session.commit()
            outcome = evaluate_bot(
                session,
                cmd.bot_id,
                market=self.market,
                calendar=self.calendar,
                now=now,
                trigger=Trigger.MANUAL,
            )
            cmd.detail = outcome.detail
            session.commit()
            return outcome

        try:
            new = apply_command(BotState(bot.state), kind)
        except InvalidTransitionError as exc:
            cmd.result, cmd.detail = "REJECTED", str(exc)
        else:
            set_bot_state(session, bot, new, None, now)
            if kind is CommandKind.START:
                bot.next_evaluation_at = (
                    now  # 바로 한 번 평가한다 (이미 판단한 봉이면 아무것도 안 함)
                )
            cmd.result, cmd.detail = "OK", f"{kind} → {new}"
            add_event(
                session,
                now,
                "INFO",
                EventKind.COMMAND,
                f"{kind}: {new}",
                bot_id=bot.id,
                data=CommandData(command=kind, state=new),
            )
        session.commit()
        return None

    def run_due_bots(self) -> list[EvaluationOutcome]:
        now = self.now()
        with self.make_session() as session:
            due = list(
                session.scalars(
                    select(BotRow.id).where(
                        BotRow.state == BotState.RUNNING,
                        (BotRow.next_evaluation_at.is_(None)) | (BotRow.next_evaluation_at <= now),
                    )
                )
            )
        outcomes = []
        for bot_id in due:
            with self.make_session() as session:
                outcome = evaluate_bot(
                    session,
                    bot_id,
                    market=self.market,
                    calendar=self.calendar,
                    now=now,
                    trigger=Trigger.SCHEDULED,
                )
                log.info("평가 bot=%s %s %s", bot_id, outcome.status, outcome.detail)
                outcomes.append(outcome)
        return outcomes
