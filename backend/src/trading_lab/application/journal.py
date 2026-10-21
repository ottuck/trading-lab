"""매매일지: 날마다 무엇을 근거로 어떻게 했고, 주문이 어떻게 체결됐는지 (모의 투자 기록).

판단·모의 주문·입금·AI 판단 기록을 판단일별로 엮는다. 이미 남은 기록만 읽어 만들고, 봇을 지우거나
처음부터 다시 시작하면 그때의 일지를 통째로 보관한다 (journal_archives). 실제 계좌로 따라 산
주문은 실거래 기록(live_orders)에 따로 남는다.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from trading_lab.application.errors import NotFound
from trading_lab.application.messages import (
    _usd,
    decision_numbers,
    decision_reason,
    obj,
)
from trading_lab.domain.advisor import CASH, JudgmentStatus
from trading_lab.domain.strategy import is_ai
from trading_lab.persistence.ai_judgments import all_judgments
from trading_lab.persistence.bots import decisions_of, deposits_by_date, get_bot
from trading_lab.persistence.journal import (
    archives_of,
    get_archive,
    save_archive,
    sim_orders_of,
)
from trading_lab.persistence.models import AiJudgmentRow, BotRow, DecisionRow, SimOrderRow


class JournalTrade(TypedDict):
    symbol: str
    side: str  # BUY | SELL
    status: str  # PENDING(다음 장에 예정) | FILLED | UNFILLED
    fill_date: str | None
    qty: str | None
    price: str | None  # 한 주 가격
    amount: str | None  # 체결 금액 (수량 × 가격)
    realized_pnl: str | None


class JournalLine(TypedDict):
    """종목 하나 (AI 봇은 현금 CASH도). AI 봇만 비중(before·target)이 있다."""

    symbol: str
    action: str  # BUY | SELL | HOLD (현금은 "")
    reason: str  # 쉬운 말 이유
    numbers: str  # 판단에 쓴 숫자 한 문장
    before: str | None  # 판단할 때 비중 %
    target: int | None  # 목표 비중 %
    blocked: str | None


class JournalDay(TypedDict):
    date: str  # 판단일 (미국 거래일). 주문은 다음 거래일 시가에 체결한다
    quiet: bool  # 주문·입금·비중 변화가 없는 날 (화면이 묶어서 보여준다)
    headline: str  # 이날 한 일 한 문장
    basis: list[str]  # AI 봇: 그렇게 정한 근거
    summary: str | None  # AI 봇: 그날 시장(차트) 요약
    lines: list[JournalLine]
    trades: list[JournalTrade]
    deposit: str | None  # 이날 넣은 돈
    sources: list[dict[str, str]]  # AI 봇: 근거로 쓴 기사 [{url, title}]


# 판단하지 못한 날 (AI 봇)
MISSED = {
    JudgmentStatus.FAILED: "AI가 이날 판단하지 못해서 지금 그대로 뒀어요.",
    JudgmentStatus.INVALID: "AI 답이 규칙(고른 종목만, 합 100%)에 맞지 않아 지금 그대로 뒀어요.",
    JudgmentStatus.OVER_BUDGET: "이번 달 AI 비용 상한에 닿아서 지금 그대로 뒀어요.",
}
REASONS = {"DELETED": "봇을 지우기 전", "RESET": "처음부터 다시 시작하기 전"}


def weights_when_judged(request: dict[str, Any] | None) -> dict[str, str]:
    """AI 판단을 부를 때의 비중 % (기록한 입력에서, 현금은 CASH)."""
    if not request:
        return {}
    out = {s["symbol"]: s["weight_now"] for s in request.get("symbols", [])}
    return out | {CASH: request.get("cash_weight", "0")}


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _trade(o: SimOrderRow) -> JournalTrade:
    amount = o.qty * o.price if o.qty is not None and o.price is not None else None
    return JournalTrade(
        symbol=o.symbol,
        side=o.side,
        status=o.status,
        fill_date=o.fill_date.isoformat() if o.fill_date else None,
        qty=_str(o.qty),
        price=_str(o.price),
        amount=_str(amount),
        realized_pnl=_str(o.realized_pnl),
    )


def _names(symbols: list[str]) -> str:
    return "·".join("현금" if s == CASH else s for s in symbols)


def _trade_headline(trades: list[JournalTrade]) -> str:
    """'QQQ를 샀어요', 'TQQQ를 팔고 QQQ·VOO를 샀어요', 다음 장 예정이면 '…사요'."""
    parts = []
    for side, past, plan, fail in (
        ("SELL", "팔았어요", "팔아요", "팔려 했지만 체결되지 않았어요"),
        ("BUY", "샀어요", "사요", "사려 했지만 체결되지 않았어요"),
    ):
        group = [t for t in trades if t["side"] == side]
        if not group:
            continue
        status = group[0]["status"]
        verb = past if status == "FILLED" else plan if status == "PENDING" else fail
        parts.append((obj(_names([t["symbol"] for t in group])), verb))
    if not parts:
        return ""
    if len(parts) == 2:  # 팔고 산 날
        (sold, verb), (bought, buy) = parts
        return f"{sold} {verb.removesuffix('았어요').removesuffix('아요')}고 {bought} {buy}"
    return f"{parts[0][0]} {parts[0][1]}"


def _rule_day(
    day: date, rows: list[DecisionRow], trades: list[JournalTrade], deposit: Decimal | None
) -> JournalDay:
    lines = []
    for r in rows:
        snap = r.strategy or {}
        name, params = snap.get("name", ""), snap.get("params", {})
        lines.append(
            JournalLine(
                symbol=r.symbol,
                action=r.action,
                reason=decision_reason(name, params, r.indicators, action=r.action, raw=r.reason),
                numbers=decision_numbers(name, params, r.indicators),
                before=None,
                target=None,
                blocked=r.blocked,
            )
        )
    headline = _trade_headline(trades)
    if not headline:
        held = any(r.holding for r in rows)
        if deposit is not None:
            headline = f"{_usd(deposit)} 넣고 사지 않고 모아 뒀어요"
        else:
            headline = "그대로 들고 있었어요" if held else "사지 않고 기다렸어요"
    blocked = any(r.blocked for r in rows)
    return JournalDay(
        date=day.isoformat(),
        quiet=not trades and deposit is None and not blocked,
        headline=headline,
        basis=[],
        summary=None,
        lines=lines,
        trades=trades,
        deposit=_str(deposit),
        sources=[],
    )


def _change_headline(weights: dict[str, int], previous: dict[str, int] | None) -> str:
    """지난 판단의 목표 비중과 비교한 한 문장 (AI가 쓴 한 문장이 없던 예전 판단)."""
    if previous is None:
        return "처음으로 비중을 정했어요"
    keys = sorted(set(weights) | set(previous), key=lambda k: k == CASH)
    up = [k for k in keys if weights.get(k, 0) > previous.get(k, 0)]
    down = [k for k in keys if weights.get(k, 0) < previous.get(k, 0)]
    if up and down:
        return f"{_names(up)} 비중을 늘리고 {_names(down)} 비중을 줄였어요"
    if up or down:
        return f"{_names(up or down)} 비중을 {'늘렸어요' if up else '줄였어요'}"
    return "지난 비중을 그대로 유지했어요"


def _now(line: JournalLine) -> float:
    return float(line["before"] or 0)


def _ai_day(
    day: date,
    rows: list[DecisionRow],
    trades: list[JournalTrade],
    deposit: Decimal | None,
    judgment: AiJudgmentRow | None,
    previous: dict[str, int] | None,
) -> JournalDay:
    """previous는 지난 판단의 목표 비중 (바꿨는지는 지금 비중이 아니라 지난 목표와 비교한다)."""
    by_symbol = {r.symbol: r for r in rows}
    ok = bool(judgment and judgment.status == JudgmentStatus.OK and judgment.weights)
    before = weights_when_judged(judgment.request if judgment else None)
    weights = (judgment.weights if judgment and ok else None) or {}
    reasons = (judgment.reasons if judgment and ok else None) or {}
    lines = []
    for symbol in [*by_symbol, CASH]:
        r = by_symbol.get(symbol)
        target = weights.get(symbol) if ok else None
        now = before.get(symbol)
        acted = r is not None and (r.action != "HOLD" or r.blocked)
        if not acted and not target and float(now or 0) < 0.5:
            continue  # 담지도 들고 있지도 않은 종목
        lines.append(
            JournalLine(
                symbol=symbol,
                action=r.action if r else "",
                reason=reasons.get(symbol, ""),
                numbers="",
                before=now,
                target=target,
                blocked=r.blocked if r else None,
            )
        )
    lines.sort(
        key=lambda ln: (ln["symbol"] == CASH, -(ln["target"] or 0), -float(ln["before"] or 0))
    )
    if not ok:
        status = JudgmentStatus(judgment.status) if judgment else JudgmentStatus.FAILED
        headline = MISSED.get(status, MISSED[JudgmentStatus.FAILED])
    else:
        assert judgment is not None
        headline = judgment.decision or _change_headline(weights, previous)
    changed = ok and weights != previous
    sources = [
        {"url": s["url"], "title": s.get("title") or s["url"]}
        for s in (judgment.sources or [] if judgment else [])
        if s.get("used")
    ]
    return JournalDay(
        date=day.isoformat(),
        quiet=bool(ok) and not trades and deposit is None and not changed,
        headline=headline.rstrip("."),
        basis=list(judgment.basis or []) if judgment and ok else [],
        summary=judgment.summary if judgment and ok else None,
        lines=lines,
        trades=trades,
        deposit=_str(deposit),
        sources=sources,
    )


def journal_days(session: Session, bot: BotRow) -> list[JournalDay]:
    """지금 기록으로 만든 일지, 오래된 날부터."""
    by_day: dict[date, list[DecisionRow]] = defaultdict(list)
    for d in decisions_of(session, bot.id):
        by_day[d.session_date].append(d)
    if not by_day:
        return []
    orders: dict[date, list[JournalTrade]] = defaultdict(list)
    for o in sim_orders_of(session, bot.id):
        orders[o.signal_date].append(_trade(o))
    deposits = {day: d.amount for day, d in deposits_by_date(session, bot.id).items()}
    ai = is_ai(bot.strategy)
    # 처음부터 다시 시작하기 전의 AI 판단은 그때의 보관 일지에 있다
    first = min(by_day)
    judgments = (
        {j.session_date: j for j in all_judgments(session, bot.id) if j.session_date >= first}
        if ai
        else {}
    )
    days = []
    previous: dict[str, int] | None = None  # 지난 판단의 목표 비중
    for day in sorted(by_day):
        rows, trades, deposit = by_day[day], orders.get(day, []), deposits.get(day)
        if ai:
            judgment = judgments.get(day)
            days.append(_ai_day(day, rows, trades, deposit, judgment, previous))
            if judgment and judgment.status == JudgmentStatus.OK and judgment.weights:
                previous = judgment.weights
        else:
            days.append(_rule_day(day, rows, trades, deposit))
    return days


def archive_journal(session: Session, bot: BotRow, why: str, now: datetime) -> None:
    """봇을 지우거나 처음부터 다시 시작하기 전에 지금 일지를 보관한다 (why: DELETED | RESET)."""
    days = journal_days(session, bot)
    save_archive(session, bot.id, bot.name, bot.strategy, why, list(map(dict, days)), now)


@dataclass(frozen=True)
class ArchiveInfo:
    id: int
    bot_name: str
    strategy: str
    why: str  # 쉬운 말 ("처음부터 다시 시작하기 전")
    first_date: date
    last_date: date


@dataclass(frozen=True)
class Journal:
    bot_id: int | None  # 지운 봇의 일지는 None
    bot_name: str
    strategy: str
    days: list[dict[str, Any]]  # JournalDay, 최근 날부터
    archives: list[ArchiveInfo]  # 같은 봇이 처음부터 다시 시작하며 남긴 일지 (최근 것부터)


def _info(row: Any) -> ArchiveInfo:
    return ArchiveInfo(
        row.id, row.bot_name, row.strategy, REASONS.get(row.why, ""), row.first_date, row.last_date
    )


def bot_journal(session: Session, bot_id: int) -> Journal:
    bot = get_bot(session, bot_id)
    if bot is None:
        raise NotFound(f"봇 {bot_id}가 없습니다")
    days = list(reversed(journal_days(session, bot)))
    archives = [_info(a) for a in archives_of(session, bot_id)]
    return Journal(bot.id, bot.name, bot.strategy, list(map(dict, days)), archives)


def deleted_journals(session: Session) -> list[ArchiveInfo]:
    """지운 봇의 일지 (최근에 지운 것부터)."""
    return [_info(a) for a in archives_of(session, None)]


def archived_journal(session: Session, archive_id: int) -> Journal:
    row = get_archive(session, archive_id)
    if row is None:
        raise NotFound("보관한 일지를 찾지 못했어요")
    days = list(reversed(row.days))
    return Journal(row.bot_id, row.bot_name, row.strategy, days, [])
