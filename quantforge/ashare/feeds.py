"""Pluggable A-share market-data layer.

Design rules, in order of importance:

1. NEVER fabricate or simulate a live feed. ``XtdataFeed`` raises a precise,
   actionable error when the QMT client / xtquant package is unavailable. A
   monitoring system that quietly falls back to made-up prices is worse than
   one that stops.
2. Backtest and live monitoring read the SAME cached, provenance-tagged data.
   That is what "QMT same-source" actually buys you: no history/realtime
   calibre drift.
3. Every snapshot/batch passes ``DataQualityGate`` before it can generate a
   signal. Unhealthy data suppresses signals and raises an alert.

This module is stdlib-only. pandas is only touched inside ``XtdataFeed`` when
the broker client is actually present.
"""

from __future__ import annotations

import csv
import json
import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .rules import CN_TZ, Instrument, TradingCalendar, price_limit_pct, price_limits

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Provenance:
    source: str                 # e.g. "QMT/xtquant", "TusharePro", "local-cache"
    as_of: str                  # ISO8601 with +08:00
    license: str = "broker-terminal"   # research / broker-terminal / commercial / public
    is_live: bool = False
    latency_ms: float | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ABar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0
    adj_close: float = 0.0      # forward-adjusted, used for FACTOR computation
    adj_factor: float = 1.0
    suspended: bool = False
    is_st: bool = False
    limit_up: float | None = None
    limit_down: float | None = None

    def factor_price(self) -> float:
        return self.adj_close or self.close

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Snapshot:
    symbol: str
    ts: str
    last: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    suspended: bool = False
    is_st: bool = False
    limit_up: float | None = None
    limit_down: float | None = None
    bid1: float = 0.0
    ask1: float = 0.0
    provenance: Provenance = field(default_factory=lambda: Provenance("unknown", ""))

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


class FeedUnavailable(RuntimeError):
    """Raised when a required data source cannot be reached. Never swallowed."""


class MarketDataFeed(ABC):
    name: str = "abstract"

    @abstractmethod
    def history(self, symbols: Sequence[str], start: str, end: str) -> dict[str, list[ABar]]:
        """Forward-adjusted daily bars, ascending by date."""

    @abstractmethod
    def snapshot(self, symbols: Sequence[str]) -> dict[str, Snapshot]:
        """Latest intraday snapshot with provenance."""

    @abstractmethod
    def trading_calendar(self, start: str, end: str) -> TradingCalendar:
        """Authoritative trading-day set from the data provider."""

    @abstractmethod
    def instruments(self, symbols: Sequence[str]) -> dict[str, Instrument]:
        ...

    def preflight(self) -> dict:
        return {"feed": self.name, "available": True, "note": ""}


# --------------------------------------------------------------------------- #
# QMT / xtquant adapter
# --------------------------------------------------------------------------- #
XTQUANT_INSTALL_GUIDE = (
    "QMT/xtquant 不可用。真实行情必须来自券商终端，本系统不会用模拟数据顶替。\n"
    "  1) 在 Windows 64 位机器安装你券商的 QMT 客户端并用资金账号登录；\n"
    "  2) 确认 xtquant 可用：python -c \"from xtquant import xtdata; print(xtdata.get_trading_dates('SH'))\";\n"
    "  3) 若客户端自带 Python 环境，用该解释器运行，或把 <QMT>/bin.x64/Lib/site-packages 加入 PYTHONPATH；\n"
    "  4) 首次使用先跑 quantforge-ashare cache-build 把行情落盘，回测与监控再共用该缓存；\n"
    "  5) 行情权限与量化交易权限是两回事，监控只需行情权限；自动下单才需 QMT 交易权限 + 程序化报备。\n"
    "字段映射随券商 xtquant 版本可能不同，请用 config/ashare/feed.json 的 field_map 校准，"
    "并以 examples/ashare_verify_feed.py 做字段自检。"
)


class XtdataFeed(MarketDataFeed):
    """Broker QMT/xtquant adapter. Lazy import; fails loudly, never fakes data.

    ``field_map`` lets you correct field names without editing library code,
    because broker xtquant builds are not identical.
    """

    DEFAULT_FIELD_MAP = {
        "open": "open", "high": "high", "low": "low", "close": "close",
        "volume": "volume", "amount": "amount",
        "tick_last": "lastPrice", "tick_prev_close": "lastClose",
        "tick_open": "open", "tick_high": "high", "tick_low": "low",
        "tick_volume": "volume", "tick_amount": "amount",
        "tick_bid1": "bidPrice", "tick_ask1": "askPrice", "tick_time": "timetag",
    }

    def __init__(self, symbols: Sequence[str], field_map: dict[str, str] | None = None,
                 market: str = "SH", dividend_type: str = "front", xtdata: Any | None = None):
        self.symbols = [str(s) for s in symbols]
        self.field_map = {**self.DEFAULT_FIELD_MAP, **(field_map or {})}
        self.market = market
        self.dividend_type = dividend_type
        self._xtdata = xtdata

    @property
    def name(self) -> str:
        return "QMT/xtquant"

    def _client(self):
        if self._xtdata is not None:
            return self._xtdata
        try:
            from xtquant import xtdata as _xt  # type: ignore
        except ImportError as exc:
            raise FeedUnavailable(XTQUANT_INSTALL_GUIDE) from exc
        self._xtdata = _xt
        return _xt

    def preflight(self) -> dict:
        try:
            xt = self._client()
        except FeedUnavailable as exc:
            return {"feed": self.name, "available": False, "note": str(exc)}
        try:
            dates = xt.get_trading_dates(self.market)
            n = len(dates) if dates is not None else 0
            return {"feed": self.name, "available": n > 0, "trading_dates": n,
                    "note": "" if n else "get_trading_dates returned empty; QMT client may not be logged in"}
        except Exception as exc:  # broker API variance must surface, not hide
            return {"feed": self.name, "available": False, "note": f"xtquant probe failed: {exc!r}"}

    def trading_calendar(self, start: str, end: str) -> TradingCalendar:
        xt = self._client()
        raw = xt.get_trading_dates(self.market, start_time=start.replace("-", ""), end_time=end.replace("-", ""))
        if not raw:
            raise FeedUnavailable("QMT returned no trading dates; refusing to guess holidays")
        days = []
        for item in raw:
            if isinstance(item, (int, float)):
                n = int(item)
                # Broker builds differ: milliseconds (1.7e12), seconds (1.7e9)
                # or plain YYYYMMDD (20260105). Handle all three explicitly.
                if n >= 1e12:
                    days.append(datetime.fromtimestamp(n / 1000, CN_TZ).date().isoformat())
                elif 1e9 <= n < 1e12:
                    days.append(datetime.fromtimestamp(n, CN_TZ).date().isoformat())
                else:
                    s = f"{n:08d}"
                    days.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
            else:
                s = str(item).replace("-", "")[:8]
                days.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
        return TradingCalendar(days, f"{self.name}:{self.market}", authoritative=True)

    def history(self, symbols: Sequence[str], start: str, end: str) -> dict[str, list[ABar]]:
        xt = self._client()
        fm = self.field_map
        fields = [fm[k] for k in ("open", "high", "low", "close", "volume", "amount")]
        raw = xt.get_market_data_ex(
            field_list=fields, stock_list=list(symbols), period="1d",
            start_time=start.replace("-", ""), end_time=end.replace("-", ""),
            count=-1, dividend_type=self.dividend_type, fill_data=False,
        )
        out: dict[str, list[ABar]] = {}
        for symbol in symbols:
            frame = raw.get(symbol) if isinstance(raw, dict) else None
            if frame is None or len(frame) == 0:
                out[symbol] = []
                continue
            rows = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)
            idx = list(frame.index) if hasattr(frame, "index") else [r.get("date", "") for r in rows]
            bars = []
            for i, r in enumerate(rows):
                d = str(idx[i]).replace("-", "")[:8]
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                close = float(r.get(fm["close"], 0) or 0)
                bars.append(ABar(
                    date=d, open=float(r.get(fm["open"], 0) or 0),
                    high=float(r.get(fm["high"], 0) or 0), low=float(r.get(fm["low"], 0) or 0),
                    close=close, volume=float(r.get(fm["volume"], 0) or 0),
                    amount=float(r.get(fm["amount"], 0) or 0), adj_close=close,
                ))
            out[symbol] = sorted(bars, key=lambda b: b.date)
        return out

    def snapshot(self, symbols: Sequence[str]) -> dict[str, Snapshot]:
        xt = self._client()
        fm = self.field_map
        raw = xt.get_full_tick(list(symbols)) or {}
        now = datetime.now(CN_TZ).isoformat(timespec="seconds")
        out: dict[str, Snapshot] = {}
        for symbol in symbols:
            t = raw.get(symbol)
            if not t:
                continue
            bid = t.get(fm["tick_bid1"]) or 0
            ask = t.get(fm["tick_ask1"]) or 0
            if isinstance(bid, (list, tuple)):
                bid = bid[0] if bid else 0
            if isinstance(ask, (list, tuple)):
                ask = ask[0] if ask else 0
            prev = float(t.get(fm["tick_prev_close"], 0) or 0)
            pct = price_limit_pct(symbol, is_st=False, as_of=datetime.now(CN_TZ).date())
            lo, hi = price_limits(prev, pct)
            out[symbol] = Snapshot(
                symbol=symbol, ts=now, last=float(t.get(fm["tick_last"], 0) or 0),
                prev_close=prev, open=float(t.get(fm["tick_open"], 0) or 0),
                high=float(t.get(fm["tick_high"], 0) or 0), low=float(t.get(fm["tick_low"], 0) or 0),
                volume=float(t.get(fm["tick_volume"], 0) or 0), amount=float(t.get(fm["tick_amount"], 0) or 0),
                bid1=float(bid), ask1=float(ask), limit_up=hi, limit_down=lo,
                provenance=Provenance(source=self.name, as_of=now, is_live=True, license="broker-terminal"),
            )
        return out

    def instruments(self, symbols: Sequence[str]) -> dict[str, Instrument]:
        xt = self._client()
        out = {}
        for symbol in symbols:
            d = xt.get_instrument_detail(symbol) or {}
            name = str(d.get("InstrumentName", ""))
            out[symbol] = Instrument(
                symbol=symbol, name=name, is_st=("ST" in name.upper()),
                listing_date=str(d.get("OpenDate", "")),
            )
        return out


# --------------------------------------------------------------------------- #
# Local, provenance-tagged cache (single source for both backtest and monitor)
# --------------------------------------------------------------------------- #
class CachedFeed(MarketDataFeed):
    """Reads a directory written by :func:`write_cache`.

    Layout::

        manifest.json          schema, source, built_at, license, date range
        calendar.csv           one authoritative trading day per row
        instruments.csv        symbol,name,board,is_st,listing_date,delisting
        bars/<symbol>.csv      date,open,high,low,close,volume,amount,adj_close,...
        snapshots.json         optional latest intraday snapshots
    """

    name = "local-cache"

    def __init__(self, root: str | Path):
        self.root = Path(root)
        manifest = self.root / "manifest.json"
        if not manifest.exists():
            raise FeedUnavailable(f"cache not found: {manifest}. Run quantforge-ashare cache-build first")
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        if self.manifest.get("schema") != SCHEMA_VERSION:
            raise FeedUnavailable(f"cache schema {self.manifest.get('schema')} != {SCHEMA_VERSION}")
        self.provenance = Provenance(
            source=self.manifest.get("source", "local-cache"),
            as_of=self.manifest.get("built_at", ""),
            license=self.manifest.get("license", "unknown"),
            is_live=False,
            note=self.manifest.get("note", ""),
        )

    def preflight(self) -> dict:
        return {"feed": self.name, "available": True, "source": self.provenance.source,
                "built_at": self.provenance.as_of, "license": self.provenance.license,
                "note": "offline snapshot, NOT live"}

    def trading_calendar(self, start: str, end: str) -> TradingCalendar:
        p = self.root / "calendar.csv"
        with p.open(encoding="utf-8") as fh:
            days = [r["date"] for r in csv.DictReader(fh)]
        return TradingCalendar(days, f"{self.provenance.source}:calendar",
                               authoritative=self.manifest.get("calendar_authoritative", True))

    def instruments(self, symbols: Sequence[str]) -> dict[str, Instrument]:
        p = self.root / "instruments.csv"
        with p.open(encoding="utf-8") as fh:
            rows = {r["symbol"]: r for r in csv.DictReader(fh)}
        out = {}
        for s in symbols:
            r = rows.get(s)
            if r:
                out[s] = Instrument(symbol=s, name=r.get("name", ""), board=r.get("board", ""),
                                    is_st=r.get("is_st", "0") in ("1", "true", "True"),
                                    is_delisting=r.get("is_delisting", "0") in ("1", "true", "True"),
                                    listing_date=r.get("listing_date", ""))
        return out

    def history(self, symbols: Sequence[str], start: str, end: str) -> dict[str, list[ABar]]:
        out: dict[str, list[ABar]] = {}
        for s in symbols:
            p = self.root / "bars" / f"{s}.csv"
            if not p.exists():
                out[s] = []
                continue
            bars = []
            with p.open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            for r in rows:
                if not (start <= r["date"] <= end):
                    continue
                bars.append(ABar(
                    date=r["date"], open=float(r["open"]), high=float(r["high"]),
                    low=float(r["low"]), close=float(r["close"]),
                    volume=float(r.get("volume", 0) or 0), amount=float(r.get("amount", 0) or 0),
                    adj_close=float(r.get("adj_close", 0) or r["close"]),
                    adj_factor=float(r.get("adj_factor", 1) or 1),
                    suspended=r.get("suspended", "0") in ("1", "true", "True"),
                    is_st=r.get("is_st", "0") in ("1", "true", "True"),
                    limit_up=float(r["limit_up"]) if r.get("limit_up") else None,
                    limit_down=float(r["limit_down"]) if r.get("limit_down") else None,
                ))
            out[s] = sorted(bars, key=lambda b: b.date)
        return out

    def snapshot(self, symbols: Sequence[str]) -> dict[str, Snapshot]:
        p = self.root / "snapshots.json"
        if not p.exists():
            raise FeedUnavailable("no snapshots.json in cache; monitor needs live QMT feed, not a static cache")
        raw = json.loads(p.read_text(encoding="utf-8"))
        out = {}
        for s in symbols:
            if s not in raw:
                continue
            d = dict(raw[s])
            d["provenance"] = Provenance(**d.get("provenance", {})) if isinstance(d.get("provenance"), dict) \
                else Provenance(source=self.provenance.source, as_of=d.get("ts", ""), is_live=False)
            out[s] = Snapshot(**d)
        return out


def write_cache(root: str | Path, bars: dict[str, Sequence[ABar]], calendar: TradingCalendar,
                instruments: dict[str, Instrument], *, source: str, license: str,
                note: str = "", snapshots: dict[str, Snapshot] | None = None) -> Path:
    """Persist a feed snapshot so backtest and monitor never disagree."""
    root = Path(root)
    (root / "bars").mkdir(parents=True, exist_ok=True)
    now = datetime.now(CN_TZ).isoformat(timespec="seconds")
    dates = sorted({b.date for rows in bars.values() for b in rows})
    (root / "manifest.json").write_text(json.dumps({
        "schema": SCHEMA_VERSION, "source": source, "license": license, "note": note,
        "built_at": now, "symbols": list(bars), "start": dates[0] if dates else "",
        "end": dates[-1] if dates else "", "bars": sum(len(v) for v in bars.values()),
        "calendar_authoritative": calendar.authoritative,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with (root / "calendar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date"])
        for d in calendar.dates:
            w.writerow([d])
    with (root / "instruments.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "name", "board", "is_st", "is_delisting", "listing_date"])
        for s, ins in instruments.items():
            w.writerow([s, ins.name, ins.board, int(ins.is_st), int(ins.is_delisting), ins.listing_date])
    for s, rows in bars.items():
        with (root / "bars" / f"{s}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(ABar.__dataclass_fields__))
            w.writeheader()
            for b in rows:
                w.writerow(b.as_dict())
    if snapshots is not None:
        (root / "snapshots.json").write_text(
            json.dumps({k: v.as_dict() for k, v in snapshots.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# Data quality gate
# --------------------------------------------------------------------------- #
class DataQualityError(RuntimeError):
    pass


@dataclass
class QualityReport:
    ok: bool
    checked_at: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    def assert_healthy(self) -> None:
        if not self.ok:
            raise DataQualityError("data quality gate failed: " + " | ".join(self.errors[:5]))


class DataQualityGate:
    """Reject data that must not be allowed to produce a trading signal.

    Fails closed: any ERROR suppresses signals. Warnings are recorded but do
    not block (e.g. a single non-critical missing amount field).
    """

    def __init__(self, max_stale_seconds: int = 60, require_provenance: bool = True,
                 max_cross_source_diff: float = 0.005):
        self.max_stale_seconds = max_stale_seconds
        self.require_provenance = require_provenance
        self.max_cross_source_diff = max_cross_source_diff

    def check_snapshots(self, snapshots: dict[str, Snapshot], instruments: dict[str, Instrument],
                        now: datetime | None = None) -> QualityReport:
        now = now or datetime.now(CN_TZ)
        errors: list[str] = []
        warnings: list[str] = []
        counts = {"symbols": 0, "stale": 0, "bad_price": 0, "bad_ohlc": 0, "limit_breach": 0,
                  "missing_provenance": 0, "suspended": 0}
        for sym, s in snapshots.items():
            counts["symbols"] += 1
            if self.require_provenance and (not s.provenance.source or s.provenance.source == "unknown"):
                errors.append(f"{sym}: missing provenance"); counts["missing_provenance"] += 1
            try:
                ts = datetime.fromisoformat(s.ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=CN_TZ)
                age = (now.astimezone(CN_TZ) - ts.astimezone(CN_TZ)).total_seconds()
                if age > self.max_stale_seconds:
                    errors.append(f"{sym}: stale quote {age:.0f}s > {self.max_stale_seconds}s")
                    counts["stale"] += 1
                elif age < -30:
                    errors.append(f"{sym}: quote timestamp in the future ({age:.0f}s)")
            except ValueError:
                errors.append(f"{sym}: unparseable ts {s.ts!r}")
            if s.last <= 0 or s.prev_close <= 0:
                errors.append(f"{sym}: non-positive price"); counts["bad_price"] += 1
                continue
            if s.high < max(s.open, s.last, s.low) or s.low > min(s.open, s.last, s.high) or s.low <= 0:
                errors.append(f"{sym}: inconsistent OHLC"); counts["bad_ohlc"] += 1
            if s.volume < 0 or s.amount < 0:
                errors.append(f"{sym}: negative volume/amount")
            ins = instruments.get(sym)
            pct = price_limit_pct(sym, is_st=(ins.is_st if ins else s.is_st), as_of=now.date())
            lo, hi = price_limits(s.prev_close, pct)
            if lo is not None and hi is not None and not (lo - 0.011 <= s.last <= hi + 0.011):
                errors.append(f"{sym}: last {s.last} outside limit [{lo}, {hi}]")
                counts["limit_breach"] += 1
            if s.suspended:
                counts["suspended"] += 1
                warnings.append(f"{sym}: suspended, no trading allowed")
        return QualityReport(not errors, now.isoformat(timespec="seconds"), errors, warnings, counts)

    def check_history(self, bars: dict[str, list[ABar]], calendar: TradingCalendar,
                      snapshots: dict[str, Snapshot] | None = None) -> QualityReport:
        from datetime import datetime as dt
        errors: list[str] = []
        warnings: list[str] = []
        counts = {"symbols": 0, "bars": 0, "duplicates": 0, "missing_days": 0,
                  "bad_ohlc": 0, "bad_adj": 0, "cross_source_diff": 0}
        expected = set(calendar.dates)
        for sym, rows in bars.items():
            counts["symbols"] += 1
            seen: set[str] = set()
            for b in rows:
                counts["bars"] += 1
                if b.date in seen:
                    errors.append(f"{sym}: duplicate bar {b.date}"); counts["duplicates"] += 1
                seen.add(b.date)
                if not b.suspended:
                    if b.high < max(b.open, b.close, b.low) or b.low > min(b.open, b.close, b.high) or b.low <= 0:
                        errors.append(f"{sym} {b.date}: inconsistent OHLC"); counts["bad_ohlc"] += 1
                    if b.close <= 0 or b.volume < 0:
                        errors.append(f"{sym} {b.date}: non-positive close / negative volume")
                if b.adj_factor <= 0 or b.factor_price() <= 0:
                    errors.append(f"{sym} {b.date}: invalid adj factor/price"); counts["bad_adj"] += 1
            if rows:
                span = set(calendar.between(rows[0].date, rows[-1].date))
                missing = sorted(span - seen)
                if missing:
                    warnings.append(f"{sym}: {len(missing)} calendar days without bars (suspension?)")
                    counts["missing_days"] += len(missing)
            if snapshots and sym in snapshots and rows:
                snap = snapshots[sym]
                last = rows[-1]
                if last.close > 0 and abs(snap.last - last.close) / last.close > self.max_cross_source_diff:
                    errors.append(f"{sym}: snapshot {snap.last} vs history close {last.close} diverge")
                    counts["cross_source_diff"] += 1
        if not calendar.authoritative:
            warnings.append("calendar is NOT authoritative (weekday fallback): backtest results are not production-grade")
        return QualityReport(not errors, dt.now(CN_TZ).isoformat(timespec="seconds"), errors, warnings, counts)
