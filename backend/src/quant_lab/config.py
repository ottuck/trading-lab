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

    # 텔레그램 알림 (Worker만 사용). 2026-10-02부터 기본으로 끈다 (project.md 6절):
    # 실거래가 없는 모의 투자에는 즉시 알림이 필요 없고, 소식은 앱의 기록에서 본다.
    # 다시 켜려면 TELEGRAM_ENABLED=true와 토큰·채팅 ID를 함께 둔다.
    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # 외부 감시(Healthchecks.io 등) ping URL. Worker·PC가 멈추면 외부 서비스가 알린다.
    heartbeat_ping_url: str | None = None

    # 매일 일봉을 갱신할 관심 종목 (백테스트용, 쉼표 구분). 봇 종목은 평가 때 따로 갱신된다.
    watchlist_symbols: str = "QQQ,VOO,QLD,TQQQ,SOXL,NVDA,GLD,MAGS,EWY,EWJ"

    worker_heartbeat_interval_s: float = 15.0
    # stored: DB에 저장된 봉만 사용 (토스 호출 없음, 로컬 기본값). toss: 운영 서버.
    worker_market_source: Literal["stored", "toss"] = "stored"

    # 포트폴리오 데모 (D2): 예시 시세만 있는 공개 데모. 서버 상태를 바꾸는 요청은 막고
    # 시험해 보기·평행세계 계산만 받는다. 토스·주문 키는 넣지 않는다.
    demo_mode: bool = False

    # Cloudflare Access (N7). 둘 다 있으면 Cloudflare를 거쳐 온 요청은 Access 토큰을 확인한다.
    cf_access_team: str | None = None  # <team>.cloudflareaccess.com의 <team>
    cf_access_aud: str | None = None  # Access 애플리케이션의 Audience(AUD) 태그

    # 빌드된 프론트엔드 위치. 있으면 API 서버가 함께 제공한다.
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
