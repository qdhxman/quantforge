"""A-share backtest engine with market-microstructure-aware execution.

Reuses the SAME factor library and signal engine as the generic research core
(``quantforge.factors`` / ``quantforge.signals``) so that an A-share result and
a generic result differ ONLY because of A-share trading rules, not because of
a different definition of "momentum".

Strictness contract
-------------------
* Signal at bar t uses bars[0..t]; execution happens at bar t+1 OPEN.
* A buy cannot fill when the bar opens at/through the upper limit; a sell
  cannot fill at the lower limit. Suspension blocks everything.
* T+1: shares bought on T are not sellable until T+1.
* Order size obeys board-specific lot rules (STAR is NOT 100-share lots).
* Real fee schedule: commission (min CNY 5), sell-side stamp tax, transfer fee.
* Every blocked order is counted by rule, never silently dropped.

PRICE CALIBRE (important, deliberately explicit)
------------------------------------------------
All prices in the engine are FORWARD-ADJUSTED continuous prices. Corporate
actions are absorbed into the price series, so returns and PnL are continuous.
Consequence: absolute turnover, the CNY-5 minimum commission trigger and lot
quantities are approximations of a real broker statement. This engine is for
STRATEGY VALIDATION, not for reconciling a live account. Live reconciliation
requires broker order/execution reports and is out of scope until those exist.
See docs/ashare-readiness-audit.md, item R-11.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

from ..config import BacktestConfig, FactorSpec, RiskConfig, SignalConfig, StrategyConfig, TradingConfig
from ..factors import FACTOR_REGISTRY, evaluate
from ..metrics import compute_metrics
from ..signals import SignalEngine
from .feeds import ABar, DataQualityGate, MarketDataFeed, QualityReport
from .rules import (
    RULE_SOURCES, FeeSchedule, Instrument, TradingCalendar, board_of,
    calculate_fees, normalise_qty, price_limit_pct, price_limits,
)

RULE_BLOCK_LABELS = {
    "LIMIT_UP_NO_FILL": "涨停封板，买单无法成交",
    "LIMIT_DOWN_NO_FILL": "跌停封板，卖单无法成交",
    "SUSPENDED": "停牌，禁止交易",
    "T1_LOCKED": "T+1，当日买入不可卖",
    "BELOW_STAR_MIN_200": "科创板单笔申报不足 200 股",
    "BELOW_BSE_MIN_100": "北交所单笔申报不足 100 股",
    "ROUNDED_TO_LOT_100": "按 100 股整手取整后为 0",
    "ST_EXCLUDED": "ST/*ST 标的被策略排除",
    "NEW_LISTING_EXCLUDED": "新股上市前 N 日被策略排除",
    "MIN_ORDER_VALUE": "低于最小调仓金额",
    "NO_BAR": "当日无行情",
}


@dataclass
class AShareBacktestConfig:
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.00025
    slippage_bps: float = 5.0
    max_position_pct: float = 0.20
    max_gross_exposure_pct: float = 0.95
    min_order_value: float = 5_000.0
    factors: list[FactorSpec] = field(default_factory=list)
    signal: SignalConfig = field(default_factory=SignalConfig)
    exclude_st: bool = True
    exclude_new_listing_days: int = 5
    allow_unverified_calendar: bool = False
    run_id: str = ""


@dataclass
class AShareBacktestResult:
    run_id: str
    assumptions: dict[str, Any]
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    latest_signals: list[dict[str, Any]] = field(default_factory=list)
    rule_blocks: dict[str, int] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "assumptions": self.assumptions, "metrics": self.metrics,
            "equity_curve": self.equity_curve, "trades": self.trades, "signals": self.signals,
            "latest_signals": self.latest_signals, "rule_blocks": self.rule_blocks,
            "quality": self.quality,
        }

    def summary(self) -> str:
        m = self.metrics
        return (f"[A股] {m.get('start')}→{m.get('end')} | 收益 {m.get('total_return', 0) * 100:.2f}% | "
                f"夏普 {m.get('sharpe')} | 回撤 {m.get('max_drawdown', 0) * 100:.2f}% | "
                f"成交 {m.get('num_trades')} 笔 | 规则拦截 {sum(self.rule_blocks.values())} 次")


def _adjust(bar: ABar) -> ABar:
    """Scale OHLC into the forward-adjusted price calibre (one consistent series)."""
    ratio = (bar.adj_close or bar.close) / bar.close if bar.close > 0 else 1.0
    return ABar(
        date=bar.date, open=bar.open * ratio, high=bar.high * ratio, low=bar.low * ratio,
        close=bar.close * ratio, volume=bar.volume, amount=bar.amount,
        adj_close=bar.adj_close or bar.close, adj_factor=bar.adj_factor,
        suspended=bar.suspended, is_st=bar.is_st,
        limit_up=bar.limit_up * ratio if bar.limit_up else None,
        limit_down=bar.limit_down * ratio if bar.limit_down else None,
    )


class AShareBacktestEngine:
    def __init__(self, config: AShareBacktestConfig, feed: MarketDataFeed,
                 calendar: TradingCalendar, gate: DataQualityGate | None = None):
        if not config.factors:
            raise ValueError("at least one factor is required")
        unknown = [f.name for f in config.factors if f.name not in FACTOR_REGISTRY]
        if unknown:
            raise ValueError(f"unknown factors: {unknown}")
        if not calendar.authoritative and not config.allow_unverified_calendar:
            raise ValueError(
                "refusing to backtest on a NON-authoritative trading calendar. "
                "Load real trading days from the QMT/broker feed (feed.trading_calendar). "
                "Set allow_unverified_calendar=True ONLY for synthetic unit tests."
            )
        self.cfg = config
        self.feed = feed
        self.calendar = calendar
        self.gate = gate or DataQualityGate()
        self.fee_schedule = FeeSchedule(commission_rate=config.commission_rate)
        self.fee_schedule.validate()
        sc = StrategyConfig(
            name=config.run_id or "ashare",
            symbols=[], factors=config.factors, signal=config.signal,
            backtest=BacktestConfig(
                initial_cash=config.initial_cash, commission_bps=0.0, slippage_bps=0.0,
                max_position_pct=config.max_position_pct,
                max_gross_exposure_pct=config.max_gross_exposure_pct,
            ),
            risk=RiskConfig(
                max_position_pct=config.max_position_pct,
                max_gross_exposure_pct=config.max_gross_exposure_pct,
                allow_short=False,
            ),
            trading=TradingConfig(mode="paper"),
        )
        self._signal_engine = SignalEngine(sc)

    def _limits(self, symbol: str, prev_close: float, bar: ABar, ins: Instrument | None,
                day: str) -> tuple[float | None, float | None]:
        if bar.limit_up is not None and bar.limit_down is not None:
            return bar.limit_down, bar.limit_up
        as_of = date.fromisoformat(day[:10])
        pct = price_limit_pct(symbol, is_st=(ins.is_st if ins else bar.is_st),
                              is_delisting=(ins.is_delisting if ins else False), as_of=as_of)
        return price_limits(prev_close, pct)

    def run(self, start: str, end: str) -> AShareBacktestResult:
        candidates = self._symbols_from_feed(start, end)
        instruments = self.feed.instruments(candidates)
        symbols = list(instruments)
        if not symbols:
            raise ValueError("feed returned no instruments")
        raw = self.feed.history(symbols, start, end)
        bars = {s: [_adjust(b) for b in rows] for s, rows in raw.items()}

        q_hist = self.gate.check_history(bars, self.calendar)
        if not q_hist.ok:
            q_hist.assert_healthy()

        days = self.calendar.between(start, end)
        by_date: dict[str, dict[str, ABar]] = {s: {b.date: b for b in rows} for s, rows in bars.items()}
        last_price: dict[str, float] = {s: rows[0].close if rows else 0.0 for s, rows in bars.items()}
        prev_close: dict[str, float] = dict(last_price)

        cash = self.cfg.initial_cash
        qty: dict[str, int] = {s: 0 for s in symbols}
        available: dict[str, int] = {s: 0 for s in symbols}
        avg_cost: dict[str, float] = {s: 0.0 for s in symbols}
        pending: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        signals_log: list[dict[str, Any]] = []
        latest_signals: list[dict[str, Any]] = []
        blocks: dict[str, int] = {}
        equity_curve: list[dict[str, Any]] = []
        base_price = {s: (bars[s][0].close if bars[s] else 0.0) for s in symbols}
        listing_count: dict[str, int] = {s: 0 for s in symbols}

        def block(rule: str) -> None:
            blocks[rule] = blocks.get(rule, 0) + 1

        for t, day in enumerate(days):
            today: dict[str, ABar] = {}
            for s in symbols:
                b = by_date[s].get(day)
                if b is not None:
                    today[s] = b

            # T+1 release at the start of a new trading day
            for s in symbols:
                available[s] = qty[s]

            # ---- execute yesterday's decisions at today's OPEN -------------
            for order in pending:
                s, side, want = order["symbol"], order["side"], order["qty"]
                realized = 0.0
                b = today.get(s)
                if b is None:
                    block("NO_BAR"); continue
                if b.suspended:
                    block("SUSPENDED"); continue
                lo, hi = self._limits(s, prev_close.get(s, b.close), b, instruments.get(s), day)
                px_open = b.open
                slip = self.cfg.slippage_bps / 10_000.0
                if side == "BUY":
                    if hi is not None and px_open >= hi - 0.005:
                        block("LIMIT_UP_NO_FILL"); continue
                    px = px_open * (1 + slip)
                    if hi is not None:
                        px = min(px, hi)
                else:
                    if lo is not None and px_open <= lo + 0.005:
                        block("LIMIT_DOWN_NO_FILL"); continue
                    px = px_open * (1 - slip)
                    if lo is not None:
                        px = max(px, lo)
                    if want > available[s]:
                        want = available[s]
                        if want <= 0:
                            block("T1_LOCKED"); continue
                q, note = normalise_qty(s, want, side, qty[s] if side == "SELL" else 0)
                if note in ("BELOW_STAR_MIN_200", "BELOW_BSE_MIN_100", "ROUNDED_TO_LOT_100") and q == 0:
                    block(note); continue
                if q <= 0:
                    block("T1_LOCKED"); continue
                fees = calculate_fees(side, px, q, self.fee_schedule)
                if side == "BUY":
                    cost = q * px + fees.total
                    if cost > cash + 1e-6:
                        q = int((cash - fees.total) / px)
                        q, note = normalise_qty(s, q, "BUY", 0)
                        if q <= 0:
                            block("MIN_ORDER_VALUE"); continue
                        fees = calculate_fees("BUY", px, q, self.fee_schedule)
                        cost = q * px + fees.total
                    new_qty = qty[s] + q
                    avg_cost[s] = (avg_cost[s] * qty[s] + q * px + fees.total) / new_qty
                    qty[s] = new_qty
                    cash -= cost
                else:
                    realized = (px - avg_cost[s]) * q - fees.total
                    cash += q * px - fees.total
                    qty[s] -= q
                    available[s] -= q
                    if qty[s] == 0:
                        avg_cost[s] = 0.0
                trades.append({
                    "date": day, "symbol": s, "side": side, "qty": q, "price": round(px, 4),
                    "notional": round(q * px, 2), "commission": round(fees.commission, 2),
                    "stamp_tax": round(fees.stamp_tax, 2), "transfer_fee": round(fees.transfer_fee, 2),
                    "regulatory_fee": round(fees.regulatory_fee, 2), "fees_total": round(fees.total, 2),
                    "slippage": round(q * abs(px - b.open), 2),
                    "pnl": round(realized, 2) if side == "SELL" else None,
                    "qty_note": note, "signal_reason": order["reason"],
                })
            pending = []

            # ---- mark to market at CLOSE ------------------------------------
            for s, b in today.items():
                if not b.suspended:
                    last_price[s] = b.close
                    prev_close[s] = b.close
                    listing_count[s] += 1
            equity = cash + sum(qty[s] * last_price[s] for s in symbols)
            ratios = [last_price[s] / base_price[s] for s in symbols if base_price[s] > 0]
            benchmark = self.cfg.initial_cash * (sum(ratios) / len(ratios)) if ratios else self.cfg.initial_cash
            equity_curve.append({"date": day, "equity": equity, "cash": cash,
                                 "exposure": sum(qty[s] * last_price[s] for s in symbols),
                                 "benchmark": benchmark})

            # ---- decide at CLOSE, queue for next OPEN -----------------------
            eligible: dict[str, list[ABar]] = {}
            idx_today: dict[str, int] = {}
            for s in symbols:
                rows = [b for b in bars[s] if b.date <= day]
                if not rows:
                    continue
                ins = instruments.get(s)
                if self.cfg.exclude_st and (ins.is_st if ins else rows[-1].is_st):
                    block("ST_EXCLUDED"); continue
                if listing_count[s] < self.cfg.exclude_new_listing_days:
                    block("NEW_LISTING_EXCLUDED"); continue
                eligible[s] = rows
                idx_today[s] = len(rows) - 1

            sigs = [self._signal_engine.evaluate(eligible[s], idx_today[s], s) for s in eligible]
            latest_signals = [x.as_dict() for x in sigs]
            for x in sigs:
                if x.action != "HOLD":
                    signals_log.append(x.as_dict())

            targets = {x.symbol: x.target_weight for x in sigs if x.target_weight is not None}
            gross = sum(abs(v) for v in targets.values())
            if gross > self.cfg.max_gross_exposure_pct and gross > 0:
                targets = {k: v * self.cfg.max_gross_exposure_pct / gross for k, v in targets.items()}
            sig_map = {x.symbol: x for x in sigs}
            for s, weight in targets.items():
                px = last_price[s]
                delta = weight * equity - qty[s] * px
                if abs(delta) < self.cfg.min_order_value or px <= 0:
                    block("MIN_ORDER_VALUE"); continue
                want = abs(delta) / px
                q, note = normalise_qty(s, want, "BUY" if delta > 0 else "SELL", qty[s])
                if q <= 0:
                    block(note if note in RULE_BLOCK_LABELS else "MIN_ORDER_VALUE"); continue
                pending.append({"symbol": s, "side": "BUY" if delta > 0 else "SELL",
                                "qty": q, "reason": sig_map[s].reason})

        metrics = compute_metrics(equity_curve, trades, self.cfg.initial_cash, equity_curve)
        metrics["rule_blocks"] = sum(blocks.values())
        metrics["risk_blocks"] = metrics["rule_blocks"]
        metrics["total_fees"] = round(sum(t["fees_total"] for t in trades), 2)
        assumptions = {
            "price_calibre": "forward-adjusted continuous prices; corporate actions absorbed into price",
            "known_limitation": "absolute turnover, CNY-5 commission minimum and lot quantities are "
                                "approximations; NOT a broker-statement reconciliation",
            "execution": "signal at close t -> order at open t+1; limit-up buy / limit-down sell never fill",
            "t_plus_1": True,
            "lot_rules": "MAIN/CHINEXT 100-share lots; STAR >=200 with 1-share increments",
            "fee_schedule": {"commission_rate": self.cfg.commission_rate,
                             "commission_min_cny": self.fee_schedule.commission_min_cny,
                             "stamp_tax_sell": self.fee_schedule.stamp_tax_sell,
                             "transfer_fee_both": self.fee_schedule.transfer_fee_both},
            "slippage_bps": self.cfg.slippage_bps,
            "calendar": self.calendar.describe(),
            "feed": self.feed.preflight(),
            "rule_sources": [dict(r) for r in RULE_SOURCES],
        }
        return AShareBacktestResult(
            run_id=self.cfg.run_id or "ashare", assumptions=assumptions,
            equity_curve=equity_curve, trades=trades, signals=signals_log,
            latest_signals=latest_signals, rule_blocks=blocks,
            quality=q_hist.as_dict(), metrics=metrics,
        )

    def _symbols_from_feed(self, start: str, end: str) -> list[str]:
        cached = getattr(self.feed, "symbols", None)
        if cached:
            return list(cached)
        manifest = getattr(self.feed, "manifest", None)
        if manifest and manifest.get("symbols"):
            return list(manifest["symbols"])
        raise ValueError("feed must expose .symbols or a manifest with symbols")
