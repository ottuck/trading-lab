import pytest

from trading_lab.adapters.brokers import BrokerSetupError, connect_broker
from trading_lab.config import Settings


def test_unknown_broker_name_is_refused_with_choices() -> None:
    with pytest.raises(BrokerSetupError, match="toss"):
        connect_broker("nowhere", Settings(_env_file=None))


def test_missing_keys_are_reported() -> None:
    with pytest.raises(BrokerSetupError, match="TOSS_CLIENT_ID"):
        connect_broker("toss", Settings(_env_file=None, toss_client_id=None))
