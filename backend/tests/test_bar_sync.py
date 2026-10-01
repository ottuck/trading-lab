from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from quant_lab.application.bar_sync import sync_daily_bars
from quant_lab.persistence.bars import load_daily_bars
from tests.fakes import FakeBarSource, WeekdayCalendar, make_bars

CAL = WeekdayCalendar()


def test_full_sync_skips_incomplete_latest_bar(session: Session) -> None:
    bars = make_bars("QQQ", [100 + i for i in range(450)])
    last = bars[-1].session_date
    # 마지막 거래일 정규장 마감(20:00 UTC) 전 → 마지막 봉은 진행 중
    now = datetime(last.year, last.month, last.day, 15, 0, tzinfo=UTC)

    result = sync_daily_bars(FakeBarSource(bars), session, CAL, "QQQ", now)

    assert result.mode == "full"
    assert result.saved == 449
    assert result.skipped_incomplete == [last]
    assert result.issues == []
    assert len(load_daily_bars(session, "QQQ")) == 449


def test_incremental_sync_fetches_only_new_pages(session: Session) -> None:
    bars = make_bars("QQQ", [100 + i for i in range(450)])
    end = bars[-1].session_date
    now = datetime(end.year, end.month, end.day, 23, 0, tzinfo=UTC)
    sync_daily_bars(FakeBarSource(bars[:-3]), session, CAL, "QQQ", now)

    source = FakeBarSource(bars)
    result = sync_daily_bars(source, session, CAL, "QQQ", now)

    assert result.mode == "incremental"
    assert result.saved == 3
    assert result.latest == end
    assert source.requests == 1
    assert len(load_daily_bars(session, "QQQ")) == 450


def test_changed_history_triggers_full_resync(session: Session) -> None:
    bars = make_bars("QQQ", [100 + i for i in range(50)])
    end = bars[-1].session_date
    now = datetime(end.year, end.month, end.day, 23, 0, tzinfo=UTC)
    sync_daily_bars(FakeBarSource(bars[:-1]), session, CAL, "QQQ", now)

    # 2:1 분할로 과거 수정주가가 모두 바뀐 상황
    halved = [
        replace(b, open=b.open / 2, high=b.high / 2, low=b.low / 2, close=b.close / 2) for b in bars
    ]
    result = sync_daily_bars(FakeBarSource(halved), session, CAL, "QQQ", now)

    assert result.mode == "resync"
    stored = load_daily_bars(session, "QQQ")
    assert len(stored) == 50
    assert stored[0].close == Decimal(50)
