"""환경변수 기반 설정. 로컬에서는 저장소 루트의 .env를 읽고, 컨테이너에서는 환경변수만 쓴다."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://quant:quant@localhost:5432/quant_lab"

    # 토스 키는 Worker만 사용한다 (project.md 3절 원칙 6).
    toss_client_id: SecretStr | None = None
    toss_client_secret: SecretStr | None = None

    # 텔레그램 알림 (Worker만 사용). 둘 다 있어야 켜진다.
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # 외부 감시(Healthchecks.io 등) ping URL. Worker·PC가 멈추면 외부 서비스가 알린다.
    heartbeat_ping_url: str | None = None

    worker_heartbeat_interval_s: float = 15.0
    # stored: DB에 저장된 봉만 사용 (토스 호출 없음, 로컬 기본값). toss: 운영 서버.
    worker_market_source: Literal["stored", "toss"] = "stored"

    # 빌드된 프론트엔드 위치. 있으면 API 서버가 함께 제공한다.
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
