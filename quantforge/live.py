"""Autonomous execution loop: signals -> sizing -> risk gate -> broker -> audit.

``run_cycle()`` is deterministic and side-effect-contained, so it is testable
without a clock or network. ``run()`` is just a loop around it.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .brokers import Broker
from .config import StrategyConfig, validate_factors
from .data import Dataset
from .factors import FACTOR_REGISTRY
from .journal import Journal, redact
from .orders import OrderRequest, Side
from .portfolio import Portfolio, Position
from .risk import RiskContext, RiskManager
from .signals import SignalEngine


@dataclass
class StepResult:
    index: int
    date: str
    signals: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    account: dict[str, Any] = field(default_factory=dict)
    halted: bool = False
    exhausted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "date": self.date, "signals": self.signals,
            "orders": self.orders, "blocked": self.blocked,
            "account": redact(self.account), "halted": self.halted, "exhausted": self.exhausted,
        }


class LiveTradingEngine:
    def __init__(self, config: StrategyConfig, broker: Broker, data: Dataset,
                 journal: Journal | None = None, start_index: int | None = None,
                 env: dict[str, str] | None = None,
                 sleep_fn: Callable[[float], None] = time.sleep):
        validate_factors(config, FACTOR_REGISTRY)
        if config.trading.mode == "live" and not broker.is_live:
            raise PermissionError("trading.mode='live' 但券商不是实盘实例；请显式构造 AlpacaBroker(enable_live=True)")
        if config.trading.mode == "paper" and broker.is_live:
            raise PermissionError("配置是模拟盘却接了实盘券商，已拒绝启动")

        self.cfg = config
        self.broker = broker
        self.data = {s: data[s] for s in config.symbols if data.get(s)}
        if not self.data:
            raise ValueError("No data for configured symbols")
        self.env = env if env is not None else dict(os.environ)
        self.journal = journal or Journal()
        self.sleep_fn = sleep_fn
        self.signal_engine = SignalEngine(config)
        self.risk = RiskManager(config.risk, self.env)
        self.length = min(len(v) for v in self.data.values())
        warmup = max((FACTOR_REGISTRY[f.name].min_bars for f in config.factors), default=30)
        self.cursor = max(start_index if start_index is not None else warmup + 1, 0)
        self.peak_equity = config.backtest.initial_cash
        self.day_start_equity = config.backtest.initial_cash
        self._last_trade: dict[str, int] = {}
        self._last_date = ""
        self._halted = False
        self._cycles = 0
        self.journal.append("ENGINE_START", mode=config.trading.mode, broker=broker.name,
                            strategy=config.name, live=broker.is_live)

    # ------------------------------------------------------------------ #
    def halt(self, reason: str) -> None:
        if not self._halted:
            self._halted = True
            self.journal.append("ENGINE_HALT", reason=reason, cycle=self._cycles)

    def resume(self) -> None:
        self._halted = False
        self.journal.append("ENGINE_RESUME", cycle=self._cycles)

    def status(self) -> dict[str, Any]:
        return {
            "running": not self._halted, "halted": self._halted, "cycles": self._cycles,
            "cursor": self.cursor, "bars": self.length, "mode": self.cfg.trading.mode,
            "broker": self.broker.name, "is_live": self.broker.is_live,
            "strategy": self.cfg.name, "kill_switch": self.risk.kill_switch,
            "account": redact(self.broker.get_account()),
        }

    def _snapshot_portfolio(self, prices: dict[str, float]) -> tuple[Portfolio, float]:
        account = self.broker.get_account()
        pf = Portfolio(float(account.get("cash", self.cfg.backtest.initial_cash)))
        for symbol, qty in self.broker.get_positions().items():
            pf.positions[symbol] = Position(symbol, qty, prices.get(symbol, 0.0))
        for s, p in prices.items():
            pf.set_price(s, p)
        equity = float(account.get("equity") or 0.0) or pf.equity()
        return pf, max(equity, 1e-9)

    def run_cycle(self) -> StepResult:
        i = self.cursor
        exhausted = i >= self.length
        date = next(iter(self.data.values()))[min(i, self.length - 1)].date
        result = StepResult(index=i, date=date, halted=self._halted, exhausted=exhausted)

        if self._halted or exhausted:
            return result
        if self.risk.kill_switch:
            self.halt("QFI_KILL_SWITCH / risk.kill_switch 触发")
            result.halted = True
            return result

        bars_upto = {s: v[: i + 1] for s, v in self.data.items()}
        idx = {s: i for s in self.data}
        signals = self.signal_engine.evaluate_many(bars_upto, idx)
        result.signals = [s.as_dict() for s in signals]
        prices = {s: self.data[s][i].close for s in self.data}
        pf, equity = self._snapshot_portfolio(prices)

        if date != self._last_date:
            self.day_start_equity = equity
            self._last_date = date
        self.peak_equity = max(self.peak_equity, equity)

        targets = {s.symbol: s.target_weight for s in signals if s.target_weight is not None}
        gross = sum(abs(w) for w in targets.values())
        cap = min(self.cfg.backtest.max_gross_exposure_pct, self.cfg.risk.max_gross_exposure_pct)
        if gross > cap and gross > 0:
            targets = {k: v * cap / gross for k, v in targets.items()}

        sig_by_symbol = {s.symbol: s for s in signals}
        pending_count = 0
        for symbol, weight in targets.items():
            price = prices[symbol]
            delta = weight * equity - pf.position_value(symbol)
            if abs(delta) < self.cfg.backtest.min_order_value or price <= 0:
                continue
            lot = max(1, int(self.cfg.backtest.lot_size))
            qty = math.floor(abs(delta) / price / lot) * lot
            qty = min(qty, math.floor(self.cfg.risk.max_order_notional / price / lot) * lot)
            if qty <= 0:
                continue
            if pending_count >= self.cfg.trading.max_orders_per_cycle:
                break
            req = OrderRequest(
                symbol=symbol, side=Side.BUY if delta > 0 else Side.SELL, qty=float(qty),
                limit_price=price, reason=sig_by_symbol[symbol].reason, target_weight=weight,
            )
            ctx = RiskContext(
                equity=equity, day_start_equity=self.day_start_equity, peak_equity=self.peak_equity,
                bars_since_last_trade=i - self._last_trade.get(symbol, -10 ** 6),
                pending_count=pending_count, max_pending=self.cfg.trading.max_orders_per_cycle,
                halted=self._halted,
            )
            decision = self.risk.evaluate(req, pf, price, ctx)
            if not decision.allowed:
                event = {
                    "symbol": symbol, "side": req.side.value, "qty": req.qty,
                    "blocked_by": decision.blocked_by,
                    "failed_checks": [c.as_dict() for c in decision.checks if not c.passed],
                    "reason": req.reason,
                }
                result.blocked.append(event)
                self.journal.append("RISK_BLOCK", date=date, **event)
                continue

            order = self.broker.submit_order(req, price)
            result.orders.append(order.as_dict())
            self.journal.append("ORDER_SUBMITTED", date=date, order=order.as_dict())
            pending_count += 1
            self._last_trade[symbol] = i
            if order.status.value == "FILLED":
                # keep the intra-cycle risk view conservative
                pf.apply_fill(symbol, req.side.value, req.qty, price, 0.0, 0.0)

        result.account = self.broker.get_account()
        self._cycles += 1
        self.cursor += 1
        result.index = self.cursor
        return result

    def run(self, interval_seconds: float | None = None, max_cycles: int | None = None) -> None:
        interval = self.cfg.trading.poll_seconds if interval_seconds is None else interval_seconds
        count = 0
        while not self._halted and self.cursor < self.length:
            if max_cycles is not None and count >= max_cycles:
                break
            self.run_cycle()
            count += 1
            if self.cursor < self.length and interval > 0:
                self.sleep_fn(interval)
        self.journal.append("ENGINE_STOP", cycles=count, reason="halted" if self._halted else "completed")
