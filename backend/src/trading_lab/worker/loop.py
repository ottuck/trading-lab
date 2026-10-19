"""Worker 루프: heartbeat → 명령 처리 → 예정된 평가."""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from trading_lab.application.ai_judge import AiConfig
from trading_lab.application.dry_run import (
    EvaluationOutcome,
    Trigger,
    evaluate_bot,
    latest_completed_session,
)
from trading_lab.application.live import LiveDesk, check_holdings
from trading_lab.application.market import LiveSource, MarketData
from trading_lab.domain.bars import TradingCalendar
from trading_lab.domain.bot import (
    BotState,
    CommandKind,
    InvalidTransitionError,
    apply_command,
)
from trading_lab.domain.broker import AccountSnapshot, BrokerAccessError
from trading_lab.domain.events import CommandData, EventKind, RestartData
from trading_lab.persistence.bars import latest_session_date
from trading_lab.persistence.bots import add_event, bot_weights, get_bot, set_bot_state
from trading_lab.persistence.broker_account import save_error, save_snapshot
from trading_lab.persistence.market_info import (
    upsert_exchange_rate,
    upsert_instruments,
    upsert_live_bars,
    upsert_quotes,
)
from trading_lab.persistence.models import BotRow, CommandRow, InstrumentRow

# 같은 DB에 Worker가 둘 뜨지 않게 하는 PostgreSQL advisory lock 키 ("QLAB")
WORKER_LOCK_KEY = 0x514C4142
WATCHLIST_CHECK_INTERVAL = timedelta(minutes=30)
QUOTE_INTERVAL = timedelta(seconds=30)
INSTRUMENT_INTERVAL = timedelta(days=1)
ACCOUNT_INTERVAL = timedelta(hours=1)
ACCOUNT_RETRY_INTERVAL = timedelta(minutes=1)
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
        ai: AiConfig | None = None,
    ) -> None:
        self.make_session = make_session
        self.market = market
        self.calendar = calendar
        self.now = now
        self.watchlist = list(watchlist)
        self.live = live
        self.account = account
        self.desk = desk
        self.ai = ai  # AI 봇 판단 (마일스톤 4). 없으면 AI 봇은 판단하지 않고 그대로 둔다
        self._account_at: datetime | None = None
        self._account_failed = False
        self._watchlist_checked_at: datetime | None = None
        self._watchlist_failing: set[str] = set()
        self._quotes_at: datetime | None = None
        self._instruments_at: datetime | None = None
        self._instruments_asked: set[str] = set()
        self._fx_at: datetime | None = None

    def recover_after_restart(self) -> None:
        """실행 중이던 봇은 그대로 이어서 돈다. 밀린 평가는 다음 tick에서 바로 처리된다.

        평가는 같은 봉을 두 번 판단하지 않고(유일 제약) 체결가는 봉 데이터로 정해지므로,
        재시작 시점과 상관없이 결과가 같다. 재개했다는 사실만 기록한다. 배포로 다시 켜질 때마다
        알리면 시끄러우므로 텔레그램은 멈춘 동안 판단할 때가 지난 봇만 알린다.
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
                    data=RestartData(
                        overdue=bot.next_evaluation_at is None or bot.next_evaluation_at <= now
                    ),
                )
            session.commit()

    def tick(self) -> list[EvaluationOutcome]:
        outcomes = self.process_commands()
        outcomes += self.run_due_bots()
        self.sync_watchlist()
        self.refresh_live()
        self.refresh_account()
        self.trade_live()
        if self.desk is not None and self.desk.account_refresh_pending:
            self.refresh_account(force=True)
        return outcomes

    def trade_live(self) -> None:
        """실제로 따라 사기 (실거래 R2). 실패해도 모의 판단과는 무관하다."""
        if self.desk is None:
            return
        try:
            self.desk.tick(self.now())
        except Exception:
            log.exception("실제 주문 처리 실패, 다음 주기에 다시")

    def refresh_account(self, *, force: bool = False) -> None:
        """실제 계좌를 1시간마다, 주문 접수·체결 확인 뒤에도 읽어 저장한다.

        판단·모의 체결과 무관하다. 실패하면 마지막 값은 두고 실패 종류만 적는다 (알림 없음):
        access(인증·권한·허용 IP, 사람이 확인) | temporary(일시 장애).
        주문 뒤 조회가 실패하면 요청을 남겨 1분 뒤 재시도한다. 일반 조회 실패는 1시간 뒤 재시도한다.
        """
        if self.account is None:
            return
        now = self.now()
        if self._account_at is not None:
            elapsed = now - self._account_at
            if not force and elapsed < ACCOUNT_INTERVAL:
                return
            if self._account_failed and elapsed < ACCOUNT_RETRY_INTERVAL:
                return
        self._account_at = now
        since = now.astimezone(KST).date() - timedelta(days=ACCOUNT_ORDER_DAYS)
        try:
            snap = self.account(since)
        except Exception as exc:
            self._account_failed = True
            log.warning("계좌 읽기 실패: %s", exc)
            kind = "access" if isinstance(exc, BrokerAccessError) else "temporary"
            with self.make_session() as session:
                save_error(session, kind, now)
                session.commit()
            return
        with self.make_session() as session:
            save_snapshot(session, snap, now)
            check_holdings(session, snap, now)  # 실제 계좌 대조 (실거래 R2)
            session.commit()
        self._account_failed = False
        if self.desk is not None:
            self.desk.account_refresh_pending = False

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
            known = set(
                session.scalars(
                    select(InstrumentRow.symbol).where(InstrumentRow.symbol.in_(bot_symbols))
                )
            )
        try:
            # 하루에 한 번 받되, 새 봇의 종목처럼 정보가 아직 없는 종목은 바로 받는다.
            # 토스가 모르는 종목을 15초마다 되묻지 않게, 한 번 물어본 종목은 다음 갱신까지 둔다.
            unknown = [
                s for s in bot_symbols if s not in known and s not in self._instruments_asked
            ]
            if (
                unknown
                or self._instruments_at is None
                or now - self._instruments_at >= INSTRUMENT_INTERVAL
            ):
                self._instruments_at = now
                symbols = sorted(set(self.watchlist) | set(bot_symbols))
                self._instruments_asked = set(symbols)
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
            log.warning("관심 종목 기준 거래일 계산 실패", exc_info=True)
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
        # 처리 표시를 먼저 저장해서, 처리 중 Worker가 죽어도 같은 명령을 두 번 실행하지 않게 한다.
        cmd.processed_at = now
        try:
            kind = CommandKind(cmd.kind)
        except ValueError:
            # 알 수 없는 명령이 남아 있으면 매 주기 같은 곳에서 멈추므로 거절하고 넘어간다.
            cmd.result, cmd.detail = "REJECTED", f"알 수 없는 명령입니다: {cmd.kind}"
            session.commit()
            return None
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
                ai=self.ai,
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
                    ai=self.ai,
                )
                log.info("평가 bot=%s %s %s", bot_id, outcome.status, outcome.detail)
                outcomes.append(outcome)
        return outcomes
