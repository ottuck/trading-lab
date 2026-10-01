"""Worker 진입점: `python -m quant_lab.worker`.

Phase 1에서는 heartbeat만 기록한다. 평가 루프는 Phase 3에서 추가한다.
"""

import io
import logging
import signal
import socket
import sys
import threading
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from quant_lab import __version__
from quant_lab.config import get_settings
from quant_lab.persistence.db import get_engine
from quant_lab.persistence.heartbeat import record_heartbeat

log = logging.getLogger("quant_lab.worker")


def run(stop: threading.Event) -> None:
    settings = get_settings()
    make_session = sessionmaker(get_engine())
    worker_id = socket.gethostname()
    started_at = datetime.now(UTC)
    log.info("worker 시작 id=%s version=%s", worker_id, __version__)

    while not stop.is_set():
        try:
            with make_session() as session:
                record_heartbeat(session, worker_id, __version__, started_at, datetime.now(UTC))
        except SQLAlchemyError:
            # DB가 없으면 아무것도 하지 않고 다시 시도한다 (project.md 3절 원칙 5).
            log.exception("heartbeat 기록 실패")
        stop.wait(settings.worker_heartbeat_interval_s)

    log.info("worker 종료")


def main() -> None:
    # Windows 콘솔(cp949)에서도 한글 로그가 깨지지 않게 한다.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run(stop)


if __name__ == "__main__":
    main()
