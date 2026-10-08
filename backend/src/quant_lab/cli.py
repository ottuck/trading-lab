"""운영·개발용 CLI: `uv run python -m quant_lab.cli <command>`."""

import argparse
import io
import json
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from quant_lab.adapters.claude.advisor import ClaudeAdvisor
from quant_lab.adapters.market_calendar import get_calendar
from quant_lab.adapters.telegram import TelegramClient
from quant_lab.adapters.toss.client import TossClient
from quant_lab.application.ai_judge import AiConfig, judge
from quant_lab.application.backtesting import backtest_symbol
from quant_lab.application.bar_sync import sync_daily_bars
from quant_lab.application.demo_advisor import DemoAdvisor
from quant_lab.application.demo_prices import DEMO_START, DEMO_USD_KRW, LEVERAGE, demo_bars
from quant_lab.application.dry_run import latest_completed_session
from quant_lab.application.replay import replay_bot
from quant_lab.config import get_settings
from quant_lab.domain.advisor import make_request
from quant_lab.domain.bars import outlier_limit
from quant_lab.domain.bot import BotState, CommandKind
from quant_lab.domain.broker import ExchangeRate, Instrument
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import STRATEGIES, AiJudge, is_ai
from quant_lab.persistence.ai_judgments import save_judgment
from quant_lab.persistence.bars import load_daily_bars, upsert_daily_bars
from quant_lab.persistence.bots import (
    create_bot,
    delete_bot,
    enqueue_command,
    get_bot,
    list_bots,
    load_account,
)
from quant_lab.persistence.db import get_engine
from quant_lab.persistence.market_info import (
    leverage_of,
    upsert_exchange_rate,
    upsert_instruments,
)
from quant_lab.persistence.models import DailyBarRow, DecisionRow, SimOrderRow


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
    leverage = {s.symbol: s.leverage_factor for s in client.instruments(args.symbols)}
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


def cmd_bot_create_ai(args: argparse.Namespace) -> int:
    """AI 봇 만들기 (마일스톤 4 A2, 화면은 A3). 종목 비율은 쓰지 않아 똑같이 나눠 둔다."""
    symbols = args.symbols or get_settings().watchlist_symbols.upper().split(",")
    share, extra = divmod(100, len(symbols))
    weights = {s: share + (1 if i < extra else 0) for i, s in enumerate(symbols)}
    strategy = AiJudge(deposit=args.deposit, day=args.day)
    with sessionmaker(get_engine())() as session:
        bot = create_bot(
            session,
            name=args.name,
            symbol=symbols[0],
            strategy=strategy.name,
            params=strategy.params,
            initial_cash=args.cash,
            costs=CostModel(),
            limits=RiskLimits(),
            now=datetime.now(UTC),
            weights=weights,
        )
        session.commit()
        print(f"AI 봇 {bot.id} 생성: {bot.name} {','.join(symbols)} {strategy.params} (STOPPED)")
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


def cmd_seed_demo(args: argparse.Namespace) -> int:
    """포트폴리오 데모 DB에 예시 시세를 넣는다 (D1). 토스 시세가 있는 DB에는 넣지 않는다."""
    now = datetime.now(UTC)
    calendar = get_calendar()
    end = latest_completed_session(calendar, now)
    sessions = calendar.sessions(DEMO_START, end)
    bars = demo_bars(sessions, seed=args.seed)
    with sessionmaker(get_engine())() as session:
        real = session.scalar(
            select(func.count()).select_from(DailyBarRow).where(DailyBarRow.source != "demo")
        )
        if real:
            print(f"이 DB에는 토스 등 실제 시세 {real}건이 있어 예시 시세를 넣지 않습니다.")
            print("데모 전용 DB(DATABASE_URL)를 지정하세요.")
            return 1
        for rows in bars.values():
            upsert_daily_bars(session, rows, "demo", now)
        upsert_instruments(
            session,
            [
                Instrument(
                    symbol=s,
                    name=f"{s} (예시)",
                    market="DEMO",
                    security_type="ETF" if s != "NVDA" else "STOCK",
                    status="ACTIVE",
                    currency="USD",
                    leverage_factor=Decimal(LEVERAGE[s]) if s in LEVERAGE else None,
                )
                for s in bars
            ],
            now,
        )
        fx = ExchangeRate("USD", "KRW", DEMO_USD_KRW, None, now)
        upsert_exchange_rate(session, fx, "demo", now)
        session.commit()
    total = sum(len(v) for v in bars.values())
    print(f"예시 시세 {len(bars)}종목 {total}봉 ({sessions[0]} ~ {end}, seed={args.seed})")
    if args.bots:
        _seed_demo_bots(end, now)
    return 0


# 데모 홈에 미리 돌고 있는 예시 봇: (이름, 전략, 파라미터, 종목·비율, 시작 금액)
DEMO_BOTS: tuple[tuple[str, str, dict[str, int], dict[str, int], Decimal], ...] = (
    (
        "나 카피 봇",
        "dip_saver",
        {"deposit": 1000, "day": 25, "dip": 10, "hot": 15, "high": 252, "sma": 200, "regular": 1},
        {"QQQ": 50, "VOO": 50},
        Decimal(1000),
    ),
    ("QQQ 봇", "sma_cross", {}, {"QQQ": 100}, Decimal(10_000)),
    ("TQQQ 봇", "trend_filter", {}, {"TQQQ": 100}, Decimal(10_000)),
    # AI 봇 (마일스톤 4): 데모에는 AI 키가 없어 규칙으로 만든 예시 판단(DemoAdvisor)을 쓴다
    (
        "AI 봇",
        "ai_judge",
        {"deposit": 1000, "day": 25},
        {s: 10 for s in ("QQQ", "VOO", "QLD", "TQQQ", "SOXL", "NVDA", "GLD", "MAGS", "EWY", "EWJ")},
        Decimal(1000),
    ),
)


def _seed_demo_bots(end: date, now: datetime) -> None:
    """예시 봇을 2년 전부터(AI 봇은 1년 전부터) 정기 평가로 돌려 둔다.

    이미 있으면 마지막 판단 다음 날부터 이어서. AI 봇은 하루 평가가 무거워(종목 10개) 1년만 채운다.
    """
    make_session = sessionmaker(get_engine())
    calendar = get_calendar()
    for name, strategy_name, params, weights, cash in DEMO_BOTS:
        years = 1 if is_ai(strategy_name) else 2
        start = calendar.sessions(date(end.year - years, end.month, 1), end)[0]
        strategy = STRATEGIES[strategy_name](**params)
        with make_session() as session:
            bot = next((b for b in list_bots(session) if b.name == name), None)
            if bot is None:
                bot = create_bot(
                    session,
                    name=name,
                    symbol=next(iter(weights)),
                    strategy=strategy.name,
                    params=strategy.params,
                    initial_cash=cash,
                    costs=CostModel(commission_rate=Decimal("0.001"), slippage_bps=Decimal(5)),
                    limits=RiskLimits(),
                    now=now,
                    weights=weights,
                )
                first = start
            else:
                last = session.scalar(
                    select(func.max(DecisionRow.session_date)).where(DecisionRow.bot_id == bot.id)
                )
                first = (last or start) + timedelta(days=1)
            bot.state = BotState.RUNNING
            session.commit()
            bot_id = bot.id
        if first <= end:
            ai = AiConfig(DemoAdvisor(), Decimal(1_000_000))  # 예시 판단은 비용이 없다
            outcomes = replay_bot(make_session, bot_id, calendar, first, end, ai=ai)
            print(f"  {name}: {first} ~ {end} 평가 {len(outcomes)}회")


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


def cmd_ai_judge(args: argparse.Namespace) -> int:
    """현금만 든 봇이라 치고 AI 판단을 한 번 받아 기록한다 (마일스톤 4 A1, 비용이 든다)."""
    settings = get_settings()
    make_session = sessionmaker(get_engine())
    with make_session() as session:
        start = (args.date or datetime.now(UTC).date()) - timedelta(days=550)
        histories = {s: load_daily_bars(session, s, start, args.date) for s in args.symbols}
        missing = [s for s, h in histories.items() if not h]
        if missing:
            raise SystemExit(f"저장된 일봉이 없는 종목: {', '.join(missing)}")
        days = {h[-1].session_date for h in histories.values()}
        if len(days) != 1:
            raise SystemExit(f"종목마다 마지막 봉 날짜가 다릅니다: {sorted(days)}")
        request = make_request(
            histories,
            cash=args.cash,
            qtys={},
            contributed=args.cash,
            monthly_deposit=args.deposit,
            leverage={s: leverage_of(session, s) for s in args.symbols},
        )
        if args.show:
            print(json.dumps(request.as_dict(), ensure_ascii=False, indent=1))
            return 0
        key = settings.anthropic_api_key
        advisor = ClaudeAdvisor(key.get_secret_value()) if key else None
        judgment = judge(advisor, request)
        save_judgment(session, None, judgment, datetime.now(UTC))
        session.commit()
    print(f"{judgment.session_date} 판단: {judgment.status.value}")
    if judgment.usage:
        u = judgment.usage
        print(
            f"  {u.model} 입력 {u.input_tokens:,} 출력 {u.output_tokens:,}"
            f" 검색 {u.web_searches}번 ${u.cost:.4f}"
        )
    if judgment.error:
        print(f"  이유: {judgment.error}")
    if judgment.advice:
        a = judgment.advice
        print(f"  시장: {a.summary}")
        for symbol, weight in a.weights.items():
            print(f"  {symbol:5} {weight:3}%  {a.reasons.get(symbol, '')}")
        for query in a.queries:
            print(f"  검색: {query}")
        print(f"  출처 {len(a.sources)}곳")
    return 0 if judgment.advice else 1


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
    create_ai = bot_sub.add_parser("create-ai", help="AI 봇 생성 (STOPPED, 매일 AI 판단)")
    create_ai.add_argument("name")
    create_ai.add_argument("--symbols", type=lambda t: t.upper().split(","), help="기본: 관심 목록")
    create_ai.add_argument("--deposit", type=int, default=1000, help="매달 넣는 돈 (USD)")
    create_ai.add_argument("--day", type=int, default=25, help="입금일 (1~28)")
    create_ai.add_argument("--cash", type=Decimal, default=Decimal(1000), help="시작 금액")
    create_ai.set_defaults(func=cmd_bot_create_ai)
    bot_sub.add_parser("list", help="봇 목록").set_defaults(func=cmd_bot_list)
    command = bot_sub.add_parser("cmd", help="Worker에 명령 등록")
    command.add_argument("bot_id", type=int)
    command.add_argument("kind", choices=[k.value for k in CommandKind])
    command.set_defaults(func=cmd_bot_command)

    demo = sub.add_parser("seed-demo", help="데모 DB에 예시 시세 넣기 (토스 데이터 없음)")
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--no-bots", dest="bots", action="store_false", help="예시 봇은 만들지 않음")
    demo.set_defaults(func=cmd_seed_demo)

    rp = sub.add_parser("replay", help="저장된 일봉으로 정기 평가를 재생하고 백테스트와 비교")
    rp.add_argument("symbol", type=str.upper)
    rp.add_argument("--start", type=date.fromisoformat, required=True)
    rp.add_argument("--end", type=date.fromisoformat, required=True)
    rp.add_argument("--keep", action="store_true", help="재생에 쓴 임시 봇과 기록을 남김")
    _add_cost_args(rp)
    rp.set_defaults(func=cmd_replay)

    ai = sub.add_parser("ai-judge", help="AI 판단 1회 시험 (현금만 든 봇, Claude API 비용이 듦)")
    ai.add_argument("symbols", nargs="+", type=str.upper)
    ai.add_argument("--date", type=date.fromisoformat, help="판단일 (기본: 저장된 마지막 봉)")
    ai.add_argument("--cash", type=Decimal, default=Decimal(10_000))
    ai.add_argument("--deposit", type=Decimal, default=Decimal(1000), help="매달 넣는 돈")
    ai.add_argument("--show", action="store_true", help="AI에 넘길 입력만 보여 주고 부르지 않음")
    ai.set_defaults(func=cmd_ai_judge)

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
