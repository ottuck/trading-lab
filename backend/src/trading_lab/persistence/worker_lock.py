"""Worker가 하나만 동작하게 하는 PostgreSQL 세션 잠금."""

from sqlalchemy import Connection, func, select

# 같은 DB에 Worker가 둘 뜨지 않게 하는 advisory lock 키 ("QLAB")
WORKER_LOCK_KEY = 0x514C4142


def try_acquire_worker_lock(conn: Connection) -> bool:
    """세션 수준 잠금. conn이 열려 있는 동안 유지된다."""
    acquired = bool(conn.execute(select(func.pg_try_advisory_lock(WORKER_LOCK_KEY))).scalar())
    # 트랜잭션을 열어 둔 채 두지 않는다 (idle in transaction 타임아웃에 연결이 끊기지 않게).
    conn.commit()
    return acquired


def release_worker_lock(conn: Connection) -> None:
    """연결 풀에 돌려줘도 세션 잠금은 남으므로 명시적으로 푼다."""
    conn.execute(select(func.pg_advisory_unlock(WORKER_LOCK_KEY)))
    conn.commit()
