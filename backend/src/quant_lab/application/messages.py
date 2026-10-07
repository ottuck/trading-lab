"""사람이 읽는 말. 전략 소개, 판단 이유, 알림·활동 문장을 한곳에서 만든다.

주식을 잘 모르는 사람도 이해할 수 있게 전문 용어를 피한다 (텔레그램·화면 공용).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from quant_lab.domain.events import (
    AiJudgmentData,
    CommandData,
    ConfigChange,
    ConfigChangeData,
    ErrorReason,
    EventKind,
    LiveControlData,
    LiveFundsData,
    LiveOrderData,
    LiveReconcileData,
    MissedSessionsData,
    RunData,
    SkipReason,
)

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    params: dict[str, int]


@dataclass(frozen=True)
class Choice:
    """프리셋과 따로 고르는 규칙 하나 (예: 고점에 쉬기). options는 (값, 보이는 말)."""

    key: str
    label: str
    options: list[tuple[int, str]]
    hint: str = ""
    requires: str = (
        ""  # 이 규칙 값이 0이면 보이지 않는다 (예: 떨어졌을 때만 사면 고점에 쉬기는 의미 없음)
    )


@dataclass(frozen=True)
class StrategyInfo:
    name: str
    nickname: str
    summary: str
    risk: str  # 낮음·보통·높음
    trades: str  # 거래 빈도를 쉬운 말로
    presets: list[Preset]
    preset_label: str = "반응 속도"  # 프리셋 선택지의 이름
    choices: list[Choice] = field(default_factory=list)  # 프리셋을 바꿔도 유지되는 규칙


CATALOG: dict[str, StrategyInfo] = {
    "sma_cross": StrategyInfo(
        name="sma_cross",
        nickname="느긋한 추세 타기",
        summary="큰 상승 흐름이 이어지는 동안만 들고 있어요. 자주 사고팔지 않고, 큰 하락장을 피하는 데 강해요.",
        risk="낮음",
        trades="1년에 1번 안팎",
        presets=[
            Preset("steady", "느긋하게 (기본)", {"fast": 50, "slow": 200}),
            Preset("quick", "조금 빠르게", {"fast": 20, "slow": 100}),
        ],
    ),
    "trend_filter": StrategyInfo(
        name="trend_filter",
        nickname="200일선 지킴이",
        summary="주가가 지난 200일 평균보다 위에 있을 때만 들고 있어요. 단순하지만, 오르내림이 잦으면 자주 사고팔아요.",
        risk="보통",
        trades="1년에 몇 번",
        presets=[
            Preset("steady", "200일 기준 (기본)", {"sma": 200}),
            Preset("quick", "100일 기준 (빠르게)", {"sma": 100}),
        ],
    ),
    "rsi2": StrategyInfo(
        name="rsi2",
        nickname="급락 줍줍",
        summary="오르는 흐름 속에서 짧게 크게 떨어지면 사고, 반등하면 바로 팔아요. 들고 있는 기간이 짧아요.",
        risk="낮음",
        trades="한 달에 몇 번",
        presets=[Preset("steady", "기본", {"rsi": 2, "entry": 10, "exit_sma": 5, "trend": 200})],
    ),
    "donchian": StrategyInfo(
        name="donchian",
        nickname="신고가 올라타기",
        summary="최근 최고가를 넘어서면 사고, 최근 최저가 아래로 내려가면 팔아요. 강한 상승을 잘 타지만 헛신호도 있어요.",
        risk="보통",
        trades="1년에 여러 번",
        presets=[
            Preset("steady", "55일 기준 (기본)", {"entry": 55, "exit": 20}),
            Preset("quick", "20일 기준 (빠르게)", {"entry": 20, "exit": 10}),
        ],
    ),
    "dip_saver": StrategyInfo(
        name="dip_saver",
        nickname="나처럼 투자",
        summary=(
            "매달 월급날 돈을 넣고 사 모아요. 많이 올랐을 땐 현금으로 모아 두고, "
            "1년 최고가보다 크게 떨어지면 모아 둔 돈까지 다 사요. 팔지 않아요."
        ),
        risk="보통",
        trades="한 달에 한 번 안팎",
        presets=[
            Preset(
                "small",
                "월 $500",
                {"deposit": 500, "day": 25, "dip": 10, "hot": 10, "high": 252, "sma": 200},
            ),
            Preset(
                "base",
                "월 $1,000 (기본)",
                {"deposit": 1000, "day": 25, "dip": 10, "hot": 10, "high": 252, "sma": 200},
            ),
            Preset(
                "large",
                "월 $2,000",
                {"deposit": 2000, "day": 25, "dip": 10, "hot": 10, "high": 252, "sma": 200},
            ),
        ],
        preset_label="매달 넣는 돈",
        choices=[
            Choice(
                "regular",
                "사는 때",
                [(1, "매달"), (0, "떨어졌을 때만")],
                "떨어졌을 때만 사면 평소엔 넣은 돈을 모아 두기만 해요.",
            ),
            Choice(
                "hot",
                "고점에 쉬기",
                [(10, "+10%"), (15, "+15%"), (20, "+20%"), (0, "안 쉼")],
                "200일 평균보다 이만큼 높으면 그달엔 사지 않고 현금으로 모아 둬요.",
                requires="regular",
            ),
            Choice(
                "dip",
                "하락장 기준",
                [(10, "-10%"), (15, "-15%"), (20, "-20%")],
                "1년 최고가보다 이만큼 떨어지면 모아 둔 돈까지 다 사요.",
            ),
        ],
    ),
    "ai_judge": StrategyInfo(
        name="ai_judge",
        nickname="AI에게 맡기기",
        summary=(
            "매달 돈을 넣고, 고른 종목 안에서 무엇을 얼마나 들고 있을지 AI가 매일 시장을 "
            "조사해 정해요. 이유와 참고한 뉴스를 함께 보여줘요."
        ),
        risk="보통",
        trades="AI가 정해요 (매일 판단)",
        presets=[Preset("base", "월 $1,000", {"deposit": 1000, "day": 25})],
        preset_label="매달 넣는 돈",
    ),
}


# 영문·숫자를 한국어로 읽었을 때 받침이 있는 끝 글자 (L=엘, M=엠, N=엔, R=알, 0=영, 1=일, 3=삼, 6=육, 7=칠, 8=팔)
_FINAL_CONSONANT = set("LMNR013678")


def _has_batchim(word: str) -> bool:
    ch = word.strip()[-1:] or "a"
    if "가" <= ch <= "힣":
        return (ord(ch) - ord("가")) % 28 != 0
    return ch.upper() in _FINAL_CONSONANT


def obj(word: str) -> str:
    """목적격 조사: QQQ를, VOO를, 봇을."""
    return f"{word}{'을' if _has_batchim(word) else '를'}"


def subj(word: str) -> str:
    """주격 조사: 봇이, qqq-sma가."""
    return f"{word}{'이' if _has_batchim(word) else '가'}"


def nickname(strategy: str) -> str:
    info = CATALOG.get(strategy)
    return info.nickname if info else strategy


SLIPPAGE_TEXT = {0: "이상적으로", 5: "보통", 10: "보수적으로"}  # 화면의 체결 가격 가정


def _preset_label(info: StrategyInfo, params: dict[str, Any]) -> str:
    keep = {c.key for c in info.choices}  # 따로 고르는 규칙은 빼고 본다
    for p in info.presets:
        if all(params.get(k) == v for k, v in p.params.items() if k not in keep):
            return p.label.replace(" (기본)", "")
    return "직접 설정"


def _limit_text(value: Any) -> str:
    return "가진 현금 전부" if value is None else f"${Decimal(str(value)):,.0f}"


def settings_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """설정을 바꾼 기록을 쉬운 말로: ["전략 급락 줍줍 → 느긋한 추세 타기", "최대 투자 금액 ..."]."""
    lines = []
    old, new = before.get("strategy", ""), after.get("strategy", "")
    bp, ap = before.get("params") or {}, after.get("params") or {}
    info = CATALOG.get(new)
    if old != new:
        lines.append(f"전략 {nickname(old)} → {nickname(new)}")
    elif bp != ap and info:
        pb, pa = _preset_label(info, bp), _preset_label(info, ap)
        if pb != pa:
            lines.append(f"{info.preset_label} {pb} → {pa}")
        for c in info.choices:
            vb, va = bp.get(c.key), ap.get(c.key)
            if vb != va:
                text: dict[Any, str] = dict(c.options)
                lines.append(f"{c.label} {text.get(vb, vb)} → {text.get(va, va)}")
        if not lines:
            lines.append("규칙 값을 바꿨어요")
    sb = int(Decimal(str(before.get("slippage_bps", 5))))
    sa = int(Decimal(str(after.get("slippage_bps", 5))))
    if sb != sa:
        lines.append(f"체결 가격 가정 {SLIPPAGE_TEXT.get(sb, sb)} → {SLIPPAGE_TEXT.get(sa, sa)}")
    mb, ma = before.get("max_position_value"), after.get("max_position_value")
    if _limit_text(mb) != _limit_text(ma):
        lines.append(f"최대 투자 금액 {_limit_text(mb)} → {_limit_text(ma)}")
    return lines


def _usd(value: Any) -> str:
    return f"${Decimal(str(value)):,.2f}"


def _shares(value: Any) -> str:
    """주식 수량. 소수점 6자리까지, 끝자리 0은 지운다 ('0.962140' → '0.96214', '20.000000' → '20')."""
    q = Decimal(str(value or 0)).quantize(Decimal("0.000001"))
    text = f"{q:,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _ind(indicators: dict[str, Any], key: str) -> str:
    return _usd(indicators[key]) if key in indicators else "?"


def decision_reason(
    strategy: str,
    params: dict[str, Any],
    indicators: dict[str, Any],
    target_long: bool,
    holding: bool,
    action: str | None = None,
    raw: str = "",
) -> str:
    """전략 지표를 일상어 한두 문장으로 바꾼다. AI 봇은 AI가 쓴 이유(raw)를 그대로 쓴다."""
    p = params
    if strategy == "ai_judge":
        return raw or "AI가 정한 비중에 맞춰요."
    if strategy == "dip_saver":
        drop = -float(indicators.get("drawdown", 0)) * 100
        up = float(indicators.get("premium", 0)) * 100
        # 상장 1년 미만이면 있는 만큼(bars일)의 최고가·평균으로 본다
        young = indicators.get("bars")
        top = "상장 뒤 최고가" if young else "1년 최고가"
        avg = f"상장 뒤 {int(float(young))}일 평균" if young else f"{p.get('sma')}일 평균"
        if drop >= float(p.get("dip", 10)):
            tail = (
                "모아 둔 돈까지 사요."
                if action == "BUY"
                else "살 현금이 없어 다음 입금을 기다려요."
            )
            return f"{top}보다 {drop:.1f}% 낮아요. {tail}"
        if not int(p.get("regular", 1)):
            return "평소엔 사지 않고 모아 둬요. 크게 떨어지면 그때 몰아서 사요."
        hot = float(p.get("hot", 10))
        if hot and up >= hot:
            return f"{avg}보다 {up:.1f}% 높아요. 이번엔 사지 않고 현금으로 모아 둬요."
        if action == "BUY":
            return "적당한 가격이에요. 이번 달 넣은 돈으로 사요."
        return "적당한 가격이에요. 다음 월급날에 사요."
    if strategy == "sma_cross":
        fast, slow = (
            _ind(indicators, f"sma{p.get('fast')}"),
            _ind(indicators, f"sma{p.get('slow')}"),
        )
        if target_long:
            return f"상승 흐름이에요. 최근 {p.get('fast')}일 평균 가격({fast})이 {p.get('slow')}일 평균({slow})보다 높아요."
        return f"하락 흐름이에요. 최근 {p.get('fast')}일 평균 가격({fast})이 {p.get('slow')}일 평균({slow})보다 낮아요."
    if strategy == "trend_filter":
        avg = _ind(indicators, f"sma{p.get('sma')}")
        side = "위에" if target_long else "아래에"
        return f"주가가 지난 {p.get('sma')}일 평균({avg}) {side} 있어요."
    if strategy == "rsi2":
        if holding and not target_long:
            return f"반등했어요. 주가가 최근 {p.get('exit_sma')}일 평균을 넘었어요."
        if holding:
            return "아직 반등을 기다리는 중이에요."
        if target_long:
            return "오르는 흐름 속에서 단기간에 크게 떨어졌어요. 싸게 살 기회예요."
        return "아직 살 만큼 떨어지지 않았어요."
    if strategy == "donchian":
        high, low = (
            _ind(indicators, f"high{p.get('entry')}"),
            _ind(indicators, f"low{p.get('exit')}"),
        )
        if target_long and not holding:
            return f"최근 {p.get('entry')}일 최고가({high})를 넘어섰어요."
        if not target_long and holding:
            return f"최근 {p.get('exit')}일 최저가({low}) 아래로 내려갔어요."
        if holding:
            return f"최근 {p.get('exit')}일 최저가({low}) 위에서 버티고 있어요."
        return f"최근 {p.get('entry')}일 최고가({high})를 넘기를 기다리는 중이에요."
    return ""


def action_phrase(action: str, holding: bool, symbol: str) -> str:
    if action == "BUY":
        more = "더 " if holding else ""
        return f"내일 장이 열리면 {obj(symbol)} {more}사요."
    if action == "SELL":
        return f"내일 장이 열리면 {obj(symbol)} 팔아요."
    return f"{obj(symbol)} 계속 들고 있어요." if holding else "지금은 사지 않고 기다려요."


@dataclass(frozen=True)
class Message:
    icon: str
    title: str
    body: str
    level: str  # INFO·WARN·ERROR
    notify: bool  # 텔레그램으로 보낼지


# 이유 코드 → 쉬운 말. 엔진의 로그 문구(message 칸)는 읽지 않는다 (domain/events.py).
SKIP_TEXT: dict[str, str] = {
    SkipReason.DATA_NOT_READY: "아직 최신 시세가 도착하지 않았어요.",
    SkipReason.CALENDAR_MISMATCH: "오늘 미국 시장이 열렸는지 토스와 확인이 맞지 않아요.",
    SkipReason.BROKER_UNAVAILABLE: "토스 서버 연결이 잠시 불안정해요.",
    SkipReason.BAD_BARS: "시세 데이터에 비어 있거나 이상한 날이 있어요.",
    SkipReason.NOT_ENOUGH_BARS: "판단에 필요한 만큼 시세가 쌓이지 않았어요.",
    SkipReason.DUPLICATE: "같은 날 판단이 이미 진행 중이에요.",
    SkipReason.NO_RECENT_SESSION: "최근에 끝난 거래일을 찾지 못했어요.",
    SkipReason.BOT_MISSING: "봇을 찾지 못했어요.",
}
ERROR_TEXT: dict[str, str] = {
    ErrorReason.BROKER_ACCESS: "토스가 접속을 막았거나 로그인 정보에 문제가 있어요. "
    "인터넷 주소(IP)가 바뀌었거나 키가 만료됐을 수 있어요. 토스 앱의 허용 IP와 키를 확인해 주세요.",
    ErrorReason.UNEXPECTED: "예상하지 못한 문제가 생겼어요. 확인이 필요해요.",
}


def _weights_label(symbols: list[dict[str, Any]]) -> str:
    active = [s for s in symbols if int(s.get("weight", 0)) > 0]
    if len(active) > 1:
        return " · ".join(f"{s['symbol']} {s['weight']}%" for s in active)
    return "·".join(str(s["symbol"]) for s in active)


def event_message(
    kind: str,
    level: str,
    raw: str,
    data: dict[str, Any] | None,
    bot_name: str | None,
    symbol: str | None,
) -> Message | None:
    """이벤트 한 건을 사람이 읽는 메시지로. None이면 보여주지 않는다."""
    d = data or {}
    sym = d.get("symbol") or symbol or ""
    who = bot_name or "봇"
    equity_line = ""
    if "equity" in d:
        ret = float(d.get("total_return", 0)) * 100
        equity_line = f"내 모의 자산 {_usd(d['equity'])} ({ret:+.2f}%)"

    if kind == EventKind.DECISION:
        if "action" not in d:
            return None  # 예전 형식의 "이미 판단함" 기록
        action = d["action"]
        reason = decision_reason(
            d.get("strategy", ""),
            d.get("params", {}),
            d.get("indicators", {}),
            bool(d.get("target_long")),
            bool(d.get("holding")),
            action=d.get("action"),
            raw=str(d.get("reason", "")),
        )
        phrase = action_phrase(action, bool(d.get("holding")), sym)
        if action == "BUY":
            return Message(
                "🔴", f"매수 신호 · {sym}", f"{reason}\n{phrase} (모의 투자)", "INFO", True
            )
        if action == "SELL":
            return Message(
                "🔵", f"매도 신호 · {sym}", f"{reason}\n{phrase} (모의 투자)", "INFO", True
            )
        body = "\n".join(x for x in (f"{phrase} {reason}", equity_line) if x)
        # 아무것도 하지 않는 날의 점검은 앱 기록에만 남긴다. 텔레그램은 거래·문제·주간 정리만.
        return Message("📋", f"오늘의 점검 · {sym}", body, "INFO", False)

    if kind == EventKind.DEPOSIT:
        amount, total = _usd(d.get("amount", 0)), _usd(d.get("contributed", 0))
        body = f"모의 계좌에 {amount}를 넣었어요. 지금까지 넣은 돈 {total}"
        return Message("💵", f"월급 입금 · {sym}", body, "INFO", False)

    if kind == EventKind.SIM_FILL:
        qty, price = _shares(d.get("qty")), d.get("price")
        fee = _usd(d.get("commission", 0))
        if d.get("side") == "BUY":
            return Message(
                "✅",
                f"{sym} {qty}주를 샀어요",
                f"한 주에 {_usd(price)} · 수수료 {fee} (모의 투자)",
                "INFO",
                True,
            )
        pnl = d.get("realized_pnl")
        pnl_text = (
            f"이번 거래 손익 {'+' if pnl and Decimal(str(pnl)) >= 0 else ''}{_usd(pnl)}"
            if pnl is not None
            else ""
        )
        return Message(
            "💰",
            f"{sym} {qty}주를 팔았어요",
            f"한 주에 {_usd(price)} · {pnl_text} (모의 투자)",
            "INFO",
            True,
        )

    if kind == EventKind.WEEKLY_REPORT:
        week, hold = Decimal(d["week_return"]), Decimal(d["hold_return"])
        buys, sells = int(d.get("buys", 0)), int(d.get("sells", 0))
        trades = (
            f"이번 주 거래 {buys + sells}번 (산 것 {buys}번, 판 것 {sells}번)"
            if buys + sells
            else "이번 주 거래는 없었어요"
        )
        gap = week - hold  # 0.1%p 안쪽은 비슷하다고 본다 (현금 조금·수수료 차이)
        if gap > Decimal("0.001"):
            verdict = "이번 주는 그냥 들고 있을 때보다 나았어요."
        elif gap < Decimal("-0.001"):
            verdict = "이번 주는 그냥 들고 있는 게 더 나았어요."
        else:
            verdict = "이번 주는 그냥 들고 있을 때와 비슷했어요."
        return Message(
            "📊",
            f"이번 주 정리 · {sym}",
            "\n".join(
                (
                    f"내 모의 자산 {_usd(d['equity'])} · 이번 주 {week * 100:+.2f}%",
                    f"그냥 들고 있었다면 이번 주 {hold * 100:+.2f}%",
                    verdict,
                    trades,
                    f"시작부터 {Decimal(d['total_return']) * 100:+.2f}%",
                )
            ),
            "INFO",
            True,
        )
    if kind == EventKind.BOT_RESET:
        return Message(
            "🔄",
            f"{obj(who)} 처음부터 다시 시작해요",
            "모의 잔고를 시작 금액으로 되돌리고 기록을 지웠어요. 곧 오늘 판단부터 다시 해요.",
            "INFO",
            True,
        )
    if kind == EventKind.BOT_DELETED:
        name = d.get("name") or who
        return Message("🗑️", f"{obj(name)} 지웠어요", "봇과 그 기록을 모두 지웠어요.", "INFO", True)
    if kind == EventKind.RESTART_RESUME:
        # 배포로 다시 켜질 때마다 알리면 시끄럽다: 판단할 때가 지난 봇만 텔레그램으로 (앱 기록에는 늘)
        return Message(
            "🔄",
            f"{obj(who)} 이어서 실행해요",
            "프로그램이 다시 켜졌어요. 멈춘 동안 밀린 판단이 있으면 바로 처리해요.",
            "INFO",
            bool(d.get("overdue", True)),
        )
    if kind == EventKind.RESTART_PAUSE:  # 2026-10-02 이전 기록
        return Message(
            "⏸️",
            f"{obj(who)} 잠시 멈췄어요",
            "프로그램이 다시 켜졌어요. 앱에서 [매매 시작]을 눌러 주세요.",
            "WARN",
            True,
        )
    if kind == EventKind.RUN_SKIPPED:
        run = cast(RunData, d)
        notify = level == "WARN"  # 같은 이유가 이어지면 두 번째부터 INFO로 기록된다
        text = SKIP_TEXT.get(run.get("reason", ""), "잠시 확인이 필요한 상황이에요.")
        return Message(
            "⏳", "오늘 판단을 잠시 미뤘어요", f"{text}\n15분 뒤 다시 확인해요.", level, notify
        )
    if kind == EventKind.RUN_ERROR:
        run = cast(RunData, d)
        text = ERROR_TEXT.get(run.get("reason", ""), ERROR_TEXT[ErrorReason.UNEXPECTED])
        return Message("🚨", f"{subj(who)} 멈췄어요", text, "ERROR", True)
    if kind == EventKind.MISSED_SESSIONS:
        missed = cast(MissedSessionsData, d)
        span = (
            f" ({missed['first']} ~ {missed['last']}, {missed['count']}일)"
            if "count" in missed
            else ""
        )
        return Message(
            "📅",
            "판단하지 못한 날이 있어요",
            f"프로그램이 꺼져 있던 동안의 판단을 건너뛰었어요.{span}",
            "WARN",
            True,
        )
    if kind == EventKind.LIVE_ORDER:
        return _live_order_message(cast(LiveOrderData, d))
    if kind == EventKind.LIVE_FUNDS:
        funds = cast(LiveFundsData, d)
        needed, available = Decimal(funds["needed"]), Decimal(funds["available"])
        when = f"{funds['deadline']}에 " if funds.get("deadline") else "다음 장이 열리면 "
        body = (
            f"{when}실제 주문 {_usd(needed)}를 내야 하는데 달러가 {_usd(available)} 있어요. "
            f"그 전에 {_usd(needed - available)} 이상 채워 주세요. 못 채우면 이번 몫은 넘어가요."
        )
        return Message("💵", "실제 주문할 달러가 모자라요", body, "WARN", True)
    if kind == EventKind.LIVE_RECONCILE:
        items = cast(LiveReconcileData, d).get("shortfall") or []
        if not items:
            return Message("✅", "실제 계좌가 봇 기록과 다시 맞아요", "", "INFO", True)
        lines = [
            f"{i['symbol']}: 계좌 {_shares(i['held'])}주 · 봇이 산 수량 {_shares(i['bought'])}주"
            for i in items
        ]
        lines.append("직접 파셨다면 괜찮아요. 실제 주문은 맞을 때까지 매번 승인을 받아요.")
        body = "\n".join(lines)
        return Message("⚠️", "실제 계좌가 봇 기록보다 적어요", body, "WARN", True)
    if kind == EventKind.AI_JUDGMENT:
        ai = cast(AiJudgmentData, d)
        if ai.get("status") == "OVER_BUDGET":
            body = (
                f"이번 달 AI 비용이 상한({_usd(ai.get('budget', 0))})에 닿았어요 "
                f"(쓴 돈 {_usd(ai.get('spent', 0))}). 이번 달 남은 날은 판단하지 않고 지금 그대로 둬요."
            )
            return Message("💸", "AI 비용 상한에 닿았어요", body, level, level == "WARN")
        body = "오늘은 사고팔지 않고 지금 그대로 둬요. 다음 거래일에 다시 판단해요."
        return Message("🤖", "AI가 오늘 판단하지 못했어요", body, "WARN", True)
    if kind == EventKind.NOTIFY_TEST:
        return Message("🔔", "알림 테스트", "텔레그램 알림이 잘 와요.", "INFO", True)
    if kind == EventKind.LIVE_CONTROL:
        if cast(LiveControlData, d).get("halted"):
            return Message(
                "⛔",
                "실제 주문을 모두 멈췄어요",
                "다시 시작할 때까지 실제 계좌로 주문을 내지 않아요.",
                "WARN",
                True,
            )
        return Message("▶️", "실제 주문을 다시 시작해요", "", "INFO", True)
    if kind == EventKind.CONFIG_CHANGE:
        change = cast(ConfigChangeData, d)
        kind_of = change.get("change")
        if kind_of == ConfigChange.LIVE:
            ratio = change["after"].get("live_ratio")
            if ratio is None:
                return Message("⚙️", "실제로 따라 사기를 껐어요", "", "INFO", False)
            share = f"1/{round(1 / Decimal(str(ratio)))}"
            body = (
                f"모의 매수의 {share} 금액을 실제 계좌에서 따라 사요. 처음 몇 번은 승인을 받아요."
            )
            return Message("⚙️", "실제로 따라 사기를 켰어요", body, "INFO", False)
        if kind_of == ConfigChange.SYMBOLS:
            body = f"{_weights_label(change.get('before', {}).get('symbols') or [])} → {_weights_label(change['after']['symbols'])}"
            if change.get("dropped"):
                body += f" (더 사지 않고 들고만 있기: {', '.join(change['dropped'])})"
            return Message("⚙️", "종목을 바꿨어요", body, "INFO", False)
        if kind_of == ConfigChange.RENAME:
            body = f"{change.get('before', {}).get('name')} → {change['after'].get('name')}"
            return Message("⚙️", "이름을 바꿨어요", body, "INFO", False)
        after = change.get("after") or {}
        if kind_of == ConfigChange.CREATE:
            return Message(
                "⚙️", "봇을 만들었어요", nickname(after.get("strategy", "")), "INFO", False
            )
        lines = settings_changes(change.get("before") or {}, after)
        body = " · ".join(lines) or nickname(after.get("strategy", ""))
        return Message("⚙️", "설정을 바꿨어요", body, "INFO", False)
    if kind == EventKind.COMMAND:
        labels = {
            "RUNNING": ("▶️", "매매를 시작했어요"),
            "PAUSED": ("⏸️", "매매를 멈췄어요"),
            "STOPPED": ("⏸️", "매매를 멈췄어요"),
        }
        icon, title = labels.get(cast(CommandData, d).get("state", ""), ("ℹ️", "봇 상태를 바꿨어요"))
        return Message(icon, title, "", "INFO", False)
    # worker_start, decision_repeat, watchlist_sync 등은 내부 기록이라 보여주지 않는다.
    return None


# 실제 주문을 내지 않은 이유 (domain/live.py SkipReason, domain/broker.py RejectReason)
_LIVE_REASONS = {
    "declined": "이번엔 사지 않기로 했어요.",
    "halted": "실제 주문을 멈춰 둔 동안이라 내지 않았어요.",
    "missed": "주문을 받는 시간 안에 내지 못했어요. 이번 몫은 넘어가요.",
    "no_session": "그날 장이 열리지 않아 넘어가요.",
    "leveraged": "이 레버리지 상품은 실제로 사고팔지 않아요 (QLD·TQQQ만 해요).",
    "too_small": "금액이 $1보다 작아 내지 않았어요.",
    "carried": "금액이 작아 모아 뒀어요. 같은 종목 몫이 $1을 넘으면 함께 사요.",
    "no_funds": "실제 계좌에 달러가 모자라 사지 않았어요. 이번 몫은 넘어가요.",
    "nothing_held": "이 봇이 실제로 산 주식이 없어 팔지 않아요 (따라 하기를 켜기 전 모의 보유예요).",
    "outside_hours": "주문을 받는 시간이 아니었어요.",
    "insufficient_funds": "실제 계좌에 돈이 부족해요. 달러를 채워 주세요.",
    "prerequisite": "증권사 앱에서 이 종목의 사전 확인(위험 고지 등)을 먼저 해 주세요.",
    "restricted": "지금 이 종목이나 계좌는 주문이 막혀 있어요.",
    "other": "증권사가 주문을 받지 않았어요.",
}


def _live_order_message(d: LiveOrderData) -> Message | None:
    if d.get("side") == "SELL":
        return _live_sell_message(d)
    sym, amount, state = d.get("symbol", ""), _usd(d.get("amount", 0)), d.get("state")
    why = _LIVE_REASONS.get(d.get("reason", ""), "")
    if state == "WAITING_APPROVAL":
        body = f"다음 장이 열리면 실제 계좌에서 {amount}어치 사요. 앱에서 [승인]을 눌러 주세요."
        return Message("🙋", f"실제로 살까요? · {sym}", body, "INFO", True)
    if state == "APPROVED":
        body = f"다음 장이 열리면 실제 계좌에서 {amount}어치 {'자동으로 ' if d.get('auto') else ''}사요."
        return Message("🛒", f"실제로 사요 · {sym}", body, "INFO", False)
    if state == "FILLED":
        body = f"{sym} {_shares(d.get('filled_qty'))}주를 {amount}에 샀어요 (실제 계좌)."
        return Message("✅", f"실제로 샀어요 · {sym}", body, "INFO", True)
    if state == "SKIPPED":
        warn = d.get("reason") in ("missed", "halted")
        return Message("⏭️", f"실제 주문을 넘겼어요 · {sym}", why, "WARN" if warn else "INFO", warn)
    if state in ("REJECTED", "CANCELED"):
        title = "실제 주문이 거절됐어요" if state == "REJECTED" else "실제 주문이 취소됐어요"
        if d.get("reason") == "insufficient_funds":  # 돈 부족은 고장이 아니라 자동은 그대로
            body = f"{why} 이번 몫은 넘어가요."
        else:
            body = f"{why} 다음 주문부터 다시 승인을 받아요.".strip()
        return Message("⚠️", f"{title} · {sym}", body, "WARN", True)
    if state == "UNKNOWN":
        body = f"증권사 앱에서 {sym} {amount} 주문이 들어갔는지 확인해 주세요. 다음 주문부터 다시 승인을 받아요."
        return Message("⚠️", f"실제 주문을 확인하지 못했어요 · {sym}", body, "WARN", True)
    return None  # SENDING·SENT는 내부 상태


def _live_sell_message(d: LiveOrderData) -> Message | None:
    """파는 실제 주문 (사고팔기 봇은 이 봇이 실제로 산 만큼 모두, AI 봇은 그중 일부)."""
    sym, state = d.get("symbol", ""), d.get("state")
    qty = f"{_shares(d.get('quantity'))}주"
    about = f"{qty}(약 {_usd(d.get('amount', 0))})"
    why = _LIVE_REASONS.get(d.get("reason", ""), "")
    if state == "WAITING_APPROVAL":
        body = f"다음 장이 열리면 실제 계좌의 {sym} {about}를 팔아요. 앱에서 [승인]을 눌러 주세요."
        return Message("🙋", f"실제로 팔까요? · {sym}", body, "INFO", True)
    if state == "APPROVED":
        auto = "자동으로 " if d.get("auto") else ""
        body = f"다음 장이 열리면 실제 계좌의 {sym} {about}를 {auto}팔아요."
        return Message("🛒", f"실제로 팔아요 · {sym}", body, "INFO", False)
    if state == "FILLED":
        body = f"{sym} {_shares(d.get('filled_qty'))}주를 팔았어요 (실제 계좌)."
        return Message("✅", f"실제로 팔았어요 · {sym}", body, "INFO", True)
    if state == "SKIPPED":
        warn = d.get("reason") in ("missed", "halted")
        return Message("⏭️", f"실제 매도를 넘겼어요 · {sym}", why, "WARN" if warn else "INFO", warn)
    if state in ("REJECTED", "CANCELED", "UNKNOWN"):
        title = {
            "REJECTED": "실제 매도가 거절됐어요",
            "CANCELED": "실제 매도가 취소됐어요",
            "UNKNOWN": "실제 매도를 확인하지 못했어요",
        }[state]
        body = f"{why} 증권사 앱에서 {sym}를 확인해 주세요. 다음 주문부터 다시 승인을 받아요."
        return Message("⚠️", f"{title} · {sym}", body.strip(), "WARN", True)
    return None


def telegram_text(msg: Message, bot_name: str | None, at_kst: str) -> str:
    lines = [f"{msg.icon} {msg.title}"]
    if msg.body:
        lines.append(msg.body)
    footer = " · ".join(x for x in (bot_name, at_kst) if x)
    lines.append(f"— {footer}")
    return "\n".join(lines)
