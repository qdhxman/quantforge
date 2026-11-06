"""OHLCV data model, CSV/Yahoo adapters and a deterministic sample generator.

The bundled sample is *synthetic* on purpose: no licence issues, no network,
and every backtest in the docs is reproducible. Swap in real bars with
``load_csv`` or ``load_yfinance``.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


Dataset = dict[str, list[Bar]]


def _weekdays(start: str, count: int) -> list[str]:
    d = date.fromisoformat(start)
    out: list[str] = []
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# symbol -> (start_price, annual drift, annual vol, phase, base volume)
SAMPLE_UNIVERSE: dict[str, tuple[float, float, float, float, float]] = {
    "AAPL": (165.0, 0.07, 0.22, 0.3, 4.2e6),
    "MSFT": (370.0, 0.08, 0.20, 1.7, 2.6e6),
    "NVDA": (48.0, 0.15, 0.35, 2.9, 9.0e6),
    "SPY": (470.0, 0.05, 0.13, 4.1, 7.0e6),
}


def generate_synthetic(
    n_bars: int = 504,
    seed: int = 20260101,
    start: str = "2024-01-02",
    universe: dict[str, tuple[float, float, float, float, float]] | None = None,
) -> Dataset:
    """Regime-switching geometric Brownian motion with deterministic seed.

    Drift oscillates and volatility clusters, so trend, reversal and volatility
    factors genuinely disagree on some bars -- which is what makes factor
    selection interesting in the demo.
    """
    universe = universe or SAMPLE_UNIVERSE
    dates = _weekdays(start, n_bars)
    data: Dataset = {}
    for s_idx, (symbol, (s0, drift0, vol0, phase, base_vol)) in enumerate(universe.items()):
        rng = random.Random(seed + s_idx * 7919)
        close = s0
        bars: list[Bar] = []
        for t, day in enumerate(dates):
            # A shared bear regime around bar ~310 so the sample contains a real
            # drawdown: a demo with only an uptrend cannot show why risk controls
            # or defensive factors exist.
            bear = -0.85 * math.exp(-((t - 310) / 45.0) ** 2) * (vol0 / 0.22)
            drift = drift0 + 0.16 * math.sin(t / 47.0 + phase) + 0.05 * math.sin(t / 13.0 + phase) + bear
            vol = vol0 * (1.0 + 0.45 * abs(math.sin(t / 23.0 + phase)) + 0.6 * abs(bear))
            shock = rng.gauss(0.0, 1.0)
            ret = drift / 252.0 + vol / math.sqrt(252.0) * shock
            prev_close = close
            close = max(1.0, close * math.exp(ret))
            gap = rng.uniform(-0.0035, 0.0035)
            op = prev_close * (1.0 + gap)
            spread = abs(ret) * 0.55 + rng.uniform(0.001, 0.006)
            hi = max(op, close) * (1.0 + spread)
            lo = min(op, close) * (1.0 - spread)
            volume = base_vol * (1.0 + 14.0 * abs(ret) + rng.uniform(-0.18, 0.18))
            bars.append(
                Bar(
                    date=day,
                    open=round(op, 4),
                    high=round(hi, 4),
                    low=round(lo, 4),
                    close=round(close, 4),
                    volume=round(volume, 2),
                )
            )
        data[symbol] = bars
    return data


def load_csv(path: str | Path) -> Dataset:
    """Read a long-format CSV (one row per symbol per day).

    Required columns: date, open, high, low, close, volume.
    Optional ``symbol`` column; if absent the file stem is used as the symbol.
    Columns are case-insensitive; ``adj_close`` may stand in for ``close``.
    """
    p = Path(path)
    data: Dataset = {}
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"Empty CSV: {p}")
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        close_col = cols.get("close") or cols.get("adj_close")
        if not close_col:
            raise ValueError(f"CSV needs a close/adj_close column: {p}")
        for row in reader:
            def f(key: str, default: float | None = None) -> float:
                raw = row.get(cols.get(key, ""), "")
                if raw is None or str(raw).strip() == "":
                    if default is None:
                        raise ValueError(f"Missing value for '{key}' in {p}")
                    return default
                return float(raw)

            c = f("close")
            o = f("open", c)
            h = f("high", max(o, c))
            lo = f("low", min(o, c))
            v = f("volume", 0.0)
            d = (row.get(cols.get("date", "")) or "").strip()
            sym = (row.get(cols.get("symbol", "")) or p.stem).strip()
            if not d:
                raise ValueError(f"Missing date in {p}")
            data.setdefault(sym, []).append(Bar(d, o, h, lo, c, v))
    for symbol in data:
        data[symbol].sort(key=lambda b: b.date)
    return data


def load_yfinance(symbols: Iterable[str], start: str, end: str) -> Dataset:
    """Optional real-data adapter. Requires ``pip install -e '.[market]'``."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:
        raise RuntimeError("install the market extra: pip install -e '.[market]'") from exc
    data: Dataset = {}
    raw = yf.download(list(symbols), start=start, end=end, group_by="ticker", auto_adjust=True, progress=False)
    for symbol in symbols:
        frame = raw[symbol].dropna()
        data[symbol] = [
            Bar(str(idx.date()), float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), float(r["Volume"]))
            for idx, r in frame.iterrows()
        ]
    return data


def date_index(bars: list[Bar]) -> dict[str, int]:
    return {b.date: i for i, b in enumerate(bars)}


def slice_dataset(data: Dataset, start: str | None = None, end: str | None = None) -> Dataset:
    out: Dataset = {}
    for symbol, bars in data.items():
        out[symbol] = [b for b in bars if (not start or b.date >= start) and (not end or b.date <= end)]
    return out


def dataset_to_jsonable(data: Dataset) -> dict[str, list[dict[str, Any]]]:
    return {symbol: [b.as_dict() for b in bars] for symbol, bars in data.items()}
