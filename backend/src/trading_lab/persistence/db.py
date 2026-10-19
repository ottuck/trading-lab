from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from trading_lab.config import get_settings


def make_engine(url: str) -> Engine:
    # 단일 사용자 도구라 연결 수를 작게 둔다.
    return create_engine(url, pool_size=3, max_overflow=2, pool_pre_ping=True)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def get_session() -> Iterator[Session]:
    with sessionmaker(get_engine())() as session:
        yield session


def ping(session: Session) -> None:
    """DB에 연결되는지 본다 (안 되면 SQLAlchemyError)."""
    session.execute(text("SELECT 1"))
