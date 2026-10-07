"""Worker 생존 신호 (화면의 "프로그램 멈춤" 표시가 읽는다).

평가와 따로 정해진 주기마다 남긴다. 한 바퀴가 AI 판단처럼 오래 걸려도 살아 있게 보이도록.
대신 메인 루프가 stuck_after보다 오래 다음 바퀴를 시작하지 못하면(멈춤) 남기지 않아,
화면이 멈춘 Worker를 살아 있다고 보이지 않는다.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from quant_lab.persistence.heartbeat import record_heartbeat

log = logging.getLogger(__name__)


class HeartbeatThread(threading.Thread):
    def __init__(
        self,
        make_session: Callable[[], Session],
        worker_id: str,
        version: str,
        started_at: datetime,
        interval: float,
        stop: threading.Event,
        stuck_after: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(name="heartbeat", daemon=True)
        self.make_session = make_session
        self.worker_id, self.version, self.started_at = worker_id, version, started_at
        self.interval, self.stop, self.stuck_after, self.clock = interval, stop, stuck_after, clock
        self.loop_at = clock()

    def loop_started(self) -> None:
        """메인 루프가 한 바퀴를 시작할 때 부른다."""
        self.loop_at = self.clock()

    def beat(self) -> bool:
        idle = self.clock() - self.loop_at
        if idle > self.stuck_after:
            log.warning("메인 루프가 %.0f초째 멈춰 있어 생존 신호를 남기지 않아요", idle)
            return False
        try:
            with self.make_session() as session:
                record_heartbeat(
                    session, self.worker_id, self.version, self.started_at, datetime.now(UTC)
                )
        except SQLAlchemyError:
            log.warning("생존 신호를 남기지 못했어요 (DB 오류)")
            return False
        return True

    def run(self) -> None:
        while not self.stop.wait(self.interval):
            self.beat()
