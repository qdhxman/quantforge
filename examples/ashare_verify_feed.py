"""Verify the QMT/xtquant data connection BEFORE any strategy work.

Run this on the Windows machine with the broker QMT client logged in:

    python examples/ashare_verify_feed.py

It never falls back to synthetic data. If xtquant / the client is missing it
prints the exact remediation steps and exits non-zero.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.ashare import XtdataFeed  # noqa: E402
from quantforge.ashare.config import AShareSettings  # noqa: E402
from quantforge.ashare.rules import CN_TZ  # noqa: E402

REQUIRED_TICK_FIELDS = ("lastPrice", "lastClose", "open", "high", "low", "volume", "amount")


def main() -> int:
    settings = AShareSettings.load()
    f = settings.feed
    feed = XtdataFeed(
        symbols=settings.symbols,
        field_map=f.get("field_map", {}),
        market=f.get("market", "SH"),
        dividend_type=f.get("dividend_type", "front"),
    )
    print("== QMT/xtquant preflight ==")
    pre = feed.preflight()
    print(json.dumps(pre, ensure_ascii=False, indent=2))
    if not pre.get("available"):
        print("\n行情源不可用。绝不退化到模拟数据。请按上面的指引修复后重试。")
        return 2

    end = datetime.now(CN_TZ).date()
    start = end - timedelta(days=120)
    problems = []

    try:
        cal = feed.trading_calendar(start.isoformat(), end.isoformat())
        print(f"\n交易日历: {cal.describe()}")
        if not cal.authoritative:
            problems.append("calendar not authoritative")
    except Exception as exc:
        problems.append(f"trading_calendar failed: {exc!r}")

    try:
        hist = feed.history(settings.symbols[:2], start.isoformat(), end.isoformat())
        for s, rows in hist.items():
            print(f"历史 {s}: {len(rows)} 根, 首={rows[0].date if rows else '-'}, 末={rows[-1].date if rows else '-'}")
            if not rows:
                problems.append(f"{s}: empty history")
    except Exception as exc:
        problems.append(f"history failed: {exc!r}")

    try:
        snap = feed.snapshot(settings.symbols[:2])
        print(f"\n快照返回 {len(snap)} 个标的")
        for s, q in list(snap.items())[:2]:
            print(f"  {s} last={q.last} prev_close={q.prev_close} ts={q.ts} src={q.provenance.source}")
        if not snap:
            problems.append("snapshot returned nothing")
    except Exception as exc:
        problems.append(f"snapshot failed: {exc!r}")

    try:
        client = feed._client()
        raw = client.get_full_tick(settings.symbols[:1]) or {}
        first = next(iter(raw.values()), {}) if raw else {}
        missing = [k for k in REQUIRED_TICK_FIELDS if k not in first]
        print(f"\n字段自检: 实际字段 {sorted(first)[:20]}")
        if missing:
            print(f"缺少字段 {missing} -> 在 config/ashare/strategy.json 的 feed.field_map 中校准映射")
            problems.append(f"field mismatch: {missing}")
    except Exception as exc:
        problems.append(f"field probe failed: {exc!r}")

    ins = feed.instruments(settings.symbols[:3])
    print(f"\n标的信息: {[(s, i.name, i.board, i.is_st) for s, i in ins.items()]}")

    if problems:
        print("\n自检未通过:")
        for p in problems:
            print("  -", p)
        return 1
    print("\n自检通过。下一步用 scripts/ashare_pipeline.py 落盘缓存并跑严格回测。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
