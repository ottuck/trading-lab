"""설정으로 증권사 연결을 고르는 조립 도우미.

Worker와 CLI는 증권사 이름만 넘기고 `Broker`·`Trader` 규약으로 받는다.
증권사를 바꾸거나 늘릴 때는 어댑터를 만들고 아래 BROKERS에 한 줄을 더한다.
"""

from collections.abc import Callable
from dataclasses import dataclass

from trading_lab.adapters.toss.client import TossClient
from trading_lab.adapters.toss.trader import TossTrader
from trading_lab.config import Settings
from trading_lab.domain.broker import Broker, Trader


class BrokerSetupError(Exception):
    """증권사를 고르지 못했다 (모르는 이름, 키 없음). 메시지는 그대로 보여 줄 수 있다."""


@dataclass(frozen=True, slots=True)
class BrokerSpec:
    connect: Callable[[Settings], Broker]
    make_trader: Callable[[Broker], Trader]


def _connect_toss(settings: Settings) -> Broker:
    if settings.toss_client_id is None or settings.toss_client_secret is None:
        raise BrokerSetupError("TOSS_CLIENT_ID, TOSS_CLIENT_SECRET가 설정되지 않았습니다")
    return TossClient(
        settings.toss_client_id.get_secret_value(), settings.toss_client_secret.get_secret_value()
    )


def _toss_trader(broker: Broker) -> Trader:
    if not isinstance(broker, TossClient):
        raise BrokerSetupError("토스 주문은 토스 연결로만 낼 수 있습니다")
    return TossTrader(broker)


BROKERS: dict[str, BrokerSpec] = {"toss": BrokerSpec(_connect_toss, _toss_trader)}
DEFAULT_BROKER = "toss"  # CLI가 쓰는 증권사 (Worker는 WORKER_MARKET_SOURCE로 고른다)


def _spec(name: str) -> BrokerSpec:
    try:
        return BROKERS[name]
    except KeyError:
        raise BrokerSetupError(
            f"모르는 증권사입니다: {name!r} (가능한 값: {', '.join(sorted(BROKERS))})"
        ) from None


def connect_broker(name: str, settings: Settings) -> Broker:
    """시세·계좌 읽기 연결."""
    return _spec(name).connect(settings)


def make_trader(name: str, broker: Broker) -> Trader:
    """주문 어댑터. 실거래 스위치가 켜졌을 때만 부른다."""
    return _spec(name).make_trader(broker)
