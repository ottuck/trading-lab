"""환경변수 기반 설정. 로컬에서는 저장소 루트의 .env를 읽고, 컨테이너에서는 환경변수만 쓴다."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://quant:quant@localhost:5432/quant_lab"

    # 토스 키는 Worker만 사용한다 (project.md 3절 원칙 6).
    toss_client_id: SecretStr | None = None
    toss_client_secret: SecretStr | None = None

    worker_heartbeat_interval_s: float = 15.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
