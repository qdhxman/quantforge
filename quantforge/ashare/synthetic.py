"""SYNTHETIC A-share-shaped test fixtures. NOT real market data, ever.

Used by unit tests and scripts/ashare_pipeline.py to prove the pipeline runs
end-to-end without pretending to have a live feed. The cache manifest is
stamped ``license="synthetic-test-fixture"`` and ``calendar_authoritative=False``
so no production path can accidentally consume it as real data.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, time, timedelta
from typing import Sequence

from .feeds import ABar, Provenance, Snapshot
from .rules import CN_TZ, Instrument, TradingCalendar, board_of, price_limit_pct, price_limits

SYNTHETIC_LICENSE = "synthetic-test-fixture"


def build_synthetic_fixture(
    symbols: Sequence[str], n_bars: int = 504, seed: int = 20261106,
    end_date: str | None = None, with_dividend_jump: bool = True,
) -> tuple[dict[str, list[ABar]], TradingCalendar, dict[str, Instrument], dict[str, Snapshot]]:
    """Return (bars, calendar, instruments, snapshots).

    Includes one deliberate ex-dividend price jump so the adjusted-price
    calibre can be verified, and a few suspension days.
    """
    end = date.fromisoformat(end_date) if end_date else datetime.now(CN_TZ).date()
    dates: list[str] = []
    d = end - timedelta(days=int(n_bars * 1.6))
    while len(dates) < n_bars:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    calendar = TradingCalendar(dates, "SYNTHETIC weekday fixture (NOT an exchange calendar)",
                               authoritative=False)

    bars: dict[str, list[ABar]] = {}
    instruments: dict[str, Instrument] = {}
    snapshots: dict[str, Snapshot] = {}
    ts = datetime.combine(end, time(10, 0), CN_TZ).isoformat(timespec="seconds")

    for k, raw in enumerate(symbols):
        rng = random.Random(seed + k * 7919)
        board = board_of(raw)
        start_px = 10.0 + 8.0 * (k + 1)
        adj_close = start_px
        rows: list[ABar] = []
        is_st = (k == len(symbols) - 1)
        pct = price_limit_pct(raw, is_st=is_st, as_of=end)
        for t, day in enumerate(dates):
            drift = 0.05 + 0.14 * math.sin(t / 46.0 + k)
            vol = 0.16 + 0.06 * (k % 3)
            ret = drift / 252.0 + vol / math.sqrt(252.0) * rng.gauss(0, 1)
            adj_close = max(1.0, adj_close * math.exp(ret))
            # A corporate action: raw price halves at t=250 while the adjusted
            # series stays continuous. factor = adj_close / raw_close.
            factor = 0.5 if (with_dividend_jump and t < 250) else 1.0
            close = adj_close / factor
            op = close * (1 + rng.uniform(-0.006, 0.006))
            hi = max(op, close) * (1 + abs(ret) * 0.5 + 0.003)
            lo = min(op, close) * (1 - abs(ret) * 0.5 - 0.003)
            suspended = (t % 97 == 0 and t > 0)
            prev = rows[-1].close if rows else close
            lo_lim, hi_lim = price_limits(prev, pct)
            rows.append(ABar(
                date=day, open=round(op, 4), high=round(hi, 4), low=round(lo, 4),
                close=round(close, 4), volume=round(1e6 * (1 + 8 * abs(ret)), 2),
                amount=round(close * 1e6 * (1 + 8 * abs(ret)), 2),
                adj_close=round(adj_close, 4), adj_factor=factor,
                suspended=suspended, is_st=is_st,
                limit_up=hi_lim, limit_down=lo_lim,
            ))
        bars[raw] = rows
        instruments[raw] = Instrument(symbol=raw, name=f"SYNTHETIC-{raw}", board=board,
                                      is_st=is_st, listing_date=dates[0])
        last, prev = rows[-1], rows[-2]
        lo_lim, hi_lim = price_limits(prev.close, pct)
        snapshots[raw] = Snapshot(
            symbol=raw, ts=ts, last=last.close, prev_close=prev.close, open=last.open,
            high=last.high, low=last.low, volume=last.volume, amount=last.amount,
            suspended=False, is_st=is_st, limit_up=hi_lim, limit_down=lo_lim,
            provenance=Provenance(source="SYNTHETIC-FIXTURE", as_of=ts,
                                  license=SYNTHETIC_LICENSE, is_live=False,
                                  note="NOT REAL MARKET DATA"),
        )
    return bars, calendar, instruments, snapshots
