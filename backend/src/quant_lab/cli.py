"""운영·개발용 CLI: `uv run python -m quant_lab.cli <command>`."""

import argparse
import io
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import sessionmaker

from quant_lab.adapters.market_calendar import get_calendar
from quant_lab.adapters.toss.client import TossClient
from quant_lab.application.backtesting import backtest_symbol
from quant_lab.application.bar_sync import sync_daily_bars
from quant_lab.config import get_settings
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import STRATEGIES
from quant_lab.persistence.db import get_engine


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
    leveraged = {s.symbol for s in client.stocks(args.symbols) if (s.leverage_factor or 1) > 1}
    exit_code = 0
    with sessionmaker(get_engine())() as session:
        for symbol in args.symbols:
            limit = Decimal("0.9") if symbol in leveraged else Decimal("0.5")
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
    if run.result.pending:
        p = run.result.pending
        print(f"  다음 시가 체결 대기: {p.action} ({p.session_date} 판단: {p.reason})")
    if run.saved_id:
        print(f"  저장됨: {run.saved_id}")
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
