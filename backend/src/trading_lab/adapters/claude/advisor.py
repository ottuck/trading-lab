"""Claude API 판단 어댑터: 요약 입력 → 웹 검색 → 구조화 출력(목표 비중) (project.md 14절).

엔진은 domain/advisor.py 규약만 안다. 모델 이름·요금·웹 검색·응답 형식은 여기에만 둔다.
"""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Final, cast

import anthropic
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaWebSearchTool20250305Param,
)

from trading_lab.domain.advisor import (
    CASH,
    Advice,
    AdviceRequest,
    AdviceResult,
    AdviceUsage,
    AdvisorError,
    Source,
)

SOURCE = "claude"
MODEL = "claude-sonnet-5-5"  # 2026-10-06 사용자 결정
PROMPT_VERSION = "2026-10-22.1"  # 지침(SYSTEM·입력 형식)을 바꾸면 올린다
MAX_SEARCHES = 5
# 기본 웹 검색 도구. 결과를 서버에서 코드로 걸러 주는 web_search_20260209는 AI가 기사 주소를 거의
# 보지 못해 근거 기사를 1개(늘 첫 결과)만 댔고 같은 검색을 반복했다. 기본 도구는 같은 날 비교에서
# 근거 5개·검색 3번·$0.147 (최신 도구 1개·5번·$0.188) (2026-10-07 실측)
SEARCH_TOOL: Final = "web_search_20250305"
MAX_EVIDENCE = 6  # 근거로 쓴 기사로 받는 최대 수
# 검색에서 뺄 사이트: 백과사전, 지역 뉴스, 예측시장·베팅, 질 낮은 전망 글
# (2026-10-07 운영 첫 판단의 출처를 보고 골랐다)
BLOCKED_DOMAINS = [
    "wikipedia.org",
    "dtnext.in",
    "defirate.com",
    "polymarket.com",
    "kalshi.com",
    "top1markets.com",
]
MAX_CONTINUATIONS = 3  # 웹 검색이 길어져 멈춘 답(pause_turn)을 이어 받는 횟수
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # 거절되면 서버가 다른 모델로 이어 답함

# 100만 토큰당 달러: 입력, 출력, 캐시 쓰기, 캐시 읽기 (2026-10-06 기준). 모르는 모델은 가장 비싼 값
_PRICES = {
    "claude-sonnet-5-5": (Decimal(2), Decimal(10), Decimal("2.5"), Decimal("0.2")),
    "claude-opus-5-5": (Decimal(4), Decimal(20), Decimal(5), Decimal("0.2")),
}
_UNKNOWN_PRICE = (Decimal(10), Decimal(50), Decimal("12.5"), Decimal(1))
_SEARCH_PRICE = Decimal("0.01")  # 웹 검색 1번
_MTOK = Decimal(1_000_000)

SYSTEM = """\
당신은 한 개인 투자자의 모의 투자 봇을 운용합니다. 매일 미국 정규장이 끝난 뒤 한 번, \
정해 준 종목들과 현금 사이의 목표 비중을 정합니다. 엔진이 지금 비중과의 차이를 다음 거래일 \
시가에 팔고 사서 맞춥니다(팔기 먼저, 작은 차이는 무시). 주문·수수료·한도는 엔진이 맡습니다.

판단하는 법
- 먼저 웹 검색으로 지금 시장 상황(금리·물가·실적·정책·큰 뉴스)과 각 종목에 관한 최근 소식을 \
확인하세요. 검색은 꼭 필요한 만큼만 합니다.
- 미국 시장 소식은 영어로 검색하고, 로이터·블룸버그·CNBC·WSJ·야후 파이낸스처럼 믿을 만한 \
경제 뉴스를 우선하세요. 백과사전, 날짜가 오래된 글, 다른 나라 지역 뉴스, 예측시장·베팅 사이트, \
개인 블로그와 광고성 전망 글은 근거로 쓰지 마세요.
- 같은 주제는 한 번만 검색하세요. 날짜만 바꾼 같은 검색은 하지 마세요. 보통 3~4번이면 충분합니다.
- 시장 분위기를 보려고 CNN Fear & Greed 지수(0~100, 낮을수록 겁먹고 높을수록 들뜬 시장)의 \
오늘 값을 한 번 확인하고, summary에 그 값과 뜻을 쉬운 말로 적으세요 (예: "시장 분위기 지수 25, \
겁먹은 편"). 이 지수 하나만으로 비중을 크게 바꾸지는 마세요.
- 입력의 종목 지표(200일 평균 대비, 1년 최고가 대비, 수익률, 변동성)와 지금 비중을 함께 보세요.
- 이 투자자는 매달 돈을 넣는 장기 투자자입니다. 지난 판단을 유지하는 것이 기본이고, \
분명한 이유가 있을 때만 비중을 바꾸세요. 근거 없이 매일 뒤집지 마세요.
- feedback은 최근 판단마다 그 비중대로 들고 있었다면 오늘까지의 수익(result, %)과, 같은 현금 \
비중으로 레버리지가 아닌 종목을 똑같이 나눠 들고 있었다면의 수익(even, %)입니다. 종목을 잘 \
골랐는지 보는 기준이지 현금을 줄이거나 레버리지를 늘리라는 뜻이 아닙니다. 며칠 결과에는 운이 \
크게 섞여 있으니 한두 번의 결과로 판단을 뒤집지 말고, 같은 방향으로 여러 번 계속 빗나갈 때 그 \
이유를 돌아보는 데만 쓰세요.
- 레버리지 ETF(leverage 값이 있는 종목)는 하락장에서 손실이 배로 커집니다.
- 목표 비중은 정해 준 종목과 CASH(현금)에만, 0~100 정수로, 합이 정확히 100이 되게 정하세요. \
비중을 0으로 두는 종목도 allocations에 넣으세요.
- evidence에는 판단의 근거가 된 기사 주소를 검색 결과에 나온 그대로 3~6개 넣으세요: 시장 \
전반 1개 이상, 금리·물가 1개 이상, 그리고 많이 담거나 비중을 바꾼 종목에 관한 기사. summary와 \
reason에 쓴 내용은 이 기사들에서 나와야 합니다. 읽기만 하고 쓰지 않은 기사는 넣지 마세요.

쓰는 말 (매매일지에 그대로 남아 나중에 다시 읽습니다)
- decision은 오늘 무엇을 어떻게 했는지 한 문장입니다. 비중을 바꿨으면 무엇을 늘리고 줄였는지, \
그대로 뒀으면 그렇다고 쓰세요 (예: "반도체 비중을 줄이고 현금을 늘렸어요", "지난 비중을 그대로 \
유지했어요").
- basis는 그렇게 정한 근거 2~4개입니다. 하나에 한 문장으로, 무엇을 봤고 그래서 어떻게 했는지가 \
함께 드러나게 쓰세요 (예: "물가가 예상보다 높게 나와 금리 인하가 늦어질 수 있어요. 그래서 많이 \
흔들리는 종목을 줄였어요"). 근거 기사(evidence)에서 확인한 사실만 쓰세요.
- reason은 종목마다 한두 문장으로, 근거를 먼저 쓰고 비중을 어떻게 했는지로 끝내세요 (예: \
"실적이 예상보다 좋았고 200일 평균 위에서 오르고 있어 20%에서 25%로 늘려요").
- summary는 오늘 시장을 두세 문장으로 요약합니다. 모두 한국어로 씁니다.
- 주식을 잘 모르는 사람도 알아듣게 쉬운 말로 쓰고, 전문 용어와 영어 약어는 피하세요.
- 확실하지 않은 것을 사실처럼 쓰지 마세요."""


def _schema(symbols: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "decision": {"type": "string"},
            "basis": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "allocations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": [*symbols, CASH]},
                        "weight": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["symbol", "weight", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "decision", "basis", "allocations", "evidence"],
        "additionalProperties": False,
    }


def _prompt(request: AdviceRequest) -> str:
    return (
        "오늘 판단할 봇의 상태입니다. 비율 값의 단위는 %이고 금액은 달러입니다. "
        "session_date는 지표를 계산한 미국 거래일(그날 종가까지 반영), "
        "as_of는 지금 시각(UTC)입니다. "
        "검색할 때는 as_of 기준 최근 소식을 찾으세요.\n\n"
        + json.dumps(request.as_dict(), ensure_ascii=False, indent=1)
    )


def _cost(model: str, usage: Any) -> Decimal:
    price_in, price_out, price_write, price_read = _PRICES.get(model, _UNKNOWN_PRICE)
    searches = usage.server_tool_use.web_search_requests if usage.server_tool_use else 0
    return (
        Decimal(usage.input_tokens) * price_in
        + Decimal(usage.output_tokens) * price_out
        + Decimal(usage.cache_creation_input_tokens or 0) * price_write
        + Decimal(usage.cache_read_input_tokens or 0) * price_read
    ) / _MTOK + searches * _SEARCH_PRICE


class ClaudeAdvisor:
    def __init__(
        self, api_key: str, client: anthropic.Anthropic | None = None, model: str = MODEL
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=2)
        self._model = model

    @property
    def source(self) -> str:
        return SOURCE

    def advise(self, request: AdviceRequest) -> AdviceResult:
        symbols = [s.symbol for s in request.symbols]
        messages: list[BetaMessageParam] = [{"role": "user", "content": _prompt(request)}]
        search: BetaWebSearchTool20250305Param = {
            "type": SEARCH_TOOL,
            "name": "web_search",
            "max_uses": MAX_SEARCHES,
            "user_location": {"type": "approximate", "country": "US"},
            "blocked_domains": BLOCKED_DOMAINS,
        }
        output: BetaOutputConfigParam = {
            "effort": "high",
            "format": {"type": "json_schema", "schema": _schema(symbols)},
        }
        responses: list[BetaMessage] = []
        try:
            for _ in range(MAX_CONTINUATIONS + 1):
                response = self._client.beta.messages.create(
                    model=self._model,
                    max_tokens=16000,
                    system=SYSTEM,
                    messages=messages,
                    tools=[search],
                    output_config=output,
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                )
                responses.append(response)
                if response.stop_reason != "pause_turn":
                    break
                # 서버가 검색 도중 멈춤: 받은 내용을 그대로 붙여 다시 보내면 이어서 한다
                paused = {"role": "assistant", "content": response.content}
                messages = [messages[0], cast(BetaMessageParam, paused)]
        except anthropic.APIError as e:
            raise AdvisorError(f"AI 호출 실패: {type(e).__name__}: {e}", _usage(responses)) from e

        usage = _usage(responses)
        last = responses[-1]
        if last.stop_reason != "end_turn":
            raise AdvisorError(f"AI 답이 끝나지 않음: {last.stop_reason}", usage)
        try:
            data = json.loads(_final_text(last))
            weights = {a["symbol"]: int(a["weight"]) for a in data["allocations"]}
            reasons = {a["symbol"]: str(a["reason"]) for a in data["allocations"]}
            summary = str(data["summary"])
            evidence = [str(u) for u in data.get("evidence", [])]
            decision, basis = _rationale(data)
        except (ValueError, KeyError, TypeError) as e:
            raise AdvisorError(f"AI 답 형식 오류: {e}", usage) from e
        sources, queries = _research(responses, evidence)
        advice = Advice(weights, reasons, summary, sources, queries, decision, basis)
        assert usage is not None
        return AdviceResult(advice, usage, PROMPT_VERSION)


def _rationale(data: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """매매일지용 한 문장(decision)과 근거(basis). 빠져도 판단은 쓴다 (비중이 본체)."""
    basis = tuple(str(b).strip() for b in data.get("basis") or () if str(b).strip())
    return str(data.get("decision") or "").strip(), basis


def _usage(responses: Sequence[BetaMessage]) -> AdviceUsage | None:
    if not responses:
        return None
    model = responses[-1].model
    return AdviceUsage(
        model=model,
        input_tokens=sum(r.usage.input_tokens for r in responses),
        output_tokens=sum(r.usage.output_tokens for r in responses),
        web_searches=sum(
            r.usage.server_tool_use.web_search_requests if r.usage.server_tool_use else 0
            for r in responses
        ),
        cost=sum((_cost(r.model, r.usage) for r in responses), Decimal(0)),
    )


def _final_text(message: BetaMessage) -> str:
    """마지막 검색 결과 뒤의 글 (구조화 출력 JSON). 검색 전에 쓴 말은 뺀다."""
    texts: list[str] = []
    for block in message.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type in ("server_tool_use", "web_search_tool_result"):
            texts = []
    return "".join(texts)


def _research(
    responses: Sequence[BetaMessage], evidence: Sequence[str] = ()
) -> tuple[tuple[Source, ...], tuple[str, ...]]:
    """검색한 말과 검색 결과의 주소·제목 (기사 본문은 남기지 않는다).

    AI가 근거로 쓴 기사(evidence)는 실제 검색 결과에 있는 주소만 인정해 앞에 둔다
    (지어낸 주소는 버린다).
    """
    sources: dict[str, Source] = {}
    queries: list[str] = []
    for response in responses:
        for block in response.content:
            if block.type == "server_tool_use" and block.name == "web_search":
                query = block.input.get("query") if isinstance(block.input, dict) else None
                if query:
                    queries.append(str(query))
            elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                for result in block.content:
                    sources.setdefault(result.url, Source(result.url, result.title))
    # AI가 주소를 조금 다르게 옮겨 적을 수 있다 (http/https, www, 끝의 /, 대소문자)
    by_key = {_url_key(u): u for u in sources}
    picked = (by_key.get(_url_key(u)) for u in evidence)
    used = [u for u in dict.fromkeys(picked) if u is not None][:MAX_EVIDENCE]
    cited = [Source(u, sources[u].title, used=True) for u in used]
    rest = [s for u, s in sources.items() if u not in used]
    return (*cited, *rest), tuple(queries)


def _url_key(url: str) -> str:
    """주소 비교용: 스킴·www·끝의 /·호스트 대소문자를 무시한다."""
    rest = url.strip().split("://", 1)[-1]
    host, _, path = rest.partition("/")
    host = host.lower().removeprefix("www.")
    return f"{host}/{path}".rstrip("/")
