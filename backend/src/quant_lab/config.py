"""환경변수 기반 설정. 로컬에서는 저장소 루트의 .env를 읽고, 컨테이너에서는 환경변수만 쓴다."""

from decimal import Decimal
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

    # 텔레그램 알림 (Worker만 사용). 토큰·채팅 ID가 있으면 준비되고, 켜기·받을 알림은
    # 화면 설정(notify_settings)에서 고른다 (2026-10-04~).
    # TELEGRAM_ENABLED는 처음 시작 값으로만 쓴다.
    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # 외부 감시(Healthchecks.io 등) ping URL. Worker·PC가 멈추면 외부 서비스가 알린다.
    heartbeat_ping_url: str | None = None

    # 매일 일봉을 갱신할 관심 종목 (백테스트용, 쉼표 구분). 봇 종목은 평가 때 따로 갱신된다.
    watchlist_symbols: str = "QQQ,VOO,QLD,TQQQ,SOXL,NVDA,GLD,MAGS,EWY,EWJ"

    # 실제 계좌 읽기 (R1). Worker가 5분마다, 봇 주문 변화 뒤에도 잔고·보유·최근 주문을 읽는다.
    # WORKER_MARKET_SOURCE=toss일 때만 동작한다. 주문은 내지 않는다.
    toss_account_enabled: bool = False

    # 실거래 스위치 (실거래 R2). 켜야만 Worker가 주문 어댑터를 만들고 실제 주문을 낸다.
    # 봇마다 "실제로 따라 사기"도 켜야 하고, 한도를 넘는 주문은 화면에서 승인해야 나간다.
    live_trading: bool = False

    # AI 봇 (마일스톤 4). Claude API 키는 Worker만 쓴다. 없으면 AI 봇은 판단하지 않는다.
    anthropic_api_key: SecretStr | None = None
    ai_monthly_budget: Decimal = Decimal(
        15
    )  # 시장분석 AI 봇의 한 달 비용 상한 (USD). 넘으면 그달은 판단하지 않음
    ai_candle_monthly_budget: Decimal = Decimal(5)  # 캔들분석 AI 봇의 한 달 비용 상한 (따로 센다)

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
