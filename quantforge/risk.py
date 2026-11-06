"""Pre-trade risk controls. No order reaches a broker without passing here.

The manager returns EVERY rule result, not just the first failure. That makes
the dashboard able to show "which rule stopped this order" instead of a
mysterious rejected order -- the audit trail matters more than clever logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from .config import RiskConfig
from .orders import OrderRequest
from .portfolio import Portfolio

RULE_META: list[dict[str, str]] = [
    {"rule": "KILL_SWITCH", "label": "紧急停机", "description": "一键停止所有下单，配置或环境变量均可触发"},
    {"rule": "SYMBOL_BLACKLIST", "label": "标的黑名单", "description": "禁止交易指定标的"},
    {"rule": "MIN_QTY", "label": "最小下单量", "description": "过滤零股/空单"},
    {"rule": "MAX_ORDER_NOTIONAL", "label": "单笔金额上限", "description": "限制单笔委托名义金额，防 fat finger"},
    {"rule": "MAX_POSITION_WEIGHT", "label": "单票仓位上限", "description": "限制单一标的占净值比例"},
    {"rule": "MAX_GROSS_EXPOSURE", "label": "总敞口上限", "description": "限制组合总持仓占净值比例"},
    {"rule": "MAX_DAILY_LOSS", "label": "日内亏损熔断", "description": "当日亏损超阈值后停止开新仓"},
    {"rule": "MAX_DRAWDOWN", "label": "回撤熔断", "description": "自峰值回撤超阈值后停机"},
    {"rule": "COOLDOWN", "label": "交易冷却", "description": "限制同一标的连续下单频率，抑制过度交易"},
    {"rule": "BUYING_POWER", "label": "购买力", "description": "买单金额不得超过可用现金"},
    {"rule": "SHORTING_DISABLED", "label": "禁止做空", "description": "不允许卖出超过当前持仓（未开启融券时）"},
    {"rule": "PENDING_ORDER_LIMIT", "label": "挂单数量", "description": "限制同一周期未成交委托数量"},
]


@dataclass
class RiskContext:
    equity: float
    day_start_equity: float
    peak_equity: float
    bars_since_last_trade: int = 10 ** 6
    pending_count: int = 0
    max_pending: int = 20
    halted: bool = False


@dataclass
class RiskCheck:
    rule: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "passed": self.passed, "detail": self.detail}


@dataclass
class RiskDecision:
    allowed: bool
    blocked_by: str | None
    checks: list[RiskCheck] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "blocked_by": self.blocked_by,
                "checks": [c.as_dict() for c in self.checks]}


class RiskManager:
    def __init__(self, config: RiskConfig, env: Mapping[str, str] | None = None):
        self.cfg = config
        self.env = env if env is not None else os.environ

    @property
    def kill_switch(self) -> bool:
        return bool(self.cfg.kill_switch) or self.env.get("QFI_KILL_SWITCH", "0") == "1"

    def evaluate(self, req: OrderRequest, portfolio: Portfolio, price: float, ctx: RiskContext) -> RiskDecision:
        cfg = self.cfg
        equity = max(ctx.equity, 1e-9)
        qty = abs(req.qty)
        notional = qty * max(price, 0.0)
        is_buy = req.side.value == "BUY"
        signed = qty if is_buy else -qty
        current_qty = portfolio.positions.get(req.symbol).qty if req.symbol in portfolio.positions else 0.0
        after_value = (current_qty + signed) * price
        after_gross = portfolio.gross_exposure() - abs(current_qty * price) + abs(after_value)
        checks: list[RiskCheck] = []

        def add(rule: str, passed: bool, detail: str) -> None:
            checks.append(RiskCheck(rule, passed, detail))

        add("KILL_SWITCH", not (self.kill_switch or ctx.halted),
            "已停机，所有委托拒绝" if (self.kill_switch or ctx.halted) else "运行中")
        add("SYMBOL_BLACKLIST", req.symbol not in cfg.blacklist,
            f"{req.symbol} 在黑名单" if req.symbol in cfg.blacklist else f"{req.symbol} 可交易")
        add("MIN_QTY", qty > 0, f"qty={qty:g}")
        add("MAX_ORDER_NOTIONAL", notional <= cfg.max_order_notional,
            f"单笔 {notional:,.0f} / 上限 {cfg.max_order_notional:,.0f}")
        add("MAX_POSITION_WEIGHT", abs(after_value) / equity <= cfg.max_position_pct + 1e-9,
            f"下单后仓位 {abs(after_value) / equity:.1%} / 上限 {cfg.max_position_pct:.0%}")
        add("MAX_GROSS_EXPOSURE", after_gross / equity <= cfg.max_gross_exposure_pct + 1e-9,
            f"下单后总敞口 {after_gross / equity:.1%} / 上限 {cfg.max_gross_exposure_pct:.0%}")
        daily = ctx.equity / max(ctx.day_start_equity, 1e-9) - 1.0
        add("MAX_DAILY_LOSS", daily > -cfg.max_daily_loss_pct,
            f"当日 {daily:+.2%} / 阈值 -{cfg.max_daily_loss_pct:.0%}")
        dd = ctx.equity / max(ctx.peak_equity, 1e-9) - 1.0
        add("MAX_DRAWDOWN", dd > -cfg.max_drawdown_pct,
            f"当前回撤 {dd:+.2%} / 阈值 -{cfg.max_drawdown_pct:.0%}")
        add("COOLDOWN", ctx.bars_since_last_trade >= cfg.cooldown_bars,
            f"距上次成交 {ctx.bars_since_last_trade} bar / 要求 {cfg.cooldown_bars}")
        add("BUYING_POWER", (not is_buy) or notional <= portfolio.cash + 1e-6,
            (f"需 {notional:,.0f} / 可用 {portfolio.cash:,.0f}") if is_buy else "卖出无需购买力")
        oversell = (not is_buy) and (not cfg.allow_short) and (qty > current_qty + 1e-9)
        add("SHORTING_DISABLED", not oversell,
            f"卖出 {qty:g} 超过持仓 {current_qty:g}" if oversell else "未超卖")
        add("PENDING_ORDER_LIMIT", ctx.pending_count < ctx.max_pending,
            f"挂单 {ctx.pending_count} / 上限 {ctx.max_pending}")

        failed = next((c for c in checks if not c.passed), None)
        return RiskDecision(failed is None, failed.rule if failed else None, checks)


def list_rules() -> list[dict[str, str]]:
    return [dict(r) for r in RULE_META]
