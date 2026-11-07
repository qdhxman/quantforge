"""Intraday A-share monitor: watch the tape, produce human-executable decisions.

THIS MODULE CONTAINS NO ORDER EXECUTION PATH. It does not import ``brokers``,
does not construct orders, and does not call any trading API. Every output is a
``ManualOrderTicket`` -- a decision-support document a human reads and then
acts on in their broker client. That is deliberate: with no automatically
generated/delivered instructions, the program-trading reporting obligation
under the 2025-07-07 exchange rules is not triggered for this path.

``assert_no_execution_path()`` scans this source file and is called by the
test suite, so a future edit cannot accidentally reintroduce a submit call.

Fail-closed rules:
  * outside trading sessions -> no signals
  * stale / inconsistent / provenance-less quotes -> suppress ALL signals, alert
  * non-authoritative calendar -> refuse to start
  * limit-up / limit-down / suspension -> ticket marked NOT tradable
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from ..config import BacktestConfig, FactorSpec, RiskConfig, SignalConfig, StrategyConfig, TradingConfig
from ..factors import FACTOR_REGISTRY
from ..journal import Journal
from ..signals import SignalEngine
from .engine import _adjust
from .feeds import ABar, DataQualityGate, MarketDataFeed, Provenance, Snapshot
from .rules import (
    CN_TZ, FeeSchedule, Instrument, TradingCalendar, board_of, calculate_fees,
    is_continuous_session, market_phase, normalise_qty,
)

# Built by concatenation so this source file does not contain the literal
# tokens it is scanning for (otherwise the scan would always match itself).
FORBIDDEN_TOKENS = (
    "submit" + "_order",
    "place" + "_order",
    "order" + "_target",
    "xtquant.xt" + "trader",
)


def assert_no_execution_path(path: str | Path | None = None) -> list[str]:
    """Return forbidden trading-call tokens found in this module (must be empty)."""
    p = Path(path or __file__)
    src = p.read_text(encoding="utf-8")
    return [t for t in FORBIDDEN_TOKENS if t in src]


@dataclass
class MonitorConfig:
    symbols: list[str] = field(default_factory=list)
    factors: list[FactorSpec] = field(default_factory=list)
    signal: SignalConfig = field(default_factory=SignalConfig)
    poll_seconds: int = 30
    max_stale_seconds: int = 60
    assumed_equity: float = 1_000_000.0
    max_position_pct: float = 0.20
    max_order_value: float = 100_000.0
    exclude_st: bool = True
    boards_permitted: list[str] = field(default_factory=lambda: ["MAIN", "CHINEXT", "STAR"])
    min_signal_strength: float = 0.0
    db_path: str = "reports/ashare_monitor.db"
    snapshot_path: str = "web/ashare_signals.json"
    journal_path: str = "reports/ashare_monitor_journal.jsonl"
    webhook_url: str = ""          # empty = no external call at all
    allow_unverified_calendar: bool = False


@dataclass
class AccountSnapshot:
    cash: float
    equity: float
    positions: dict[str, int] = field(default_factory=dict)
    available: dict[str, int] = field(default_factory=dict)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ManualOrderTicket:
    """A decision-support document. NOT an order. Nothing here is ever sent."""
    symbol: str
    name: str
    board: str
    side: str                       # BUY / SELL / HOLD
    as_of: str
    session: str
    signal_score: float
    signal_reason: str
    last_price: float
    limit_up: float | None
    limit_down: float | None
    suggested_qty: int
    suggested_price_low: float
    suggested_price_high: float
    estimated_notional: float
    estimated_fees: dict[str, float]
    tradable: bool
    checks: list[Check] = field(default_factory=list)
    data_source: str = ""
    data_quality: str = "OK"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [c.as_dict() for c in self.checks]
        return d


@dataclass
class MonitorCycle:
    ts: str
    session: str
    skipped: bool
    quality: dict[str, Any]
    tickets: list[ManualOrderTicket] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ts": self.ts, "session": self.session, "skipped": self.skipped,
                "quality": self.quality, "tickets": [t.as_dict() for t in self.tickets],
                "alerts": self.alerts, "signals": self.signals}


class AlertSink(ABC):
    @abstractmethod
    def emit(self, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
        ...


class ConsoleAlert(AlertSink):
    def emit(self, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
        print(f"[{datetime.now(CN_TZ):%H:%M:%S}][{level}] {message}")


class WebhookAlert(AlertSink):
    """Optional. Does nothing unless a URL is explicitly configured.

    Deliberately stdlib-only and fire-and-forget. Sending a webhook is an
    external action; monitor leaves it OFF by default.
    """

    def __init__(self, url: str, timeout: float = 5.0):
        self.url = url
        self.timeout = timeout

    def emit(self, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
        if not self.url:
            return
        import urllib.request
        body = json.dumps({"level": level, "message": message, "payload": payload or {}},
                          ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                r.read()
        except Exception as exc:
            print(f"[alert] webhook failed: {exc!r}")


class Monitor:
    def __init__(self, config: MonitorConfig, feed: MarketDataFeed, calendar: TradingCalendar,
                 gate: DataQualityGate | None = None, alert: AlertSink | None = None,
                 journal: Journal | None = None):
        if not calendar.authoritative and not config.allow_unverified_calendar:
            raise ValueError("refusing to monitor on a non-authoritative trading calendar")
        if not config.factors:
            raise ValueError("monitor needs at least one factor")
        unknown = [f.name for f in config.factors if f.name not in FACTOR_REGISTRY]
        if unknown:
            raise ValueError(f"unknown factors: {unknown}")
        self.cfg = config
        self.feed = feed
        self.calendar = calendar
        self.gate = gate or DataQualityGate(max_stale_seconds=config.max_stale_seconds)
        self.alert = alert or ConsoleAlert()
        self.journal = journal or Journal(config.journal_path)
        self._stop = False
        self._cycles = 0
        self.fees = FeeSchedule()
        sc = StrategyConfig(
            name="ashare-monitor", symbols=config.symbols, factors=config.factors,
            signal=config.signal,
            backtest=BacktestConfig(initial_cash=config.assumed_equity,
                                    max_position_pct=config.max_position_pct),
            risk=RiskConfig(max_position_pct=config.max_position_pct,
                            max_order_notional=config.max_order_value),
            trading=TradingConfig(mode="paper"),
        )
        self._signal_engine = SignalEngine(sc)
        self._init_db()
        self.journal.append("MONITOR_START", symbols=config.symbols, feed=feed.name,
                            calendar=calendar.describe())

    # ------------------------------------------------------------------ #
    def _init_db(self) -> None:
        p = Path(self.cfg.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # ``with sqlite3.connect(...)`` commits but does NOT close the handle;
        # on Windows that leaves the .db file locked. closing() is required.
        with closing(sqlite3.connect(p)) as c, c:
            c.execute("""CREATE TABLE IF NOT EXISTS cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, session TEXT,
                skipped INTEGER, quality TEXT, alerts TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT,
                side TEXT, tradable INTEGER, score REAL, payload TEXT)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_tickets_ts ON tickets(ts)")

    def _persist(self, cycle: MonitorCycle) -> None:
        with closing(sqlite3.connect(self.cfg.db_path)) as c, c:
            c.execute("INSERT INTO cycles(ts,session,skipped,quality,alerts) VALUES(?,?,?,?,?)",
                      (cycle.ts, cycle.session, int(cycle.skipped),
                       json.dumps(cycle.quality, ensure_ascii=False),
                       json.dumps(cycle.alerts, ensure_ascii=False)))
            for t in cycle.tickets:
                c.execute("INSERT INTO tickets(ts,symbol,side,tradable,score,payload) VALUES(?,?,?,?,?,?)",
                          (cycle.ts, t.symbol, t.side, int(t.tradable), t.signal_score,
                           json.dumps(t.as_dict(), ensure_ascii=False)))
        pre = self.feed.preflight()
        if pre.get("license") == "synthetic-test-fixture":
            data_class = "SYNTHETIC TEST FIXTURE - NOT REAL MARKET DATA"
        elif "NOT live" in pre.get("note", ""):
            data_class = "OFFLINE CACHED SNAPSHOT - NOT LIVE"
        else:
            data_class = "BROKER FEED"
        p = Path(self.cfg.snapshot_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "generated_at": cycle.ts,
            "disclaimer": "决策支持信号，非投资建议；系统不自动下单，需人工在券商客户端执行。",
            "mode": "MONITOR_ONLY_NO_EXECUTION",
            "data_class": data_class,
            "feed": pre,
            "cycle": cycle.as_dict(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def stop(self) -> None:
        self._stop = True
        self.journal.append("MONITOR_STOP", cycles=self._cycles)

    def run(self, max_cycles: int | None = None) -> None:
        import time
        n = 0
        while not self._stop:
            self.run_once()
            n += 1
            if max_cycles is not None and n >= max_cycles:
                break
            time.sleep(self.cfg.poll_seconds)

    # ------------------------------------------------------------------ #
    def run_once(self, now: datetime | None = None,
                 account: AccountSnapshot | None = None) -> MonitorCycle:
        now = now or datetime.now(CN_TZ)
        phase = market_phase(now)
        ts = now.astimezone(CN_TZ).isoformat(timespec="seconds")
        cycle = MonitorCycle(ts=ts, session=phase,
                             skipped=not is_continuous_session(now),
                             quality={"ok": False, "reason": "not evaluated"})
        if cycle.skipped:
            self.journal.append("CYCLE_SKIPPED", ts=ts, session=phase)
            self._persist(cycle)
            return cycle

        # 1) data gate -- fail closed
        try:
            snapshots = self.feed.snapshot(self.cfg.symbols)
            instruments = self.feed.instruments(self.cfg.symbols)
        except Exception as exc:
            msg = f"行情获取失败，抑制本周期全部信号: {exc!r}"
            cycle.alerts.append(msg)
            cycle.quality = {"ok": False, "reason": "feed_unavailable", "detail": repr(exc)}
            self.alert.emit("CRITICAL", msg)
            self.journal.append("FEED_FAILURE", ts=ts, error=repr(exc))
            self._persist(cycle)
            return cycle

        report = self.gate.check_snapshots(snapshots, instruments, now)
        cycle.quality = report.as_dict()
        if not report.ok:
            msg = f"数据质量门禁未通过，抑制全部信号: {report.errors[:3]}"
            cycle.alerts.append(msg)
            self.alert.emit("CRITICAL", msg)
            self.journal.append("DATA_QUALITY_BLOCK", ts=ts, errors=report.errors[:10])
            self._persist(cycle)
            return cycle

        # 2) signals from the SAME adjusted history the backtest uses
        history = self.feed.history(self.cfg.symbols,
                                    self.calendar.dates[0], now.date().isoformat())
        adj = {s: [_adjust(b) for b in rows] for s, rows in history.items()}
        tickets: list[ManualOrderTicket] = []
        for s in self.cfg.symbols:
            rows = adj.get(s) or []
            if len(rows) < 40 or s not in snapshots:
                continue
            sig = self._signal_engine.evaluate(rows, len(rows) - 1, s)
            cycle.signals.append(sig.as_dict())
            if sig.action == "HOLD" or abs(sig.score) < self.cfg.min_signal_strength:
                continue
            tickets.append(self._ticket(s, sig, snapshots[s], instruments.get(s),
                                        phase, ts, account, report.ok))

        for t in tickets:
            if t.side != "HOLD":
                self.alert.emit("SIGNAL", f"{t.symbol} {t.side} 得分 {t.signal_score:+.3f} "
                                          + ("" if t.tradable else "[不可交易，仅提示]"),
                                {"symbol": t.symbol, "tradable": t.tradable})
        cycle.tickets = tickets
        self._cycles += 1
        for t in tickets:
            self.journal.append("MANUAL_TICKET", ts=ts, symbol=t.symbol, side=t.side,
                                tradable=t.tradable, score=t.signal_score, checks=[c.as_dict() for c in t.checks])
        self._persist(cycle)
        return cycle

    # ------------------------------------------------------------------ #
    def _ticket(self, symbol: str, sig: Any, snap: Snapshot, ins: Instrument | None,
                phase: str, ts: str, account: AccountSnapshot | None,
                quality_ok: bool) -> ManualOrderTicket:
        board = board_of(symbol)
        held = (account.positions.get(symbol, 0) if account else 0)
        avail = (account.available.get(symbol, 0) if account else 0)
        equity = account.equity if account else self.cfg.assumed_equity
        price = snap.last

        # Cap the suggested size by BOTH the target weight and the per-order
        # limit. Otherwise a 20% weight on a large account always exceeds
        # max_order_value and every ticket is born untradable.
        weight_budget = abs(sig.target_weight or 0.0) * equity
        budget = min(weight_budget, self.cfg.max_order_value)
        intended = (budget / price) if price > 0 else 0
        qty, qty_note = normalise_qty(symbol, intended, sig.action, held)
        lo = snap.limit_down if snap.limit_down is not None else price * 0.9
        hi = snap.limit_up if snap.limit_up is not None else price * 1.1
        fee = calculate_fees(sig.action, price, max(qty, 0), self.fees)
        checks = [
            Check("数据质量门禁", quality_ok, "通过" if quality_ok else "未通过"),
            Check("行情新鲜度", True, snap.ts),
            Check("停牌", not snap.suspended, "停牌" if snap.suspended else "正常交易"),
            Check("ST 过滤", not (self.cfg.exclude_st and (ins.is_st if ins else snap.is_st)),
                  "ST 标的" if (ins.is_st if ins else snap.is_st) else "非 ST"),
            Check("涨停不可买", not (sig.action == "BUY" and hi is not None and price >= hi - 0.005),
                  f"last={price} upper={hi}"),
            Check("跌停不可卖", not (sig.action == "SELL" and lo is not None and price <= lo + 0.005),
                  f"last={price} lower={lo}"),
            Check("T+1 可用持仓", sig.action != "SELL" or (account is None or avail > 0),
                  "需人工核对可用持仓" if account is None else f"available={avail}"),
            Check("单票仓位上限", abs(sig.target_weight or 0) <= self.cfg.max_position_pct + 1e-9,
                  f"target={sig.target_weight:.3f} cap={self.cfg.max_position_pct}"),
            Check("单笔金额上限", qty * price <= self.cfg.max_order_value,
                  f"{qty * price:,.0f} / {self.cfg.max_order_value:,.0f}"),
            Check("申报数量合规", qty > 0, f"qty={qty} ({qty_note})"),
            Check("板块权限", board in self.cfg.boards_permitted,
                  f"board={board} permitted={self.cfg.boards_permitted}"
                  + ("；科创板需 50 万资产 + 24 个月经验" if board == "STAR" else "")),
        ]
        tradable = all(c.passed for c in checks) and qty > 0
        notes = ["本单据为人工执行建议，系统不会自动下单。"]
        if budget < weight_budget:
            notes.append(f"建议数量已受单笔金额上限 {self.cfg.max_order_value:,.0f} 元约束"
                         f"（目标仓位金额 {weight_budget:,.0f} 元）。")
        if account is None:
            notes.append("未接入真实账户，数量按假设资金估算；执行前请按实际可用资金与持仓换算。")
        notes.append("涨跌停价与复权口径来自行情源；执行前在券商客户端复核。")
        return ManualOrderTicket(
            symbol=symbol, name=(ins.name if ins else ""), board=board, side=sig.action,
            as_of=ts, session=phase, signal_score=sig.score, signal_reason=sig.reason,
            last_price=price, limit_up=hi, limit_down=lo, suggested_qty=qty,
            suggested_price_low=round(price * 0.995, 3), suggested_price_high=round(price * 1.005, 3),
            estimated_notional=round(qty * price, 2),
            estimated_fees={"commission": round(fee.commission, 2), "stamp_tax": round(fee.stamp_tax, 2),
                            "transfer_fee": round(fee.transfer_fee, 2), "total": round(fee.total, 2)},
            tradable=tradable, checks=checks,
            data_source=snap.provenance.source, data_quality="OK" if quality_ok else "BLOCKED",
            notes=notes,
        )
