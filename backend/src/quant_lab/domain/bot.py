"""봇 상태와 화면 명령. Worker 프로세스의 생존과는 별개다 (project.md 4절)."""

from enum import StrEnum


class BotState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class CommandKind(StrEnum):
    START = "START"
    PAUSE = "PAUSE"
    STOP = "STOP"
    RUN_ONCE = "RUN_ONCE"


class InvalidTransitionError(ValueError):
    pass


def apply_command(state: BotState, command: CommandKind) -> BotState:
    """명령을 적용한 다음 상태. RUN_ONCE는 상태를 바꾸지 않는다."""
    match command:
        case CommandKind.START:
            if state is BotState.RUNNING:
                raise InvalidTransitionError("이미 실행 중입니다")
            return BotState.RUNNING
        case CommandKind.PAUSE:
            if state is not BotState.RUNNING:
                raise InvalidTransitionError(f"{state} 상태에서는 일시정지할 수 없습니다")
            return BotState.PAUSED
        case CommandKind.STOP:
            return BotState.STOPPED
        case CommandKind.RUN_ONCE:
            return state


def state_after_restart(state: BotState) -> BotState:
    """Worker 재시작 뒤에는 실행 중이던 봇을 일시정지로 둔다. 사람이 확인하고 재개한다."""
    return BotState.PAUSED if state is BotState.RUNNING else state
