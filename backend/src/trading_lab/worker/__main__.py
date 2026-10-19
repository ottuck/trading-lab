"""Worker 진입점: `python -m trading_lab.worker`.

한 프로세스만 동작한다 (DB advisory lock). 토스 토큰도 이 프로세스 하나가 보유한다.
"""

import io
import logging
import signal
import socket
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from trading_lab import __version__
from trading_lab.adapters.claude.advisor import ClaudeAdvisor
from trading_lab.adapters.claude.candles import ClaudeCandleAdvisor
from trading_lab.adapters.heartbeat_ping import HeartbeatPinger
from trading_lab.adapters.market_calendar import get_calendar
from trading_lab.adapters.telegram import TelegramClient
from trading_lab.adapters.toss.client import TossClient
from trading_lab.adapters.toss.trader import TossTrader
from trading_lab.application import notify_settings
from trading_lab.application.ai_judge import AiConfig
from trading_lab.application.live import LiveDesk
from trading_lab.application.market import BrokerMarket, MarketData, StoredMarket
from trading_lab.application.notify import EventNotifier
from trading_lab.config import Settings, get_settings
from trading_lab.domain.events import EventKind
from trading_lab.persistence.bots import add_event
from trading_lab.persistence.db import get_engine
from trading_lab.persistence.worker_lock import release_worker_lock, try_acquire_worker_lock
from trading_lab.worker.heartbeat import HeartbeatThread
from trading_lab.worker.loop import Worker

log = logging.getLogger("trading_lab.worker")


def build_market(settings: Settings) -> MarketData:
    if settings.worker_market_source == "stored":
        log.info("시세 공급원: DB 저장분 (토스 호출 없음)")
        return StoredMarket()
    if settings.toss_client_id is None or settings.toss_client_secret is None:
        raise SystemExit("WORKER_MARKET_SOURCE=toss 인데 TOSS_CLIENT_ID/SECRET가 없습니다")
    log.info("시세 공급원: 토스 Open API")
    client = TossClient(
        settings.toss_client_id.get_secret_value(), settings.toss_client_secret.get_secret_value()
    )
    return BrokerMarket(client, get_calendar())


def build_notifier(settings: Settings, make_session: Callable[[], Session]) -> EventNotifier | None:
    """토큰이 있으면 만들고, 보낼지·무엇을 보낼지는 화면 설정(notify_settings)을 따른다."""
    available = settings.telegram_bot_token is not None and bool(settings.telegram_chat_id)
    with make_session() as session:
        notify_settings.announce(session, available, settings.telegram_enabled, datetime.now(UTC))
    if settings.telegram_bot_token is None or not settings.telegram_chat_id:
        log.info("텔레그램 알림 없음 (TELEGRAM_BOT_TOKEN/CHAT_ID 없음)")
        return None
    client = TelegramClient(
        settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id
    )
    notifier = EventNotifier(make_session, client.send)
    # worker_start·재시작 일시정지 이벤트보다 먼저 위치를 잡아 이번 시작 알림부터 보낸다.
    notifier.start()
    log.info("텔레그램 알림 준비됨 (켜기·범위는 화면 설정)")
    return notifier


def run(stop: threading.Event) -> None:
    settings = get_settings()
    engine = get_engine()
    make_session = sessionmaker(engine)
    worker_id = socket.gethostname()
    started_at = datetime.now(UTC)
    interval = settings.worker_heartbeat_interval_s

    # 잠금을 얻을 때까지 기다린다. 다른 Worker가 살아 있으면 그쪽이 계속 담당한다.
    lock_conn = engine.connect()
    while not try_acquire_worker_lock(lock_conn):
        log.warning("다른 Worker가 동작 중입니다. %.0f초 뒤 다시 시도합니다", interval)
        if stop.wait(interval):
            lock_conn.close()
            return

    log.info("worker 시작 id=%s version=%s", worker_id, __version__)
    market = build_market(settings)
    watchlist = [s.strip().upper() for s in settings.watchlist_symbols.split(",") if s.strip()]
    # 실시간 가격은 증권사 연결 모드에서만
    live = market if isinstance(market, BrokerMarket) else None
    # 실제 토스 계좌 읽기 (실거래 R1). 시세와 같은 클라이언트라 토큰도 하나다 (원칙 6).
    account = None
    if settings.toss_account_enabled and isinstance(market, BrokerMarket):
        account = market.broker.account_snapshot
        log.info("토스 계좌 읽기 켜짐 (1시간 주기·주문 변화 뒤, 조회만)")
    # 실거래 스위치 (실거래 R2). 꺼져 있으면 주문 어댑터를 만들지 않아 실제 주문 경로가 없다.
    trader = None
    if settings.live_trading:
        if not (isinstance(market, BrokerMarket) and isinstance(market.broker, TossClient)):
            raise SystemExit(
                "LIVE_TRADING=true 인데 토스 연결(WORKER_MARKET_SOURCE=toss)이 없습니다"
            )
        trader = TossTrader(market.broker)
        log.warning(
            "실거래 스위치 켜짐: 한도 안의 실제 주문은 자동으로, 넘는 주문은 승인 뒤에 냅니다"
        )
    desk = LiveDesk(make_session, trader, get_calendar())
    desk.announce(datetime.now(UTC))
    worker = Worker(
        make_session,
        market,
        get_calendar(),
        watchlist=watchlist,
        live=live,
        account=account,
        desk=desk,
        ai=AiConfig(
            ClaudeAdvisor(key.get_secret_value()) if (key := settings.anthropic_api_key) else None,
            settings.ai_monthly_budget,
            ClaudeCandleAdvisor(key.get_secret_value()) if key else None,
            settings.ai_candle_monthly_budget,
        ),
    )
    notifier = build_notifier(settings, make_session)
    with make_session() as session:
        add_event(
            session,
            datetime.now(UTC),
            "INFO",
            EventKind.WORKER_START,
            f"Worker 시작 ({worker_id}, v{__version__}, 시세 {settings.worker_market_source})",
        )
        session.commit()
    worker.recover_after_restart()
    pinger = HeartbeatPinger(settings.heartbeat_ping_url) if settings.heartbeat_ping_url else None
    log.info("외부 heartbeat %s", "켜짐" if pinger else "꺼짐 (HEARTBEAT_PING_URL 없음)")

    # 생존 신호는 평가와 따로 남긴다 (AI 판단처럼 긴 바퀴에도 "프로그램 멈춤"이 잘못 뜨지 않게)
    heart = HeartbeatThread(make_session, worker_id, __version__, started_at, interval, stop)
    heart.beat()
    heart.start()

    while not stop.is_set():
        heart.loop_started()
        try:
            worker.tick()
            if notifier is not None:
                notifier.poll()
            # DB 기록·명령 처리까지 성공한 주기에만 외부로 생존 신호를 보낸다.
            if pinger is not None:
                pinger.maybe_ping()
        except SQLAlchemyError:
            # DB 오류 중에는 판단·주문을 만들지 않는다 (project.md 3절 원칙 5).
            log.exception("DB 오류, 다음 주기에 다시 시도")
        except Exception:
            # 예상 못 한 오류로 Worker 전체가 죽지 않게 한다. 이번 주기의 외부 생존 신호는
            # 건너뛰므로 오류가 계속되면 heartbeat 감시가 알린다.
            log.exception("예상하지 못한 오류, 다음 주기에 다시 시도")
        stop.wait(interval)

    release_worker_lock(lock_conn)
    lock_conn.close()
    log.info("worker 종료")


def main() -> None:
    # Windows 콘솔(cp949)에서도 한글 로그가 깨지지 않게 한다.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run(stop)


if __name__ == "__main__":
    main()
