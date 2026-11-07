"""Run the A-share intraday monitor (MONITOR ONLY, never places an order).

    python examples/ashare_monitor.py --once
    python examples/ashare_monitor.py --cycles 100

Prerequisite: broker QMT client logged in on Windows, and
``python examples/ashare_verify_feed.py`` passing.

The loop watches the tape, validates data quality, computes factor signals and
writes human-executable decision tickets to:
    web/ashare_signals.json        (open web/ashare.html to read them)
    reports/ashare_monitor.db      (SQLite history)
    reports/ashare_monitor_journal.jsonl
No broker/trading API is ever called -- see quantforge/ashare/monitor.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.ashare import (  # noqa: E402
    CachedFeed, DataQualityGate, FeedUnavailable, Monitor, XtdataFeed,
    assert_no_execution_path,
)
from quantforge.ashare.config import AShareSettings  # noqa: E402
from quantforge.ashare.rules import CN_TZ  # noqa: E402


def build_feed(settings: AShareSettings, offline: bool):
    f = settings.feed
    if offline:
        return CachedFeed(ROOT / f.get("cache_dir", "data/ashare_cache"))
    return XtdataFeed(
        symbols=settings.symbols, field_map=f.get("field_map", {}),
        market=f.get("market", "SH"), dividend_type=f.get("dividend_type", "front"),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="A-share monitor-only decision support")
    ap.add_argument("--config", default=None)
    ap.add_argument("--once", action="store_true", help="one cycle then exit")
    ap.add_argument("--cycles", type=int, default=None)
    ap.add_argument("--offline", action="store_true", help="use the local cache instead of QMT (no live quotes)")
    args = ap.parse_args()

    forbidden = assert_no_execution_path()
    if forbidden:
        print(f"FATAL: execution calls found in monitor module: {forbidden}")
        return 3

    settings = AShareSettings.load(args.config)
    feed = build_feed(settings, args.offline)
    pre = feed.preflight()
    print("数据源:", json.dumps(pre, ensure_ascii=False))
    if not pre.get("available"):
        print("数据源不可用，拒绝启动监控（不会用模拟行情顶替）。")
        return 2
    if args.offline:
        print("警告：--offline 使用本地缓存快照，不是实时行情；仅用于回放与验收。")

    end = datetime.now(CN_TZ).date()
    start = end - timedelta(days=400)
    try:
        calendar = feed.trading_calendar(start.isoformat(), end.isoformat())
    except FeedUnavailable as exc:
        print(f"交易日历不可用: {exc}")
        return 2
    print("交易日历:", json.dumps(calendar.describe(), ensure_ascii=False))

    gate = DataQualityGate(
        max_stale_seconds=settings.quality.get("max_stale_seconds", 60),
        require_provenance=settings.quality.get("require_provenance", True),
        max_cross_source_diff=settings.quality.get("max_cross_source_diff", 0.005),
    )
    monitor = Monitor(settings.monitor_config(), feed, calendar, gate=gate)
    if args.once:
        cycle = monitor.run_once()
        print(json.dumps(cycle.as_dict(), ensure_ascii=False, indent=2)[:4000])
        return 0
    try:
        monitor.run(max_cycles=args.cycles)
    except KeyboardInterrupt:
        monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
