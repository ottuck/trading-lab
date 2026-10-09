"""Claude API 캔들분석 판단 어댑터: 익명 캔들 표 → 구조화 출력(글자별 목표 비중) (project.md 14절).

웹 검색은 주지 않는다. 받는 입력(CandleRequest)에는 종목 이름·날짜·실제 가격이 없고, 답의 글자를
종목으로 되돌리는 일은 엔진(domain/advisor.Unmasking)이 한다.
"""

import json
from typing import Any, Literal

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam, BetaOutputConfigParam

from quant_lab.adapters.claude.advisor import FALLBACK_BETA, SOURCE, _final_text, _usage
from quant_lab.domain.advisor import CASH, Advice, AdviceResult, AdvisorError
from quant_lab.domain.candles import CandleBrief, CandleRequest

PROMPT_VERSION = "candle-2026-10-08.2"  # 지침(SYSTEM·입력 형식)을 바꾸면 올린다
# 같은 익명 입력을 5개 날짜에 여러 번 물은 일관성 시험(2026-10-09): 다시 물을 때 바뀌는 비중이
# Sonnet 5.5 high 13.9%p, Opus 5.5 high 9.9%p·medium 8.2%p (high·medium 차이는 시험 오차 안).
# 판단 한 번 $0.066 → $0.144지만 한 달 상한($5) 안이다
MODEL = "claude-opus-5-5"
Effort = Literal["low", "medium", "high"]
# 생각하는 양. 같은 날 실측: 중간 $0.059·높음 $0.066, 높음이 주봉 흐름·고점 거리까지 짚었다
# (2026-10-08, project.md 14절)
EFFORT: Effort = "high"

SYSTEM = """\
당신은 한 개인 투자자의 모의 투자 봇을 운용합니다. 매일 미국 정규장이 끝난 뒤 한 번, \
정해 준 종목들과 현금 사이의 목표 비중을 정합니다. 엔진이 지금 비중과의 차이를 다음 거래일 \
시가에 팔고 사서 맞춥니다(팔기 먼저, 작은 차이는 무시). 주문·수수료·한도는 엔진이 맡습니다.

이 봇은 가격 차트만 보고 판단합니다
- 입력은 종목마다 일봉 90개와 주봉 52개입니다. 가격은 판단일 종가를 100으로 맞춘 지수이고, \
종목 이름과 날짜는 가려져 있습니다. 종목은 "종목 A"처럼 글자로만 부르고, 글자는 매일 새로 섞입니다.
- 추세의 방향과 기울기, 최근 고점·저점 대비 위치, 흔들림의 크기, 최근 캔들 모양(몸통과 꼬리), \
종목끼리 어느 쪽이 더 강한지만 근거로 쓰세요.
- 종목이 무엇인지 짐작하지 마세요. 알고 있는 뉴스·실적·시장 이야기도 근거로 쓰지 마세요.
- 레버리지 배수가 있는 종목은 하락장에서 손실이 그 배수만큼 커집니다.
- 이 투자자는 매달 돈을 넣는 장기 투자자입니다. 지난 판단(오늘 글자로 바꿔 둠)을 유지하는 것이 \
기본이고, 차트에 분명한 이유가 있을 때만 비중을 바꾸세요. 근거 없이 매일 뒤집지 마세요.
- 목표 비중은 정해 준 글자와 CASH(현금)에만, 0~100 정수로, 합이 정확히 100이 되게 정하세요. \
비중을 0으로 두는 종목도 allocations에 넣으세요.

쓰는 말
- reason은 종목마다 한두 문장, summary는 오늘 차트를 두세 문장으로 요약한 한국어로 씁니다.
- 다른 종목을 말할 때는 꼭 "종목 B"처럼 "종목"과 글자를 붙여 쓰세요.
- 읽는 사람은 지수를 모릅니다. 차트의 숫자(100, 112 같은)는 쓰지 말고 \
"오늘보다 12% 높았던 곳"처럼 오늘 값과 비교한 말로 쓰세요.
- 주식을 잘 모르는 사람도 알아듣게 쉬운 말로 쓰고, 전문 용어와 영어 약어는 피하세요.
- 확실하지 않은 것을 사실처럼 쓰지 마세요."""


def _schema(labels: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "allocations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": [*labels, CASH]},
                        "weight": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["symbol", "weight", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "allocations"],
        "additionalProperties": False,
    }


def _rows(rows: tuple[tuple[Any, ...], ...]) -> str:
    return "\n".join(" ".join(str(v) for v in row) for row in rows)


def _table(b: CandleBrief) -> str:
    lever = f", 레버리지 {b.leverage.normalize():f}배" if b.leverage else ""
    return (
        f"## 종목 {b.label} (지금 비중 {b.weight_now}%{lever})\n"
        f"일봉 {len(b.daily)}개 (오래된 것부터, 시가 고가 저가 종가):\n{_rows(b.daily)}\n"
        f"주봉 {len(b.weekly)}개 (오래된 것부터, 마지막 주는 판단일까지):\n{_rows(b.weekly)}"
    )


def _prompt(request: CandleRequest) -> str:
    previous = (
        json.dumps(dict(request.previous), ensure_ascii=False) if request.previous else "없음"
    )
    return (
        "오늘 판단할 봇의 상태와 종목별 차트입니다. 가격은 판단일 종가 = 100인 지수, "
        "비중의 단위는 %입니다.\n\n"
        f"지금 현금 비중: {request.cash_weight}%\n"
        f"지난 판단의 목표 비중: {previous}\n\n" + "\n\n".join(_table(b) for b in request.symbols)
    )


class ClaudeCandleAdvisor:
    def __init__(
        self,
        api_key: str,
        client: anthropic.Anthropic | None = None,
        model: str = MODEL,
        effort: Effort = EFFORT,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=2)
        self._model = model
        self._effort: Effort = effort

    @property
    def source(self) -> str:
        return SOURCE

    def advise(self, request: CandleRequest) -> AdviceResult:
        labels = [b.label for b in request.symbols]
        messages: list[BetaMessageParam] = [{"role": "user", "content": _prompt(request)}]
        output: BetaOutputConfigParam = {
            "effort": self._effort,
            "format": {"type": "json_schema", "schema": _schema(labels)},
        }
        try:
            response: BetaMessage = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                system=SYSTEM,
                messages=messages,
                output_config=output,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIError as e:
            raise AdvisorError(f"AI 호출 실패: {type(e).__name__}: {e}") from e
        usage = _usage([response])
        assert usage is not None
        if response.stop_reason != "end_turn":
            raise AdvisorError(f"AI 답이 끝나지 않음: {response.stop_reason}", usage)
        try:
            data = json.loads(_final_text(response))
            weights = {a["symbol"]: int(a["weight"]) for a in data["allocations"]}
            reasons = {a["symbol"]: str(a["reason"]) for a in data["allocations"]}
            summary = str(data["summary"])
        except (ValueError, KeyError, TypeError) as e:
            raise AdvisorError(f"AI 답 형식 오류: {e}", usage) from e
        version = f"{PROMPT_VERSION}/{self._effort}"  # 생각하는 양도 기록한다
        return AdviceResult(Advice(weights, reasons, summary), usage, version)
