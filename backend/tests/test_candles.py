"""캔들분석 AI 봇의 익명 입력: 이름·날짜·실제 가격을 가리고, 판단은 종목으로 되돌린다."""

import json
from decimal import Decimal

from quant_lab.application.demo_advisor import DemoCandleAdvisor
from quant_lab.domain.advisor import Unmasking, check_advice, make_request
from quant_lab.domain.candles import unmask_text
from tests.fakes import make_bars

HISTORIES = {
    "QQQ": make_bars("QQQ", [300 + i for i in range(300)]),
    "TQQQ": make_bars("TQQQ", [50 + i / 5 for i in range(300)]),
    "GLD": make_bars("GLD", [200 - i / 10 for i in range(300)]),
}


def test_masked_candles_hide_names_dates_and_prices() -> None:
    request = make_request(
        HISTORIES,
        cash=Decimal(1000),
        qtys={"QQQ": Decimal(1)},
        contributed=Decimal(1000),
        monthly_deposit=Decimal(500),
        leverage={"TQQQ": Decimal(3)},
        previous={"QQQ": 40, "OLD": 10, "CASH": 50},
        candles=True,
    )
    masked = request.candles
    assert masked is not None
    shown = json.dumps(masked.request.as_dict())
    assert not any(name in shown for name in ("QQQ", "TQQQ", "GLD", "OLD", "2026", "2027"))
    for b in masked.request.symbols:
        assert len(b.daily) == 90 and len(b.weekly) == 52
        assert b.daily[-1][3] == Decimal(100) == b.weekly[-1][3]  # 판단일 종가 = 100
    label = {s: k for k, s in masked.key.items()}
    assert masked.request.previous == {label["QQQ"]: 40, "CASH": 50}  # 지금 종목이 아닌 이름은 뺀다
    assert next(b for b in masked.request.symbols if b.label == label["TQQQ"]).leverage == 3
    # 같은 판단일은 같은 표 (다시 만들어도 같다)
    again = make_request(HISTORIES, Decimal(1000), {}, Decimal(1000), Decimal(500), candles=True)
    assert again.candles is not None and again.candles.key == masked.key
    json.dumps(request.as_dict())  # 대응표까지 그대로 기록할 수 있다

    # 데모 예시 판단도 익명 표만 받고, 답은 종목으로 되돌아온다
    result = Unmasking(DemoCandleAdvisor()).advise(request)
    advice = result.advice
    assert check_advice(advice, list(HISTORIES)) is None
    assert advice.weights["QQQ"] > 0 and advice.weights["TQQQ"] == 0  # 오르는 1배 종목만
    assert "QQQ를" in advice.summary and "종목 " not in advice.summary


def test_unmask_text_fixes_particles() -> None:
    key = {"A": "SOXL", "B": "QQQ"}
    text = "종목 A는 종목 B보다 강해요. 종목 B와 A는 비슷해요. 종목 Z, 종목 AB, AI는 그대로."
    assert unmask_text(text, key) == (
        "SOXL은 QQQ보다 강해요. QQQ와 SOXL은 비슷해요. 종목 Z, 종목 AB, AI는 그대로."
    )
