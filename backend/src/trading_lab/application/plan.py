"""따라 하기 (F1~F3): 나 카피 봇이 다음에 할 일, 조건까지 거리, 모아 둔 돈의 내력.

규칙은 바꾸지 않고 보여주기만 한다. "지금 가격이 다음 입금일까지 이어진다면" 같은 규칙 함수
(decide_basket)로 계산하므로 실제 그날의 판단과 같은 방식이다 (가격이 바뀌면 결과도 바뀐다).
사용자는 같은 날 같은 금액으로 실제 계좌에서 따라 할 수 있다.
"""

import copy
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from trading_lab.domain.bars import TradingCalendar
from trading_lab.domain.strategy import DipSaver, Spend, month_key
from trading_lab.domain.trading import Action, decide_basket
from trading_lab.persistence.bars import load_daily_bars
from trading_lab.persistence.bots import (
    active_weights,
    bot_costs,
    bot_limits,
    decisions_of,
    deposited_month,
    deposits_by_date,
    load_account,
    pending_buy_orders,
)
from trading_lab.persistence.models import BotRow


@dataclass(frozen=True)
class SymbolPlan:
    symbol: str
    weight: int
    close: Decimal  # 기준 종가
    state: str  # dip(하락장: 몰아 사기) · hot(고점: 쉬기) · wait(떨어질 때까지 모으기) · normal
    dip_price: Decimal  # 이 가격 이하면 모아 둔 돈까지 몰아 산다 (1년 최고가 - 하락장 기준)
    hot_price: (
        Decimal | None
    )  # 이 가격 이상이면 그달은 쉰다 (200일 평균 + 고점 기준). 없으면 안 쉰다
    buy: Decimal  # 다음 입금일에 살 금액
    save: Decimal  # 다음 입금일에 모아 둘 금액


@dataclass(frozen=True)
class ReserveItem:
    month: str  # YYYY-MM, 시작 금액이나 잔돈이면 ""
    symbol: str
    amount: Decimal


@dataclass(frozen=True)
class Plan:
    as_of: date  # 기준 종가 날짜
    deposit_date: date  # 다음 입금일 (거래일)
    deposit: Decimal
    symbols: list[SymbolPlan]
    reserve: Decimal  # 지금 모아 둔 돈
    reserve_items: list[ReserveItem]


def next_deposit_date(
    calendar: TradingCalendar, as_of: date, day: int, last_month: str | None
) -> date:
    """as_of 다음 거래일부터 보아 입금이 일어날 첫 거래일 (입금일이 휴장이면 그 뒤 첫 거래일)."""
    sessions = calendar.sessions(as_of + timedelta(days=1), as_of + timedelta(days=70))
    for d in sessions:
        if d.day >= day and month_key(d) != last_month:
            return d
    return sessions[-1]


def _reserve_items(
    session: Session, bot: BotRow, weights: dict[str, int], reserve: Decimal
) -> list[ReserveItem]:
    """모아 둔 돈이 어느 달 어느 종목 몫에서 왔는지. 마지막으로 몰아 산 뒤의 쉬는 달 몫을 모은다."""
    decisions = decisions_of(session, bot.id)
    deposits = deposits_by_date(session, bot.id)
    items: list[ReserveItem] = []
    for d in decisions:
        if d.action == Action.BUY and d.reason.startswith("하락장"):
            items = []  # 몰아 살 때 모아 둔 돈을 다 쓴다
        elif d.session_date in deposits and d.reason.startswith(("고점", "평소")):
            weight = weights.get(d.symbol or "", 0)
            amount = deposits[d.session_date].amount * weight / 100
            items.append(ReserveItem(deposits[d.session_date].month, d.symbol or "", amount))
    # 시작 금액 몫·잔돈 등 기록으로 나눌 수 없는 나머지
    rest = reserve - sum((i.amount for i in items), Decimal(0))
    if rest >= 1:
        items.append(ReserveItem("", "", rest))
    elif rest < 0:
        items = items[1:] if len(items) > 1 else items
    return items


def follow_plan(session: Session, bot: BotRow, calendar: TradingCalendar) -> Plan | None:
    """나 카피 봇이 다음에 할 일. 봉이 부족하면 None."""
    strategy = DipSaver(**bot.params)
    plan = strategy.deposit_plan
    weights = active_weights(bot)
    histories = {s: load_daily_bars(session, s) for s in weights}
    if any(len(h) < strategy.min_bars for h in histories.values()):
        return None
    pf = load_account(session, bot.id)
    as_of = min(h[-1].session_date for h in histories.values())
    last_month = deposited_month(session, bot.id, as_of)
    deposit_date = next_deposit_date(calendar, as_of, plan.day, last_month)

    # 지금 가격이 입금일까지 이어진다고 보고 같은 규칙 함수로 계산한다 (실제 계좌는 바꾸지 않는다).
    # 다음 장에 살 예정인 돈은 이미 쓴 것으로 본다 (빼지 않으면 입금일에 살 금액이 부풀려진다).
    after = copy.deepcopy(pf)
    for order in pending_buy_orders(session, bot.id):
        after.cash = max(Decimal(0), after.cash - (order.budget or after.cash))
    after.reserve = min(after.reserve, after.cash)
    after.deposit(plan.amount)
    records = {
        r.symbol: r
        for r in decide_basket(
            strategy, histories, weights, after, bot_costs(bot), bot_limits(bot), plan.amount
        )
    }
    symbols = []
    for s, w in weights.items():
        signal = strategy.signal(histories[s])
        if signal is None:
            continue
        ind = signal.indicators
        top, avg = ind[f"high{strategy.high}"], ind[f"sma{strategy.sma}"]
        state = {Spend.ALL: "dip", Spend.DEPOSIT: "normal"}.get(signal.spend, "")
        if signal.spend is Spend.NONE:
            state = "wait" if not strategy.regular else "hot"
        record = records.get(s)
        buy = (
            record.budget
            if record and record.action is Action.BUY and record.budget
            else Decimal(0)
        )
        save = plan.amount * w / 100 if signal.spend is Spend.NONE else Decimal(0)
        symbols.append(
            SymbolPlan(
                symbol=s,
                weight=w,
                close=histories[s][-1].close,
                state=state,
                dip_price=round(top * (1 - Decimal(strategy.dip) / 100), 2),
                hot_price=round(avg * (1 + Decimal(strategy.hot) / 100), 2)
                if strategy.hot and strategy.regular
                else None,
                buy=round(buy, 2),
                save=round(save, 2),
            )
        )
    return Plan(
        as_of=as_of,
        deposit_date=deposit_date,
        deposit=plan.amount,
        symbols=symbols,
        reserve=pf.reserve,
        reserve_items=_reserve_items(session, bot, weights, pf.reserve),
    )
