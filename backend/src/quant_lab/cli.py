"""운영·개발용 CLI: `uv run python -m quant_lab.cli <command>`."""

import argparse
import io
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import sessionmaker

from quant_lab.adapters.market_calendar import get_calendar
from quant_lab.adapters.toss.client import TossClient
from quant_lab.application.bar_sync import sync_daily_bars
from quant_lab.config import get_settings
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant_lab.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync-bars", help="토스 일봉을 DB에 동기화 (토스 토큰을 새로 발급함)")
    sync.add_argument("symbols", nargs="+", type=str.upper)
    sync.set_defaults(func=cmd_sync_bars)
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
