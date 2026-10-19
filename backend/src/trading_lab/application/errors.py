"""서비스 오류. 메시지는 화면에 그대로 보여줘도 되는 문장이다.

API는 이 세 종류를 HTTP 상태(404·400·409)로 바꾸기만 한다 (api/main.py).
다른 UI나 CLI도 같은 오류를 쓴다.
"""


class AppError(Exception):
    pass


class NotFound(AppError):
    pass


class Invalid(AppError):
    pass


class Conflict(AppError):
    pass


class NoData(Invalid, ValueError):
    """계산에 쓸 일봉이 아직 없다. 화면에는 입력 오류(400)로 나간다.

    ValueError이기도 해서 "비교할 날이 없어요"로 바꿔 받는 기존 처리는 그대로 동작한다.
    """
