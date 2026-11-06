"""Performance statistics computed from an equity curve (no pandas required)."""

from __future__ import annotations

import math
from typing import Sequence

TRADING_DAYS = 252


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pstdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _drawdown_series(equity: Sequence[float]) -> tuple[list[float], float, int]:
    peak, peak_i = equity[0] if equity else 0.0, 0
    dds: list[float] = []
    worst, longest, run = 0.0, 0, 0
    for i, v in enumerate(equity):
        if v > peak:
            peak, peak_i = v, i
        dd = (v / peak - 1.0) if peak > 0 else 0.0
        dds.append(dd)
        worst = min(worst, dd)
        run = i - peak_i if dd < 0 else 0
        longest = max(longest, run)
    return dds, worst, longest


def compute_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    initial_cash: float,
    benchmark_curve: list[dict] | None = None,
    periods: int = TRADING_DAYS,
) -> dict:
    equity = [float(p["equity"]) for p in equity_curve]
    if len(equity) < 2:
        return {"error": "not enough bars to compute metrics", "bars": len(equity)}

    rets = [equity[k] / equity[k - 1] - 1.0 for k in range(1, len(equity)) if equity[k - 1] > 0]
    mu, sd = _mean(rets), _pstdev(rets)
    downside = [r for r in rets if r < 0]
    dsd = math.sqrt(sum(r * r for r in downside) / len(rets)) if rets else 0.0
    _, max_dd, dd_bars = _drawdown_series(equity)

    years = len(rets) / periods
    total_return = equity[-1] / initial_cash - 1.0
    cagr = (equity[-1] / initial_cash) ** (1.0 / years) - 1.0 if years > 0 and equity[-1] > 0 else 0.0
    sharpe = mu / sd * math.sqrt(periods) if sd > 0 else 0.0
    sortino = mu / dsd * math.sqrt(periods) if dsd > 0 else 0.0
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    closed = [t["pnl"] for t in trades if t.get("pnl") is not None]
    wins = [p for p in closed if p > 0]
    losses = [p for p in closed if p < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))

    out = {
        "start": equity_curve[0]["date"],
        "end": equity_curve[-1]["date"],
        "bars": len(equity_curve),
        "initial_cash": round(initial_cash, 2),
        "final_equity": round(equity[-1], 2),
        "total_return": round(total_return, 6),
        "cagr": round(cagr, 6),
        "annual_volatility": round(sd * math.sqrt(periods), 6),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_bars": dd_bars,
        "calmar": round(calmar, 4),
        "num_trades": len(trades),
        "closed_trades": len(closed),
        "win_rate": round(len(wins) / len(closed), 4) if closed else 0.0,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else (None if not wins else 999.0),
        "total_commission": round(sum(t.get("commission", 0.0) for t in trades), 2),
        "total_slippage": round(sum(t.get("slippage", 0.0) for t in trades), 2),
        "risk_blocks": 0,  # filled by the engine
    }
    if benchmark_curve:
        b = [float(p["benchmark"]) for p in benchmark_curve]
        if b and b[0] > 0:
            out["buy_hold_return"] = round(b[-1] / b[0] - 1.0, 6)
            out["excess_return"] = round(total_return - out["buy_hold_return"], 6)
            _, bdd, _ = _drawdown_series(b)
            out["buy_hold_max_drawdown"] = round(bdd, 6)
    return out


def to_markdown(metrics: dict, strategy_name: str = "") -> str:
    pct = lambda k: f"{metrics.get(k, 0) * 100:.2f}%"  # noqa: E731
    lines = [
        f"# 回测报告{' · ' + strategy_name if strategy_name else ''}",
        "",
        f"区间：{metrics.get('start')} → {metrics.get('end')}（{metrics.get('bars')} 根 K 线）",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 期初资金 | {metrics.get('initial_cash'):,.2f} |",
        f"| 期末权益 | {metrics.get('final_equity'):,.2f} |",
        f"| 总收益 | {pct('total_return')} |",
        f"| 年化收益 (CAGR) | {pct('cagr')} |",
        f"| 年化波动率 | {pct('annual_volatility')} |",
        f"| 夏普比率 | {metrics.get('sharpe')} |",
        f"| 索提诺比率 | {metrics.get('sortino')} |",
        f"| 最大回撤 | {pct('max_drawdown')} |",
        f"| Calmar | {metrics.get('calmar')} |",
        f"| 成交笔数 | {metrics.get('num_trades')} |",
        f"| 胜率 | {(metrics.get('win_rate') or 0) * 100:.2f}% |",
        f"| 盈亏比 | {metrics.get('profit_factor')} |",
        f"| 手续费 | {metrics.get('total_commission'):,.2f} |",
        f"| 滑点成本 | {metrics.get('total_slippage'):,.2f} |",
        f"| 风控拦截 | {metrics.get('risk_blocks')} |",
    ]
    if "buy_hold_return" in metrics:
        lines += [
            "",
            f"同期等权买入持有：{pct('buy_hold_return')}，超额收益 {pct('excess_return')}。",
        ]
    return "\n".join(lines) + "\n"
