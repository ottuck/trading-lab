"""Worker 진입점: `python -m quant_lab.worker`.

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

from quant_lab import __version__
from quant_lab.adapters.heartbeat_ping import HeartbeatPinger
from quant_lab.adapters.market_calendar import get_calendar
from quant_lab.adapters.telegram import TelegramClient
from quant_lab.adapters.toss.client import TossClient
from quant_lab.application.market import MarketData, StoredMarket, TossMarket
from quant_lab.application.notify import EventNotifier
from quant_lab.config import Settings, get_settings
from quant_lab.persistence.bots import add_event
from quant_lab.persistence.db import get_engine
from quant_lab.persistence.heartbeat import record_heartbeat
from quant_lab.worker.loop import Worker, release_worker_lock, try_acquire_worker_lock

log = logging.getLogger("quant_lab.worker")


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
    return TossMarket(client, get_calendar())


def build_notifier(settings: Settings, make_session: Callable[[], Session]) -> EventNotifier | None:
    if settings.telegram_bot_token is None or not settings.telegram_chat_id:
        log.info("텔레그램 알림 꺼짐 (TELEGRAM_BOT_TOKEN/CHAT_ID 없음)")
        return None
    client = TelegramClient(
        settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id
    )
    notifier = EventNotifier(make_session, client.send)
    # worker_start·재시작 일시정지 이벤트보다 먼저 위치를 잡아 이번 시작 알림부터 보낸다.
    notifier.start()
    log.info("텔레그램 알림 켜짐")
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
    worker = Worker(make_session, market, get_calendar(), watchlist=watchlist)
    notifier = build_notifier(settings, make_session)
    with make_session() as session:
        add_event(
            session,
            datetime.now(UTC),
            "INFO",
            "worker_start",
            f"Worker 시작 ({worker_id}, v{__version__}, 시세 {settings.worker_market_source})",
        )
        session.commit()
    worker.recover_after_restart()
    pinger = HeartbeatPinger(settings.heartbeat_ping_url) if settings.heartbeat_ping_url else None
    log.info("외부 heartbeat %s", "켜짐" if pinger else "꺼짐 (HEARTBEAT_PING_URL 없음)")

    while not stop.is_set():
        try:
            with make_session() as session:
                record_heartbeat(session, worker_id, __version__, started_at, datetime.now(UTC))
            worker.tick()
            if notifier is not None:
                notifier.poll()
            # DB 기록·명령 처리까지 성공한 주기에만 외부로 생존 신호를 보낸다.
            if pinger is not None:
                pinger.maybe_ping()
        except SQLAlchemyError:
            # DB 오류 중에는 판단·주문을 만들지 않는다 (project.md 3절 원칙 5).
            log.exception("DB 오류, 다음 주기에 다시 시도")
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
