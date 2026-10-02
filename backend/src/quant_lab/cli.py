"""운영·개발용 CLI: `uv run python -m quant_lab.cli <command>`."""

import argparse
import io
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from quant_lab.adapters.market_calendar import get_calendar
from quant_lab.adapters.telegram import TelegramClient
from quant_lab.adapters.toss.client import TossClient
from quant_lab.application.backtesting import backtest_symbol
from quant_lab.application.bar_sync import sync_daily_bars
from quant_lab.application.replay import replay_bot
from quant_lab.config import get_settings
from quant_lab.domain.bars import outlier_limit
from quant_lab.domain.bot import CommandKind
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import STRATEGIES
from quant_lab.persistence.bots import (
    create_bot,
    delete_bot,
    enqueue_command,
    get_bot,
    list_bots,
    load_account,
)
from quant_lab.persistence.db import get_engine
from quant_lab.persistence.models import SimOrderRow


def _toss_client() -> TossClient:
    settings = get_settings()
    if settings.toss_client_id is None or settings.toss_client_secret is None:
        raise SystemExit("TOSS_CLIENT_ID, TOSS_CLIENT_SECRET가 설정되지 않았습니다 (.env).")
    return TossClient(
        settings.toss_client_id.get_secret_value(), settings.toss_client_secret.get_secret_value()
    )


def cmd_sync_bars(args: argparse.Namespace) -> int:
    client = _toss_client()
    calendar = get_calendar()
    leverage = {s.symbol: s.leverage_factor for s in client.stocks(args.symbols)}
    exit_code = 0
    with sessionmaker(get_engine())() as session:
        for symbol in args.symbols:
            limit = outlier_limit(leverage.get(symbol))
            result = sync_daily_bars(
                client, session, calendar, symbol, datetime.now(UTC), max_abs_return=limit
            )
            print(
                f"{symbol}: {result.mode}, 저장 {result.saved}개, 최신 {result.latest}, "
                f"미완료 제외 {[d.isoformat() for d in result.skipped_incomplete]}"
            )
            for issue in result.issues:
                exit_code = 1
                print(f"  ! {issue.kind} {issue.session_date}: {issue.detail}")
    client.close()
    return exit_code


def _parse_params(text: str) -> dict[str, int]:
    params: dict[str, int] = {}
    for item in filter(None, text.split(",")):
        key, _, value = item.partition("=")
        params[key.strip()] = int(value)
    return params


def _pct(value: Decimal | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def cmd_backtest(args: argparse.Namespace) -> int:
    strategy = STRATEGIES[args.strategy](**_parse_params(args.params))
    costs = CostModel(commission_rate=args.commission, slippage_bps=args.slippage_bps)
    limits = RiskLimits(max_position_value=args.max_position, max_order_value=args.max_order)
    with sessionmaker(get_engine())() as session:
        run = backtest_symbol(
            session,
            args.symbol,
            strategy,
            initial_cash=args.cash,
            costs=costs,
            limits=limits,
            start=args.start,
            end=args.end,
            now=datetime.now(UTC),
            save=args.save,
        )
    m = run.result.metrics
    print(f"{args.symbol} {strategy.name} {strategy.params}  {m.start} ~ {m.end}")
    print(f"  비용: 수수료 {costs.commission_rate}, 슬리피지 {costs.slippage_bps}bp")
    print(f"  {'':12}{'전략':>12}{'매수 후 보유':>14}")
    print(f"  {'최종 자산':12}{m.final_equity:>12,.0f}{m.benchmark_final_equity:>14,.0f}")
    print(f"  {'총 수익률':12}{_pct(m.total_return):>12}{_pct(m.benchmark_total_return):>14}")
    print(f"  {'CAGR':12}{_pct(m.cagr):>12}{_pct(m.benchmark_cagr):>14}")
    print(f"  {'최대 낙폭':12}{_pct(m.max_drawdown):>12}{_pct(m.benchmark_max_drawdown):>14}")
    print(f"  보유 비중 {_pct(m.exposure)}, 왕복 거래 {m.round_trips}회, 승률 {_pct(m.win_rate)}")
    for p in run.result.pending:
        print(f"  다음 시가 체결 대기: {p.symbol} {p.action} ({p.session_date} 판단: {p.reason})")
    if run.saved_id:
        print(f"  저장됨: {run.saved_id}")
    return 0


def _add_cost_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--strategy", choices=sorted(STRATEGIES), default="sma_cross")
    p.add_argument("--params", default="", help="예: fast=50,slow=200 / entry=55,exit=20")
    p.add_argument("--cash", type=Decimal, default=Decimal(10_000))
    p.add_argument("--commission", type=Decimal, default=Decimal("0.001"))
    p.add_argument("--slippage-bps", type=Decimal, default=Decimal(5))
    p.add_argument("--max-position", type=Decimal, help="종목 최대 보유 금액 (USD)")
    p.add_argument("--max-order", type=Decimal, help="1회 최대 주문 금액 (USD)")


def cmd_bot_create(args: argparse.Namespace) -> int:
    strategy = STRATEGIES[args.strategy](**_parse_params(args.params))
    with sessionmaker(get_engine())() as session:
        bot = create_bot(
            session,
            name=args.name,
            symbol=args.symbol,
            strategy=strategy.name,
            params=strategy.params,
            initial_cash=args.cash,
            costs=CostModel(commission_rate=args.commission, slippage_bps=args.slippage_bps),
            limits=RiskLimits(max_position_value=args.max_position, max_order_value=args.max_order),
            now=datetime.now(UTC),
        )
        session.commit()
        print(f"봇 {bot.id} 생성: {bot.name} {bot.symbol} {bot.strategy} {bot.params} (STOPPED)")
    return 0


def cmd_bot_list(args: argparse.Namespace) -> int:
    with sessionmaker(get_engine())() as session:
        for bot in list_bots(session):
            pf = load_account(session, bot.id)
            print(
                f"{bot.id:>3} {bot.name:<16} {bot.symbol:<6} {bot.strategy} {bot.params} "
                f"{bot.state:<8} 현금 {pf.cash:,.2f} 보유 {pf.qty}주 "
                f"다음 평가 {bot.next_evaluation_at} {bot.state_reason or ''}"
            )
    return 0


def cmd_bot_command(args: argparse.Namespace) -> int:
    with sessionmaker(get_engine())() as session:
        if get_bot(session, args.bot_id) is None:
            print(f"봇 {args.bot_id}가 없습니다. `bot list`로 확인하세요.")
            return 1
        cmd = enqueue_command(session, args.bot_id, CommandKind(args.kind), datetime.now(UTC))
        session.commit()
        print(f"명령 {cmd.id} 등록: 봇 {args.bot_id} {args.kind} (Worker가 처리)")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    strategy = STRATEGIES[args.strategy](**_parse_params(args.params))
    costs = CostModel(commission_rate=args.commission, slippage_bps=args.slippage_bps)
    limits = RiskLimits(max_position_value=args.max_position, max_order_value=args.max_order)
    make_session = sessionmaker(get_engine())
    now = datetime.now(UTC)
    with make_session() as session:
        bot = create_bot(
            session,
            name=f"replay-{now:%Y%m%d%H%M%S}",
            symbol=args.symbol,
            strategy=strategy.name,
            params=strategy.params,
            initial_cash=args.cash,
            costs=costs,
            limits=limits,
            now=now,
        )
        session.commit()
        bot_id = bot.id
    try:
        outcomes = replay_bot(make_session, bot_id, get_calendar(), args.start, args.end)
        with make_session() as session:
            orders = [
                o
                for o in session.scalars(
                    select(SimOrderRow).where(SimOrderRow.bot_id == bot_id).order_by(SimOrderRow.id)
                )
                if o.status == "FILLED"
            ]
            pf = load_account(session, bot_id)
            bt = backtest_symbol(
                session,
                args.symbol,
                strategy,
                initial_cash=args.cash,
                costs=costs,
                limits=limits,
                start=args.start,
                end=args.end,
                now=now,
                save=False,
            ).result
    finally:
        if not args.keep:
            with make_session() as session:
                delete_bot(session, bot_id)
                session.commit()

    statuses = Counter(o.status for o in outcomes)
    replay_fills = [(o.side, o.signal_date, o.fill_date, o.qty, o.price) for o in orders]
    bt_fills = [(f.side, f.signal_date, f.fill_date, f.qty, f.price) for f in bt.fills]
    print(f"{args.symbol} {strategy.name} {strategy.params} {args.start} ~ {args.end}")
    print(f"  평가 {len(outcomes)}회: {dict(statuses)}")
    print(f"  replay 체결 {len(replay_fills)}건, 백테스트 체결 {len(bt_fills)}건")
    print(f"  replay 최종 현금 {pf.cash:,.2f}, 보유 {pf.qty}주")
    same = replay_fills == bt_fills
    print(f"  체결 일치: {'예' if same else '아니오'}")
    if not same:
        for a, b in zip(replay_fills, bt_fills, strict=False):
            if a != b:
                print(f"  첫 차이: replay {a} / backtest {b}")
                break
    return 0 if same else 1


def _telegram() -> TelegramClient:
    settings = get_settings()
    if settings.telegram_bot_token is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다 (.env).")
    return TelegramClient(
        settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id or ""
    )


def cmd_notify_chat_id(args: argparse.Namespace) -> int:
    chats = _telegram().recent_chat_ids()
    if not chats:
        print("최근 메시지가 없습니다. 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
        return 1
    for chat_id, name in chats:
        print(f"TELEGRAM_CHAT_ID={chat_id}  ({name})")
    return 0


def cmd_notify_test(args: argparse.Namespace) -> int:
    if not get_settings().telegram_chat_id:
        raise SystemExit("TELEGRAM_CHAT_ID가 없습니다. 먼저 notify chat-id로 확인하세요.")
    _telegram().send("✅ Quant Lab 알림 테스트 (DRY RUN)")
    print("보냈습니다.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant_lab.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync-bars", help="토스 일봉을 DB에 동기화 (토스 토큰을 새로 발급함)")
    sync.add_argument("symbols", nargs="+", type=str.upper)
    sync.set_defaults(func=cmd_sync_bars)

    bt = sub.add_parser("backtest", help="DB 일봉으로 백테스트 (T 종가 판단 → T+1 시가 체결)")
    bt.add_argument("symbol", type=str.upper)
    bt.add_argument("--strategy", choices=sorted(STRATEGIES), default="sma_cross")
    bt.add_argument("--params", default="", help="예: fast=50,slow=200 / entry=55,exit=20")
    bt.add_argument("--start", type=date.fromisoformat, help="첫 판단일 (warmup은 자동 포함)")
    bt.add_argument("--end", type=date.fromisoformat)
    bt.add_argument("--cash", type=Decimal, default=Decimal(10_000))
    bt.add_argument("--commission", type=Decimal, default=Decimal("0.001"))
    bt.add_argument("--slippage-bps", type=Decimal, default=Decimal(5))
    bt.add_argument("--max-position", type=Decimal, help="종목 최대 보유 금액 (USD)")
    bt.add_argument("--max-order", type=Decimal, help="1회 최대 주문 금액 (USD)")
    bt.add_argument("--save", action="store_true", help="결과를 backtests 테이블에 저장")
    bt.set_defaults(func=cmd_backtest)

    bot = sub.add_parser("bot", help="DRY RUN 봇 관리")
    bot_sub = bot.add_subparsers(dest="bot_command", required=True)
    create = bot_sub.add_parser("create", help="봇 생성 (STOPPED 상태)")
    create.add_argument("name")
    create.add_argument("symbol", type=str.upper)
    _add_cost_args(create)
    create.set_defaults(func=cmd_bot_create)
    bot_sub.add_parser("list", help="봇 목록").set_defaults(func=cmd_bot_list)
    command = bot_sub.add_parser("cmd", help="Worker에 명령 등록")
    command.add_argument("bot_id", type=int)
    command.add_argument("kind", choices=[k.value for k in CommandKind])
    command.set_defaults(func=cmd_bot_command)

    rp = sub.add_parser("replay", help="저장된 일봉으로 정기 평가를 재생하고 백테스트와 비교")
    rp.add_argument("symbol", type=str.upper)
    rp.add_argument("--start", type=date.fromisoformat, required=True)
    rp.add_argument("--end", type=date.fromisoformat, required=True)
    rp.add_argument("--keep", action="store_true", help="재생에 쓴 임시 봇과 기록을 남김")
    _add_cost_args(rp)
    rp.set_defaults(func=cmd_replay)

    notify = sub.add_parser("notify", help="텔레그램 알림 설정 확인")
    notify_sub = notify.add_subparsers(dest="notify_command", required=True)
    notify_sub.add_parser("chat-id", help="봇에게 메시지를 보낸 채팅 ID 확인").set_defaults(
        func=cmd_notify_chat_id
    )
    notify_sub.add_parser("test", help="테스트 메시지 전송").set_defaults(func=cmd_notify_test)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 URL(토큰 포함)을 남기지 않는다
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
