"""AI 판단 (마일스톤 4 A1): 입력 요약, 응답 해석, 규칙에 맞지 않는 답은 판단하지 않기."""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from quant_lab.adapters.claude.advisor import ClaudeAdvisor
from quant_lab.application.ai_judge import judge
from quant_lab.domain.advisor import (
    Advice,
    AdviceRequest,
    AdviceResult,
    AdviceUsage,
    JudgmentStatus,
    make_request,
)
from tests.fakes import make_bars


def _request() -> AdviceRequest:
    histories = {
        "QQQ": make_bars("QQQ", [100 + i for i in range(260)]),
        "GLD": make_bars("GLD", [200 - i / 10 for i in range(260)]),
    }
    return make_request(
        histories,
        cash=Decimal(1000),
        qtys={"QQQ": Decimal(10)},
        contributed=Decimal(4000),
        monthly_deposit=Decimal(675),
    )


def test_request_summarizes_each_symbol_from_closes() -> None:
    req = _request()
    qqq, gld = req.symbols
    assert req.equity == Decimal(1000) + 10 * Decimal(359)
    assert qqq.close == 359 and qqq.vs_high == 0  # 계속 올라 지금이 최고가
    assert qqq.vs_sma200 is not None and qqq.vs_sma200 > 0
    assert gld.vs_high < 0 and gld.return_12m is not None and gld.return_12m < 0
    assert qqq.weight_now + gld.weight_now + req.cash_weight == Decimal("100.0")
    json.dumps(req.as_dict())  # 그대로 기록할 수 있다


def _message(
    content: list[dict[str, Any]], stop: str = "end_turn", searches: int = 0
) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 100_000,
                "output_tokens": 10_000,
                "server_tool_use": {"web_search_requests": searches, "web_fetch_requests": 0},
            },
        }
    )


class FakeClient:
    def __init__(self, *replies: BetaMessage | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> BetaMessage:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


ANSWER = {
    "summary": "금리 걱정이 줄었어요.",
    "allocations": [
        {"symbol": "QQQ", "weight": 60, "reason": "실적이 좋아요."},
        {"symbol": "GLD", "weight": 10, "reason": "조금만 들고 가요."},
        {"symbol": "CASH", "weight": 30, "reason": "하락에 대비해요."},
    ],
}


def test_claude_advisor_reads_weights_sources_and_cost_across_pause() -> None:
    search: list[dict[str, Any]] = [
        {"type": "text", "text": "먼저 찾아볼게요."},
        {
            "type": "server_tool_use",
            "id": "s1",
            "name": "web_search",
            "input": {"query": "Fed rate"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "s1",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://a.example/1",
                    "title": "A",
                    "encrypted_content": "x",
                    "page_age": None,
                },
            ],
        },
    ]
    client = FakeClient(
        _message(search, stop="pause_turn", searches=1),
        _message([{"type": "text", "text": json.dumps(ANSWER, ensure_ascii=False)}]),
    )
    result = ClaudeAdvisor("key", client=cast(Any, client)).advise(_request())

    assert result.advice.weights == {"QQQ": 60, "GLD": 10, "CASH": 30}
    assert result.advice.queries == ("Fed rate",)
    assert [s.url for s in result.advice.sources] == ["https://a.example/1"]
    # 멈춘 답은 그대로 붙여 이어 받는다
    assert client.calls[1]["messages"][1]["role"] == "assistant"
    # 두 번 부른 합: 입력 20만 × $2 + 출력 2만 × $10 (100만 토큰당) + 검색 1번 $0.01
    assert result.usage.cost == Decimal("0.4") + Decimal("0.2") + Decimal("0.01")
    assert result.usage.web_searches == 1


def test_claude_advisor_failure_keeps_cost() -> None:
    bad = FakeClient(_message([{"type": "text", "text": "{not json"}]))
    down = FakeClient(
        anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.example"))
    )
    broken = judge(ClaudeAdvisor("key", client=cast(Any, bad)), _request())
    offline = judge(ClaudeAdvisor("key", client=cast(Any, down)), _request())

    assert broken.status is JudgmentStatus.FAILED and broken.advice is None
    assert broken.usage is not None and broken.usage.cost > 0  # 돈이 든 실패도 비용을 남긴다
    assert offline.status is JudgmentStatus.FAILED and offline.usage is None


class FixedAdvisor:
    source = "fixed"

    def __init__(self, weights: dict[str, int]) -> None:
        self.weights = weights

    def advise(self, request: AdviceRequest) -> AdviceResult:
        usage = AdviceUsage("m", 1, 1, 0, Decimal("0.01"))
        return AdviceResult(Advice(self.weights, {}, ""), usage, "v")


@pytest.mark.parametrize(
    ("weights", "status"),
    [
        ({"QQQ": 50, "GLD": 20, "CASH": 30}, JudgmentStatus.OK),
        ({"QQQ": 50, "GLD": 20, "CASH": 20}, JudgmentStatus.INVALID),  # 합 90
        ({"QQQ": 50, "TQQQ": 20, "CASH": 30}, JudgmentStatus.INVALID),  # 정해 주지 않은 종목
    ],
)
def test_judge_accepts_only_given_symbols_summing_to_100(
    weights: dict[str, int], status: JudgmentStatus
) -> None:
    judgment = judge(FixedAdvisor(weights), _request())
    assert judgment.status is status
    assert (judgment.advice is not None) == (status is JudgmentStatus.OK)
    assert judge(None, _request()).status is JudgmentStatus.FAILED  # 키 없음
