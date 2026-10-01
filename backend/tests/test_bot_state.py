import pytest

from quant_lab.domain.bot import (
    BotState,
    CommandKind,
    InvalidTransitionError,
    apply_command,
    state_after_restart,
)


@pytest.mark.parametrize("state", [BotState.STOPPED, BotState.PAUSED, BotState.ERROR])
def test_start_from_non_running(state: BotState) -> None:
    assert apply_command(state, CommandKind.START) is BotState.RUNNING


def test_invalid_transitions() -> None:
    with pytest.raises(InvalidTransitionError):
        apply_command(BotState.RUNNING, CommandKind.START)
    with pytest.raises(InvalidTransitionError):
        apply_command(BotState.STOPPED, CommandKind.PAUSE)


def test_stop_and_run_once() -> None:
    assert apply_command(BotState.ERROR, CommandKind.STOP) is BotState.STOPPED
    assert apply_command(BotState.PAUSED, CommandKind.RUN_ONCE) is BotState.PAUSED


def test_restart_pauses_running_bot_only() -> None:
    assert state_after_restart(BotState.RUNNING) is BotState.PAUSED
    assert state_after_restart(BotState.STOPPED) is BotState.STOPPED
    assert state_after_restart(BotState.ERROR) is BotState.ERROR
