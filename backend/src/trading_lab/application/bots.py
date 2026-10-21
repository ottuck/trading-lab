"""봇 관리: 만들기, 설정·종목·이름 바꾸기, 처음부터 다시 시작, 삭제, 명령.

화면(API)·CLI 어디서 불러도 같은 규칙으로 동작한다. 바꾸는 함수는 봇 행을 FOR UPDATE로 잠근다.
Worker 평가도 같은 행을 잠그므로, 평가 중이면 끝날 때까지 기다렸다가 바꾼다 (다음 판단부터 적용).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from trading_lab.application.errors import Conflict, Invalid, NotFound
from trading_lab.application.journal import archive_journal
from trading_lab.domain.bot import CommandKind
from trading_lab.domain.events import BotDeletedData, ConfigChange, ConfigChangeData, EventKind
from trading_lab.domain.portfolio import CostModel, RiskLimits
from trading_lab.domain.strategy import STRATEGIES, Strategy
from trading_lab.domain.trading import MAX_SYMBOLS
from trading_lab.persistence.backtests import to_jsonable
from trading_lab.persistence.bots import (
    add_event,
    bot_weights,
    create_bot,
    delete_bot,
    enqueue_command,
    get_bot,
    name_taken,
    pending_orders,
    positions_of,
    reset_bot_history,
    strategy_taken,
)
from trading_lab.persistence.models import BotRow, CommandRow


@dataclass(frozen=True)
class BotSettings:
    """전략·비용·위험 한도. 바꾸면 다음 판단부터 적용된다."""

    strategy: str
    params: dict[str, int]
    commission_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal(5)
    max_position_value: Decimal | None = None
    max_order_value: Decimal | None = None

    def costs(self) -> CostModel:
        return CostModel(commission_rate=self.commission_rate, slippage_bps=self.slippage_bps)

    def limits(self) -> RiskLimits:
        return RiskLimits(
            max_position_value=self.max_position_value, max_order_value=self.max_order_value
        )


# --- 검증 ---

NAME_MAX = 20  # 봇 목록·칩·제목에 한 줄로 보이는 길이


# 전략마다 봇 하나만 만들 수 있는 것 (2026-10-08). 시장분석·캔들분석 AI 봇은 다른 전략이라
# 따로 하나씩 만든다. 이름은 구분하는 이름표일 뿐 제한은 전략으로 건다.
ONE_PER_STRATEGY = {
    "dip_saver": "나 카피 봇은 하나만 만들 수 있어요. 이미 있는 봇을 '다시 카피하기'로 바꿔 주세요",
    "ai_judge": "시장분석 AI 봇은 하나만 만들 수 있어요. 이미 있는 봇의 설정에서 바꿔 주세요",
    "ai_candle": "캔들분석 AI 봇은 하나만 만들 수 있어요. 이미 있는 봇의 설정에서 바꿔 주세요",
}


def check_single(session: Session, strategy: str, *, except_bot_id: int | None = None) -> None:
    """하나만 만들 수 있는 전략이면 같은 전략의 다른 봇이 이미 있는지 본다."""
    message = ONE_PER_STRATEGY.get(strategy)
    if message is None:
        return
    if strategy_taken(session, strategy, except_bot_id=except_bot_id):
        raise Conflict(message)


def check_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise Invalid("이름을 입력해 주세요")
    if len(name) > NAME_MAX:
        raise Invalid(f"이름은 {NAME_MAX}자까지 쓸 수 있어요")
    return name


MAX_CASH = Decimal(1_000_000)  # 시작 금액 상한 (달러)


def check_cash(initial_cash: Decimal | None) -> None:
    if initial_cash is not None and not 0 < initial_cash <= MAX_CASH:
        raise Invalid(f"시작 금액은 $1~${MAX_CASH:,.0f} 사이로 정해 주세요")


def check_limits(settings: BotSettings) -> None:
    """최대 투자 금액이 0 이하면 봇이 아예 사지 못한다. 없애려면 비워 둔다 (가진 현금 전부)."""
    for value in (settings.max_position_value, settings.max_order_value):
        if value is not None and value < 1:
            raise Invalid("최대 투자 금액은 $1 이상으로 정해 주세요 (없애려면 '가진 현금 전부')")


def require_bot(session: Session, bot_id: int, *, for_update: bool = False) -> BotRow:
    bot = get_bot(session, bot_id, for_update=for_update)
    if bot is None:
        raise NotFound(f"봇 {bot_id}가 없습니다")
    return bot


def check_strategy(name: str, params: dict[str, int]) -> Strategy:
    factory = STRATEGIES.get(name)
    if factory is None:
        raise Invalid(f"알 수 없는 전략: {name}")
    try:
        return factory(**params)
    except (TypeError, ValueError) as exc:
        raise Invalid(f"파라미터 오류: {exc}") from exc


def check_weights(symbol: str, symbols: Sequence[tuple[str, int]] | None) -> dict[str, int]:
    """종목과 비율을 검증한다: 최대 10개, 비율 합 100."""
    if not symbols:
        if not symbol.strip():
            raise Invalid("종목을 골라 주세요")
        return {symbol.strip().upper(): 100}
    weights: dict[str, int] = {}
    for raw, weight in symbols:
        s = raw.strip().upper()
        if not s or s in weights or weight <= 0:
            raise Invalid(f"종목·비율을 확인해 주세요: {s}")
        weights[s] = weight
    if len(weights) > MAX_SYMBOLS:
        raise Invalid(f"종목은 {MAX_SYMBOLS}개까지 고를 수 있어요")
    if sum(weights.values()) != 100:
        raise Invalid("종목 비율의 합은 100이어야 해요")
    return weights


def _symbols_json(weights: dict[str, int]) -> list[dict[str, Any]]:
    return [{"symbol": s, "weight": w} for s, w in weights.items()]


def _changes(before: dict[str, Any], after: dict[str, Any]) -> str:
    diff = [
        f"{k} {before.get(k)} → {v}"
        for k, v in after.items()
        if str(before.get(k)) != str(v)
        and not (before.get(k) is not None and v is not None and _same_number(before[k], v))
    ]
    return ", ".join(diff) or "변경 없음"


def _same_number(a: object, b: object) -> bool:
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except ArithmeticError:
        return False


# --- 바꾸기 ---


def create(
    session: Session,
    *,
    name: str,
    symbol: str,
    symbols: Sequence[tuple[str, int]] | None,
    settings: BotSettings,
    initial_cash: Decimal,
    request: dict[str, Any],
    now: datetime,
) -> BotRow:
    """request는 만든 기록에 남길 원래 요청 (설정 변경 이력의 '처음 값')."""
    strategy = check_strategy(settings.strategy, settings.params)
    check_limits(settings)
    check_cash(initial_cash)
    name = check_name(name)
    if name_taken(session, name):
        raise Conflict(f"같은 이름의 봇이 있습니다: {name}")
    weights = check_weights(symbol, symbols)
    check_single(session, strategy.name)
    bot = create_bot(
        session,
        name=name,
        symbol=next(iter(weights)),
        strategy=strategy.name,
        params=strategy.params,
        initial_cash=initial_cash,
        costs=settings.costs(),
        limits=settings.limits(),
        now=now,
        weights=weights,
    )
    add_event(
        session,
        now,
        "INFO",
        EventKind.CONFIG_CHANGE,
        f"봇 생성: {'·'.join(weights)} {bot.strategy} {bot.params}",
        bot_id=bot.id,
        data=ConfigChangeData(change=ConfigChange.CREATE, after=request),
    )
    session.commit()
    return bot


def update_settings(session: Session, bot_id: int, settings: BotSettings, now: datetime) -> BotRow:
    """실행 중에도 바꿀 수 있다. 다음 판단부터 적용된다."""
    bot = require_bot(session, bot_id, for_update=True)
    strategy = check_strategy(settings.strategy, settings.params)
    check_limits(settings)
    if strategy.name != bot.strategy:
        check_single(session, strategy.name, except_bot_id=bot.id)
    limits = to_jsonable(settings.limits())
    before = {
        "strategy": bot.strategy,
        "params": bot.params,
        "commission_rate": str(bot.commission_rate),
        "slippage_bps": str(bot.slippage_bps),
        **bot.risk,
    }
    after = {
        "strategy": strategy.name,
        "params": strategy.params,
        "commission_rate": str(settings.commission_rate),
        "slippage_bps": str(settings.slippage_bps),
        **limits,
    }
    bot.strategy, bot.params = strategy.name, strategy.params
    bot.commission_rate, bot.slippage_bps = settings.commission_rate, settings.slippage_bps
    bot.risk = limits
    bot.updated_at = now
    add_event(
        session,
        now,
        "INFO",
        EventKind.CONFIG_CHANGE,
        f"설정 변경: {_changes(before, after)}",
        bot_id=bot.id,
        data=ConfigChangeData(change=ConfigChange.SETTINGS, before=before, after=after),
    )
    session.commit()
    return bot


def update_symbols(
    session: Session, bot_id: int, symbols: Sequence[tuple[str, int]], now: datetime
) -> BotRow:
    """만든 뒤 종목·비율을 바꾼다. 다음 판단부터 적용된다.

    뺀 종목을 들고 있으면(또는 주문 예정이면) 비율 0으로 남겨 더 사지 않고 들고만 있는다.
    """
    bot = require_bot(session, bot_id, for_update=True)
    weights = check_weights("", symbols)
    before = bot_weights(bot)
    held = {p.symbol for p in positions_of(session, bot.id) if p.qty > 0} | {
        o.symbol for o in pending_orders(session, bot.id)
    }
    dropped = [s for s in before if s in held and s not in weights]
    after = weights | {s: 0 for s in dropped}
    if after == before:
        return bot

    def label(w: dict[str, int]) -> str:
        active = {s: v for s, v in w.items() if v > 0}
        if len(active) > 1:
            return " · ".join(f"{s} {v}%" for s, v in active.items())
        return "·".join(active)

    detail = f"종목 변경: {label(before)} → {label(after)}"
    if dropped:
        detail += f" (더 사지 않고 들고만 있기: {', '.join(dropped)})"
    add_event(
        session,
        now,
        "INFO",
        EventKind.CONFIG_CHANGE,
        detail,
        bot_id=bot.id,
        data=ConfigChangeData(
            change=ConfigChange.SYMBOLS,
            before={"symbols": bot.symbols},
            after={"symbols": _symbols_json(after)},
            dropped=list(dropped),
        ),
    )
    bot.symbols, bot.symbol = _symbols_json(after), next(iter(weights))
    bot.updated_at = now
    session.commit()
    return bot


def rename(session: Session, bot_id: int, name: str, now: datetime) -> BotRow:
    bot = require_bot(session, bot_id, for_update=True)
    name = check_name(name)
    if name == bot.name:
        return bot
    if name_taken(session, name):
        raise Conflict(f"같은 이름의 봇이 있습니다: {name}")
    add_event(
        session,
        now,
        "INFO",
        EventKind.CONFIG_CHANGE,
        f"이름 변경: {bot.name} → {name}",
        bot_id=bot.id,
        data=ConfigChangeData(
            change=ConfigChange.RENAME, before={"name": bot.name}, after={"name": name}
        ),
    )
    bot.name, bot.updated_at = name, now
    session.commit()
    return bot


def reset(session: Session, bot_id: int, now: datetime) -> BotRow:
    """처음부터 다시 시작: 판단·주문·실행 기록을 지우고 시작 금액으로. 설정·상태는 그대로.

    지우기 전의 매매일지는 보관한다 (봇 화면의 매매일지에서 다시 볼 수 있다).
    """
    bot = require_bot(session, bot_id, for_update=True)
    archive_journal(session, bot, "RESET", now)
    reset_bot_history(session, bot, now)
    add_event(session, now, "INFO", EventKind.BOT_RESET, "처음부터 다시 시작", bot_id=bot.id)
    session.commit()
    return bot


def remove(session: Session, bot_id: int, now: datetime) -> None:
    """봇을 지운다. 매매일지는 보관한다 (매매일지 화면의 "지운 봇")."""
    bot = require_bot(session, bot_id, for_update=True)
    name, symbol = bot.name, bot.symbol
    archive_journal(session, bot, "DELETED", now)
    delete_bot(session, bot_id)
    add_event(
        session,
        now,
        "INFO",
        EventKind.BOT_DELETED,
        f"봇 삭제: {name}",
        data=BotDeletedData(name=name, symbol=symbol),
    )
    session.commit()


def send_command(session: Session, bot_id: int, kind: CommandKind, now: datetime) -> CommandRow:
    """명령은 DB에 기록만 한다. Worker가 다음 주기(15초 이내)에 처리한다."""
    require_bot(session, bot_id)
    cmd = enqueue_command(session, bot_id, kind, now)
    session.commit()
    return cmd
