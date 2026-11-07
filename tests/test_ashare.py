"""A-share production-path tests. All data here is explicitly synthetic."""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.ashare import (  # noqa: E402
    ABar, AShareBacktestEngine, CachedFeed, DataQualityGate, FeedUnavailable, Instrument,
    MarketDataFeed, Monitor, Provenance, Snapshot, TradingCalendar, XtdataFeed,
    assert_no_execution_path, board_of, build_factor_panel, calculate_fees,
    compute_ic_ir, layered_backtest, market_phase, normalise_qty, overfit_diagnosis,
    price_limit_pct, price_limits, walk_forward, write_cache,
)
from quantforge.ashare.config import AShareSettings  # noqa: E402
from quantforge.ashare.monitor import MonitorConfig  # noqa: E402
from quantforge.ashare.rules import CN_TZ, FeeSchedule  # noqa: E402
from quantforge.ashare.synthetic import build_synthetic_fixture  # noqa: E402
from quantforge.config import FactorSpec, SignalConfig  # noqa: E402
from quantforge.journal import Journal  # noqa: E402

SYMS = ["600519", "000001", "300750", "688981"]


def _settings(**kw):
    s = AShareSettings.load()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _calendar(dates):
    return TradingCalendar.from_dates(dates, "explicit test fixture")


def _days(n, start=date(2026, 1, 1)):
    """Consecutive calendar dates; the test calendar declares them trading days."""
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


class RuleTests(unittest.TestCase):
    def test_board_identification(self):
        self.assertEqual(board_of("600519.SH"), "MAIN")
        self.assertEqual(board_of("000001"), "MAIN")
        self.assertEqual(board_of("300750"), "CHINEXT")
        self.assertEqual(board_of("688981"), "STAR")

    def test_st_limit_changed_on_2026_07_06(self):
        self.assertAlmostEqual(price_limit_pct("600519", is_st=True, as_of=date(2026, 7, 5)), 0.05)
        self.assertAlmostEqual(price_limit_pct("600519", is_st=True, as_of=date(2026, 7, 6)), 0.10)
        self.assertAlmostEqual(price_limit_pct("300750", is_st=True, as_of=date(2026, 7, 6)), 0.20)
        self.assertAlmostEqual(price_limit_pct("688981", is_st=True, as_of=date(2026, 7, 6)), 0.20)

    def test_ipo_and_regular_limits(self):
        self.assertIsNone(price_limit_pct("688981", listing_day=1, as_of=date(2026, 7, 6)))
        self.assertAlmostEqual(price_limit_pct("688981", listing_day=6), 0.20)
        self.assertAlmostEqual(price_limit_pct("600519"), 0.10)
        lo, hi = price_limits(10.0, 0.10)
        self.assertEqual((lo, hi), (9.0, 11.0))

    def test_lot_rules_differ_by_board(self):
        self.assertEqual(normalise_qty("600519", 250, "BUY")[0], 200)
        self.assertEqual(normalise_qty("688981", 250, "BUY")[0], 250)   # 1-share increment
        self.assertEqual(normalise_qty("688981", 150, "BUY")[0], 0)      # below 200
        self.assertEqual(normalise_qty("600519", 150, "SELL", held=180)[0], 180)

    def test_fee_schedule(self):
        small = calculate_fees("BUY", 10.0, 100, FeeSchedule())
        self.assertEqual(small.commission, 5.0)          # minimum CNY 5
        self.assertEqual(small.stamp_tax, 0.0)           # buy side has no stamp tax
        self.assertAlmostEqual(small.transfer_fee, 1000 * 0.00001)
        sell = calculate_fees("SELL", 10.0, 100, FeeSchedule())
        self.assertAlmostEqual(sell.stamp_tax, 1000 * 0.0005)
        big = calculate_fees("BUY", 20.0, 10000, FeeSchedule())
        self.assertAlmostEqual(big.commission, 200000 * 0.00025)

    def test_market_phase(self):
        today = date(2026, 11, 6)
        self.assertEqual(market_phase(datetime.combine(today, time(9, 20), CN_TZ)), "OPEN_CALL_AUCTION")
        self.assertEqual(market_phase(datetime.combine(today, time(10, 0), CN_TZ)), "CONTINUOUS_AM")
        self.assertEqual(market_phase(datetime.combine(today, time(14, 58), CN_TZ)), "CLOSE_CALL_AUCTION")
        self.assertEqual(market_phase(datetime.combine(today, time(15, 10), CN_TZ)), "AFTER_HOURS_FIXED_PRICE")
        self.assertEqual(market_phase(datetime.combine(today, time(3, 0), CN_TZ)), "CLOSED")

    def test_unverified_calendar_is_flagged(self):
        c = TradingCalendar.weekday_fallback("2026-01-01", "2026-01-31")
        self.assertFalse(c.authoritative)
        self.assertIn("NOT_AUTHORITATIVE", c.source)


class FeedTests(unittest.TestCase):
    def test_cache_roundtrip(self):
        bars, cal, ins, snaps = build_synthetic_fixture(SYMS, n_bars=60)
        with tempfile.TemporaryDirectory() as d:
            write_cache(d, bars, cal, ins, source="SYNTHETIC-FIXTURE",
                        license="synthetic-test-fixture", snapshots=snaps)
            feed = CachedFeed(d)
            self.assertEqual(set(feed.instruments(SYMS)), set(SYMS))
            self.assertEqual(len(feed.history(SYMS, cal.dates[0], cal.dates[-1])["600519"]), 60)
            self.assertEqual(len(feed.snapshot(SYMS)), len(SYMS))
            self.assertFalse(feed.trading_calendar(cal.dates[0], cal.dates[-1]).authoritative)
            pre = feed.preflight()
            self.assertIn("NOT live", pre["note"])

    def test_quality_gate_rejects_stale_and_bad_ohlc(self):
        bars, _, ins, snaps = build_synthetic_fixture(SYMS, n_bars=10)
        now = datetime.now(CN_TZ)
        snaps = {k: Snapshot(**{**v.__dict__, "ts": now.isoformat(timespec="seconds")})
                 for k, v in snaps.items()}
        gate = DataQualityGate(max_stale_seconds=60)
        good = gate.check_snapshots(snaps, ins, now)
        self.assertTrue(good.ok, msg=str(good.errors))

        stale = dict(snaps)
        s = stale["600519"]
        stale["600519"] = Snapshot(**{**s.__dict__, "ts": (now - timedelta(hours=2)).isoformat()})
        bad = gate.check_snapshots(stale, ins, now)
        self.assertFalse(bad.ok)
        self.assertIn("stale", " ".join(bad.errors))

        broken = dict(snaps)
        s = broken["600519"]
        broken["600519"] = Snapshot(**{**s.__dict__, "high": 0.01})
        self.assertFalse(gate.check_snapshots(broken, ins, now).ok)

    def test_quality_gate_rejects_duplicate_bars(self):
        bars, cal, _, _ = build_synthetic_fixture(SYMS, n_bars=10)
        dup = {"600519": bars["600519"] + [bars["600519"][-1]]}
        self.assertFalse(DataQualityGate().check_history(dup, cal).ok)

    def test_xtdata_adapter_uses_injected_client_and_never_fakes(self):
        class FakeXt:
            @staticmethod
            def get_trading_dates(market, start_time="", end_time=""):
                # xtquant returns millisecond timestamps
                return [int(datetime(2026, 1, d, tzinfo=CN_TZ).timestamp() * 1000)
                        for d in (5, 6)]

            @staticmethod
            def get_full_tick(codes):
                return {c: {"lastPrice": 10.5, "lastClose": 10.0, "open": 10.1,
                            "high": 10.8, "low": 9.9, "volume": 1000, "amount": 10500,
                            "bidPrice": [10.4], "askPrice": [10.6]} for c in codes}

            @staticmethod
            def get_instrument_detail(code):
                return {"InstrumentName": "TEST-" + code, "OpenDate": "20200101"}

        feed = XtdataFeed(["600519"], xtdata=FakeXt())
        self.assertTrue(feed.preflight()["available"])
        snap = feed.snapshot(["600519"])["600519"]
        self.assertEqual(snap.last, 10.5)
        self.assertEqual(snap.provenance.source, "QMT/xtquant")
        self.assertAlmostEqual(snap.limit_up, 11.0)
        self.assertEqual(feed.trading_calendar("2026-01-01", "2026-01-31").dates,
                         ["2026-01-05", "2026-01-06"])

    def test_missing_xtquant_fails_loudly(self):
        feed = XtdataFeed(["600519"])
        # Force the import path to be unavailable regardless of host setup.
        import builtins
        real = builtins.__import__

        def blocked(name, *a, **kw):
            if name.startswith("xtquant"):
                raise ImportError("forced for test")
            return real(name, *a, **kw)

        builtins.__import__ = blocked
        try:
            with self.assertRaises(FeedUnavailable) as ctx:
                feed._client()
            self.assertIn("不会用模拟数据顶替", str(ctx.exception))
        finally:
            builtins.__import__ = real


class _MemFeed(MarketDataFeed):
    name = "test-memory"

    def __init__(self, bars, calendar, instruments, snapshots=None):
        self.symbols = list(bars)
        self._bars = bars
        self._cal = calendar
        self._ins = instruments
        self._snap = snapshots or {}

    def history(self, symbols, start, end):
        return {s: [b for b in self._bars[s] if start <= b.date <= end] for s in symbols}

    def snapshot(self, symbols):
        return {s: self._snap[s] for s in symbols if s in self._snap}

    def trading_calendar(self, start, end):
        return self._cal

    def instruments(self, symbols):
        return {s: self._ins[s] for s in symbols if s in self._ins}


def _flat_bars(symbol, days, price=10.0, growth=0.0):
    out = []
    px = price
    for d in days:
        px *= (1 + growth)
        out.append(ABar(date=d, open=px, high=px, low=px, close=px, volume=1e6,
                        amount=px * 1e6, adj_close=px))
    return out


class EngineTests(unittest.TestCase):
    def _setup(self, days, bars):
        cal = _calendar(days)
        ins = {s: Instrument(symbol=s, name=f"T-{s}", board=board_of(s)) for s in bars}
        feed = _MemFeed(bars, cal, ins)
        cfg = AShareSettings.load().backtest_config(
            factors=[FactorSpec("momentum", 1.0)],
            signal=SignalConfig(buy_threshold=0.05, sell_threshold=-0.05,
                                smoothing=0.0, min_holding_bars=0),
            min_order_value=1.0, allow_unverified_calendar=False)
        return cfg, feed, cal

    def test_refuses_unverified_calendar(self):
        days = [f"2026-01-{i:02d}" for i in range(1, 21)]
        bars = {s: _flat_bars(s, days) for s in SYMS}
        cfg, feed, _ = self._setup(days, bars)
        bad = TradingCalendar.weekday_fallback(days[0], days[-1])
        with self.assertRaises(ValueError) as ctx:
            AShareBacktestEngine(cfg, feed, bad)
        self.assertIn("authoritative", str(ctx.exception))

    def test_limit_up_blocks_buy_and_fees_are_real(self):
        days = _days(45)
        bars = {s: _flat_bars(s, days, growth=0.01) for s in SYMS}
        # force every day's open to the upper limit on one symbol
        rows = bars["600519"]
        for i in range(1, len(rows)):
            prev = rows[i - 1].close
            rows[i] = ABar(**{**rows[i].__dict__, "open": round(prev * 1.1, 4),
                             "high": round(prev * 1.1, 4), "limit_up": round(prev * 1.1, 4),
                             "limit_down": round(prev * 0.9, 4)})
        cfg, feed, cal = self._setup(days, bars)
        cfg.allow_unverified_calendar = True
        result = AShareBacktestEngine(cfg, feed, cal).run(days[0], days[-1])
        self.assertGreater(result.rule_blocks.get("LIMIT_UP_NO_FILL", 0), 0)
        for t in result.trades:
            self.assertIn("fees_total", t)
            self.assertGreaterEqual(t["commission"], 5.0 - 1e-9)

    def test_no_same_day_sell_after_buy(self):
        """T+1 invariant: a symbol bought on day D is never sold on day D."""
        days = _days(45)
        bars = {s: _flat_bars(s, days, growth=0.02) for s in SYMS}
        rows = bars["000001"]
        # sharp drop on day 10 to flip the signal
        for i in range(10, len(rows)):
            rows[i] = ABar(**{**rows[i].__dict__, "open": rows[i].close * 0.97,
                             "close": rows[i].close * 0.97, "high": rows[i].close,
                             "low": rows[i].close * 0.95, "adj_close": rows[i].close * 0.97})
        cfg, feed, cal = self._setup(days, bars)
        cfg.allow_unverified_calendar = True
        result = AShareBacktestEngine(cfg, feed, cal).run(days[0], days[-1])
        by_day = {}
        for t in result.trades:
            by_day.setdefault(t["date"], {}).setdefault(t["symbol"], set()).add(t["side"])
        for day, per_symbol in by_day.items():
            for sym, sides in per_symbol.items():
                self.assertFalse("BUY" in sides and "SELL" in sides,
                                 f"T+1 violated on {day} {sym}: {sides}")

    def test_no_lookahead(self):
        days = _days(60)
        bars = {s: _flat_bars(s, days, growth=0.008) for s in SYMS}
        cfg, feed, cal = self._setup(days, bars)
        cfg.allow_unverified_calendar = True
        base = AShareBacktestEngine(cfg, feed, cal).run(days[0], days[-1])
        changed = {s: list(rows) for s, rows in bars.items()}
        for s in changed:
            for i in range(35, len(changed[s])):
                changed[s][i] = ABar(**{**changed[s][i].__dict__, "close": 9999.0,
                                        "adj_close": 9999.0, "open": 9999.0,
                                        "high": 9999.0, "low": 9999.0})
        feed2 = _MemFeed(changed, cal, feed.instruments(SYMS))
        cfg2, _, _ = self._setup(days, changed)
        cfg2.allow_unverified_calendar = True
        other = AShareBacktestEngine(cfg2, feed2, cal).run(days[0], days[-1])
        cut = days[35]
        self.assertGreater(len([t for t in base.trades if t["date"] < cut]), 0)
        self.assertEqual([t for t in base.trades if t["date"] < cut],
                         [t for t in other.trades if t["date"] < cut])

    def test_result_is_auditable(self):
        days = _days(45)
        bars = {s: _flat_bars(s, days, growth=0.01) for s in SYMS}
        cfg, feed, cal = self._setup(days, bars)
        cfg.allow_unverified_calendar = True
        r = AShareBacktestEngine(cfg, feed, cal).run(days[0], days[-1])
        self.assertIn("rule_sources", r.assumptions)
        self.assertIn("fee_schedule", r.assumptions)
        self.assertIn("known_limitation", r.assumptions)
        self.assertTrue(r.assumptions["calendar"]["authoritative"])
        self.assertIn("test fixture", r.assumptions["calendar"]["source"])
        self.assertGreater(r.metrics["total_fees"], 0)
        self.assertEqual(r.metrics["risk_blocks"], r.metrics["rule_blocks"])


class ValidationTests(unittest.TestCase):
    def test_ic_ir_detects_predictive_factor(self):
        panel = []
        for d in range(40):
            for k in range(8):
                f = k / 7.0
                panel.append({"date": f"2026-02-{d + 1:02d}", "factor": f,
                              "fwd_return": 0.01 * f + 0.001 * ((d + k) % 3)})
        r = compute_ic_ir(panel)
        self.assertEqual(r.periods, 40)
        self.assertGreater(r.ic_mean, 0.8)
        self.assertEqual(r.verdict, "PASS")

    def test_ic_ir_flags_weak_factor(self):
        panel = [{"date": f"2026-02-{d + 1:02d}", "factor": (k % 3) / 3,
                  "fwd_return": (1 if (d + k) % 2 else -1) * 0.01}
                 for d in range(30) for k in range(8)]
        r = compute_ic_ir(panel)
        self.assertLess(abs(r.ic_mean), 0.2)
        self.assertEqual(r.verdict, "FAIL")

    def test_layered_monotonic(self):
        panel = [{"date": "2026-03-01", "factor": k / 10, "fwd_return": 0.001 * k}
                 for k in range(10)]
        r = layered_backtest(panel, groups=5)
        self.assertTrue(r.monotonic)
        self.assertGreater(r.spread, 0)

    def test_walk_forward_flags_overfit(self):
        windows = [(["a"], ["b"]), (["c"], ["d"])]
        calls = {"n": 0}

        def ev(dates):
            calls["n"] += 1
            return {"sharpe": 2.0, "total_return": 0.2} if dates[0] in ("a", "c") else \
                   {"sharpe": 0.2, "total_return": 0.01}

        r = walk_forward(windows, ev)
        self.assertEqual(r.verdict, "FAIL")
        self.assertTrue(any("过拟合" in f for f in r.flags))

    def test_readiness_gate_requires_3_years(self):
        bars, cal, _, _ = build_synthetic_fixture(SYMS, n_bars=60)
        panel = build_factor_panel(bars, [FactorSpec("momentum", 1.0)], min_history=20)
        ic = compute_ic_ir(panel)
        lay = layered_backtest(panel)
        wf = walk_forward([], lambda d: {})
        d = overfit_diagnosis(ic, lay, wf, span_years=1.0)
        self.assertFalse(d["passed"])
        self.assertFalse(d["gates"]["sample_span"])
        self.assertEqual(d["verdict"], "NOT_READY")


class MonitorTests(unittest.TestCase):
    def test_no_execution_calls_in_source(self):
        self.assertEqual(assert_no_execution_path(), [])

    def _monitor(self, tmp, snapshots, bars, cal, ins, cfg=None):
        feed = _MemFeed(bars, cal, ins, snapshots)
        mc = cfg or MonitorConfig(
            symbols=SYMS, factors=[FactorSpec("momentum", 1.0)],
            signal=SignalConfig(buy_threshold=0.01, sell_threshold=-0.01,
                                smoothing=0.0, min_holding_bars=0),
            db_path=str(Path(tmp) / "m.db"), snapshot_path=str(Path(tmp) / "signals.json"),
            journal_path=str(Path(tmp) / "j.jsonl"), allow_unverified_calendar=True,
        )
        return Monitor(mc, feed, cal, gate=DataQualityGate(max_stale_seconds=60),
                       journal=Journal(str(Path(tmp) / "j.jsonl")))

    def test_closed_session_emits_no_signals(self):
        bars, cal, ins, snaps = build_synthetic_fixture(SYMS, n_bars=60)
        with tempfile.TemporaryDirectory() as tmp:
            m = self._monitor(tmp, snaps, bars, cal, ins)
            now = datetime.combine(date(2026, 11, 6), time(3, 0), CN_TZ)
            c = m.run_once(now=now)
            self.assertTrue(c.skipped)
            self.assertEqual(c.tickets, [])
            m.stop()

    def test_stale_data_suppresses_all_signals(self):
        bars, cal, ins, snaps = build_synthetic_fixture(SYMS, n_bars=60)
        old = {k: Snapshot(**{**v.__dict__, "ts": "2020-01-01T10:00:00+08:00"})
               for k, v in snaps.items()}
        with tempfile.TemporaryDirectory() as tmp:
            m = self._monitor(tmp, old, bars, cal, ins)
            now = datetime.combine(datetime.now(CN_TZ).date(), time(10, 0), CN_TZ)
            c = m.run_once(now=now)
            self.assertFalse(c.quality["ok"])
            self.assertEqual(c.tickets, [])
            self.assertTrue(any("数据质量" in a for a in c.alerts))
            m.stop()

    def test_tickets_are_decision_support_only(self):
        bars, cal, ins, snaps = build_synthetic_fixture(SYMS, n_bars=120)
        with tempfile.TemporaryDirectory() as tmp:
            m = self._monitor(tmp, snaps, bars, cal, ins)
            now = datetime.combine(datetime.now(CN_TZ).date(), time(10, 0), CN_TZ)
            # align snapshot timestamps with `now` so the freshness gate passes
            fresh = {k: Snapshot(**{**v.__dict__, "ts": now.isoformat(timespec="seconds")})
                     for k, v in snaps.items()}
            m.feed._snap = fresh
            c = m.run_once(now=now)
            self.assertTrue(c.quality["ok"], msg=str(c.quality))
            for t in c.tickets:
                self.assertIn("人工执行建议", " ".join(t.notes))
                self.assertTrue(all(ch.name for ch in t.checks))
                self.assertGreaterEqual(len(t.checks), 10)
            p = Path(tmp) / "signals.json"
            self.assertTrue(p.exists())
            doc = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(doc["mode"], "MONITOR_ONLY_NO_EXECUTION")
            m.stop()


if __name__ == "__main__":
    unittest.main()
