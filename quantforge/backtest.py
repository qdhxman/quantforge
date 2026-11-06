"""Event-driven backtester with next-bar-open execution (no look-ahead).

Timeline for each bar t:
  1. Execute orders decided at t-1 close, at t's OPEN with slippage + fees.
  2. Mark positions to market at t's CLOSE.
  3. Compute signals from bars[0..t] and queue orders for t+1.

That separation is the whole point: a signal that uses the close of t can never
trade at that same close.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .config import StrategyConfig, validate_factors
from .data import Dataset, date_index
from .factors import FACTOR_REGISTRY
from .metrics import compute_metrics, to_markdown
from .orders import OrderRequest, Side
from .portfolio import Portfolio
from .risk import RiskContext, RiskManager
from .signals import Signal, SignalEngine


@dataclass
class BacktestResult:
    config: dict[str, Any]
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    latest_signals: list[dict[str, Any]] = field(default_factory=list)
    risk_events: list[dict[str, Any]] = field(default_factory=list)
    factor_impact: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        # Keep full precision internally (metrics + JS parity); round only at the boundary.
        curve = [
            {k: (round(v, 6) if k == "drawdown" else round(v, 2) if isinstance(v, float) else v)
             for k, v in point.items()}
            for point in self.equity_curve
        ]
        return {
            "config": self.config,
            "metrics": self.metrics,
            "equity_curve": curve,
            "trades": self.trades,
            "signals": self.signals,
            "latest_signals": self.latest_signals,
            "risk_events": self.risk_events,
            "factor_impact": self.factor_impact,
        }

    def markdown(self) -> str:
        return to_markdown(self.metrics, str(self.config.get("name", "")))

    def summary(self) -> str:
        m = self.metrics
        return (f"[{self.config.get('name')}] {m.get('start')}→{m.get('end')} | "
                f"收益 {m.get('total_return', 0) * 100:.2f}% | 夏普 {m.get('sharpe')} | "
                f"最大回撤 {m.get('max_drawdown', 0) * 100:.2f}% | 成交 {m.get('num_trades')} 笔 | "
                f"风控拦截 {m.get('risk_blocks')} 次")


class BacktestEngine:
    def __init__(self, config: StrategyConfig):
        validate_factors(config, FACTOR_REGISTRY)
        self.cfg = config

    def run(self, data: Dataset) -> BacktestResult:
        cfg, bc, rc = self.cfg, self.cfg.backtest, self.cfg.risk
        symbols = [s for s in cfg.symbols if data.get(s)]
        if not symbols:
            raise ValueError(f"No bars found for configured symbols {cfg.symbols}")

        idx_maps = {s: date_index(data[s]) for s in symbols}
        all_dates: set[str] = set()
        for m in idx_maps.values():
            all_dates.update(m)
        dates = sorted(all_dates)

        pf = Portfolio(bc.initial_cash)
        signal_engine = SignalEngine(cfg)
        risk = RiskManager(rc)
        pending: list[tuple[OrderRequest, Signal]] = []

        trades: list[dict[str, Any]] = []
        signals_log: list[dict[str, Any]] = []
        risk_events: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        impact: dict[str, float] = {}
        latest_signals: list[dict[str, Any]] = []
        last_trade_bar: dict[str, int] = {}
        base_price = {s: data[s][0].close for s in symbols}
        peak = bc.initial_cash

        for t, day in enumerate(dates):
            today_bars = {s: data[s][idx_maps[s][day]] for s in symbols if day in idx_maps[s]}
            day_start = equity_curve[-1]["equity"] if equity_curve else bc.initial_cash

            # 1) execute yesterday's decisions at today's open -----------------
            for req, sig in pending:
                if req.symbol not in today_bars:
                    continue
                bar = today_bars[req.symbol]
                slip = bc.slippage_bps / 10_000.0
                is_buy = req.side == Side.BUY
                px = bar.open * (1.0 + slip) if is_buy else bar.open * (1.0 - slip)
                slip_cost = req.qty * bar.open * slip
                commission = req.qty * px * bc.commission_bps / 10_000.0
                ctx = RiskContext(
                    equity=pf.equity(), day_start_equity=day_start, peak_equity=peak,
                    bars_since_last_trade=t - last_trade_bar.get(req.symbol, -10 ** 6),
                    pending_count=0, max_pending=cfg.trading.max_orders_per_cycle,
                )
                decision = risk.evaluate(req, pf, px, ctx)
                if not decision.allowed:
                    risk_events.append({
                        "date": day, "symbol": req.symbol, "side": req.side.value,
                        "qty": req.qty, "blocked_by": decision.blocked_by,
                        "failed_checks": [c.as_dict() for c in decision.checks if not c.passed],
                        "reason": sig.reason,
                    })
                    continue
                realized = pf.apply_fill(req.symbol, req.side.value, req.qty, px, commission, slip_cost)
                last_trade_bar[req.symbol] = t
                trades.append({
                    "date": day, "symbol": req.symbol, "side": req.side.value,
                    "qty": round(req.qty, 4), "price": round(px, 4),
                    "notional": round(req.qty * px, 2), "commission": round(commission, 2),
                    "slippage": round(slip_cost, 2),
                    "pnl": round(realized, 2) if abs(realized) > 1e-9 else None,
                    "reason": sig.reason,
                })
            pending.clear()

            # 2) mark to market -----------------------------------------------
            for s, bar in today_bars.items():
                pf.set_price(s, bar.close)
            equity = pf.equity()
            peak = max(peak, equity)
            ratios = [today_bars[s].close / base_price[s] for s in symbols if s in today_bars and base_price[s] > 0]
            benchmark = bc.initial_cash * (sum(ratios) / len(ratios)) if ratios else bc.initial_cash
            equity_curve.append({
                "date": day, "equity": equity, "cash": pf.cash,
                "exposure": pf.gross_exposure(), "benchmark": benchmark,
                "drawdown": equity / peak - 1.0,
            })

            # 3) decide at close, queue for next open ---------------------------
            idx_today = {s: idx_maps[s][day] for s in symbols if day in idx_maps[s]}
            subset = {s: data[s] for s in idx_today}
            sigs = signal_engine.evaluate_many(subset, idx_today)
            latest_signals = [s.as_dict() for s in sigs]
            for sig in sigs:
                for name, value in sig.contributions.items():
                    impact[name] = impact.get(name, 0.0) + abs(value)
                if sig.action != "HOLD":
                    signals_log.append(sig.as_dict())

            targets = {s.symbol: s.target_weight for s in sigs if s.target_weight is not None}
            gross = sum(abs(w) for w in targets.values())
            cap = min(bc.max_gross_exposure_pct, rc.max_gross_exposure_pct)
            if gross > cap and gross > 0:
                targets = {k: v * cap / gross for k, v in targets.items()}

            sig_by_symbol = {s.symbol: s for s in sigs}
            for sym, weight in targets.items():
                close = today_bars[sym].close
                delta = weight * equity - pf.position_value(sym)
                if abs(delta) < bc.min_order_value or close <= 0:
                    continue
                lot = max(1, int(bc.lot_size))
                qty = math.floor(abs(delta) / close / lot) * lot
                qty = min(qty, math.floor(rc.max_order_notional / close / lot) * lot)
                if qty <= 0:
                    continue
                req = OrderRequest(
                    symbol=sym, side=Side.BUY if delta > 0 else Side.SELL,
                    qty=float(qty), limit_price=close,
                    reason=sig_by_symbol[sym].reason, target_weight=weight,
                )
                pending.append((req, sig_by_symbol[sym]))

        metrics = compute_metrics(equity_curve, trades, bc.initial_cash, equity_curve)
        metrics["risk_blocks"] = len(risk_events)
        total_impact = sum(impact.values()) or 1.0
        factor_impact = [
            {"name": name, "label": FACTOR_REGISTRY[name].label if name in FACTOR_REGISTRY else name,
             "impact": round(value, 4), "share": round(value / total_impact, 4)}
            for name, value in sorted(impact.items(), key=lambda kv: kv[1], reverse=True)
        ]
        return BacktestResult(
            config=cfg.to_dict(), equity_curve=equity_curve, trades=trades,
            signals=signals_log, latest_signals=latest_signals, risk_events=risk_events,
            factor_impact=factor_impact, metrics=metrics,
        )
