"""Out-of-sample validation and factor efficacy tests.

Thresholds follow standard factor-research practice (see
docs/ashare-readiness-audit.md, item R-07):
  |IC| > 0.03  minimal predictive power; > 0.05 strong; > 0.10 CHECK LOOK-AHEAD
  IR > 0.5    stable; > 1.0 suspiciously good, re-verify
  IC positive ratio > 0.55  direction stability
  OOS Sharpe >= 0.7 x IS Sharpe  acceptable degradation
  factor panel must span >= 3 years / a full market cycle for production claims

A pretty in-sample equity curve is not evidence. This module exists to make
that statement mechanically checkable.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from ..factors import evaluate
from .feeds import ABar

IC_MIN = 0.03
IC_STRONG = 0.05
IC_LOOKAHEAD_SUSPECT = 0.10
IR_MIN = 0.5
IR_SUSPECT = 1.0
POSITIVE_RATIO_MIN = 0.55
OOS_SHARPE_FLOOR = 0.7
MIN_CROSS_SECTION = 5


def _ranks(xs: Sequence[float]) -> list[float]:
    """Average ranks for ties (1-based)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 2:
        return 0.0
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da > 0 and db > 0 else 0.0


@dataclass
class ICReport:
    periods: int
    ic_mean: float
    ic_std: float
    ir: float
    positive_ratio: float
    ic_series: list[float] = field(default_factory=list)
    verdict: str = ""
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("periods", "ic_mean", "ic_std", "ir",
                                              "positive_ratio", "verdict", "flags")}


def compute_ic_ir(panel: Sequence[dict[str, Any]]) -> ICReport:
    """panel rows: {date, factor, fwd_return}. Rank IC per cross-section."""
    by_date: dict[str, list[tuple[float, float]]] = {}
    for r in panel:
        by_date.setdefault(str(r["date"]), []).append((float(r["factor"]), float(r["fwd_return"])))
    series: list[float] = []
    for d in sorted(by_date):
        rows = by_date[d]
        if len(rows) < MIN_CROSS_SECTION:
            continue
        f = _ranks([x[0] for x in rows])
        y = _ranks([x[1] for x in rows])
        series.append(_pearson(f, y))
    if not series:
        return ICReport(0, 0.0, 0.0, 0.0, 0.0, [], "INSUFFICIENT_DATA", ["no cross-section with >= 5 names"])
    mean = statistics.fmean(series)
    std = statistics.pstdev(series) if len(series) > 1 else 0.0
    ir = mean / std if std > 0 else 0.0
    pos = sum(1 for x in series if x > 0) / len(series)
    flags: list[str] = []
    if abs(mean) > IC_LOOKAHEAD_SUSPECT:
        flags.append("IC>0.10: 检查前视偏差 / 复权口径 / 幸存者偏差")
    if abs(ir) > IR_SUSPECT:
        flags.append("IR>1.0: 异常稳定，复核数据与因子定义")
    if len(series) < 20:
        flags.append("有效截面 <20，统计效力不足")
    if abs(mean) < IC_MIN:
        flags.append("|IC|<0.03: 无基本预测力")
    if abs(ir) < IR_MIN:
        flags.append("|IR|<0.5: 方向不稳定")
    if max(pos, 1 - pos) < POSITIVE_RATIO_MIN:
        flags.append("IC 方向一致性 <55%")
    ok = (abs(mean) >= IC_MIN and abs(ir) >= IR_MIN and
          max(pos, 1 - pos) >= POSITIVE_RATIO_MIN and len(series) >= 20)
    return ICReport(len(series), round(mean, 6), round(std, 6), round(ir, 4),
                    round(pos, 4), [round(x, 6) for x in series],
                    "PASS" if ok else "FAIL", flags)


@dataclass
class LayerReport:
    groups: int
    layer_returns: list[float]
    spread: float
    monotonic: bool
    verdict: str

    def as_dict(self) -> dict:
        return {"groups": self.groups, "layer_returns": self.layer_returns,
                "spread": self.spread, "monotonic": self.monotonic, "verdict": self.verdict}


def layered_backtest(panel: Sequence[dict[str, Any]], groups: int = 5) -> LayerReport:
    """Equal-weight forward return by factor quantile. Good factors are monotonic."""
    by_date: dict[str, list[tuple[float, float]]] = {}
    for r in panel:
        by_date.setdefault(str(r["date"]), []).append((float(r["factor"]), float(r["fwd_return"])))
    buckets: list[list[float]] = [[] for _ in range(groups)]
    for d in sorted(by_date):
        rows = sorted(by_date[d], key=lambda x: x[0])
        if len(rows) < MIN_CROSS_SECTION:
            continue
        for k, (_, ret) in enumerate(rows):
            g = min(groups - 1, k * groups // len(rows))
            buckets[g].append(ret)
    means = [statistics.fmean(b) if b else 0.0 for b in buckets]
    diffs = [means[i + 1] - means[i] for i in range(groups - 1)]
    mono = all(d >= -1e-9 for d in diffs) or all(d <= 1e-9 for d in diffs)
    spread = means[-1] - means[0]
    ok = mono and abs(spread) > 0.001 and all(buckets)
    return LayerReport(groups, [round(x, 6) for x in means], round(spread, 6), mono,
                       "PASS" if ok else "FAIL")


def build_factor_panel(bars_by_symbol: dict[str, Sequence[ABar]], specs: Sequence[Any],
                       horizon: int = 1, method: str = "weighted",
                       min_history: int = 40) -> list[dict[str, Any]]:
    """Strictly forward-looking panel: factor at T, return from T to T+horizon.

    Uses forward-adjusted prices. A row is emitted only when the future bar
    exists, so no terminal-bar leakage is possible.
    """
    out: list[dict[str, Any]] = []
    for symbol, bars in bars_by_symbol.items():
        for i in range(min_history, len(bars) - horizon):
            b, fwd = bars[i], bars[i + horizon]
            if b.suspended or fwd.suspended or b.close <= 0 or fwd.adj_close <= 0:
                continue
            comp = evaluate(bars, i, specs, method)
            if comp.coverage < 0.5:
                continue
            fwd_ret = (fwd.adj_close or fwd.close) / (b.adj_close or b.close) - 1.0
            out.append({"date": b.date, "symbol": symbol, "factor": comp.value,
                        "fwd_return": fwd_ret, "coverage": comp.coverage})
    return out


def split_oos(dates: Sequence[str], train_ratio: float = 0.7) -> tuple[list[str], list[str]]:
    d = sorted(set(dates))
    if not d:
        raise ValueError("no dates")
    k = max(1, int(len(d) * train_ratio))
    return d[:k], d[k:]


def rolling_windows(dates: Sequence[str], train_days: int, test_days: int,
                    step: int | None = None) -> list[tuple[list[str], list[str]]]:
    d = sorted(set(dates))
    step = step or test_days
    out = []
    i = 0
    while i + train_days + test_days <= len(d):
        out.append((d[i:i + train_days], d[i + train_days:i + train_days + test_days]))
        i += step
    return out


@dataclass
class WalkForwardReport:
    windows: int
    is_sharpe: list[float]
    oos_sharpe: list[float]
    is_return: list[float]
    oos_return: list[float]
    verdict: str
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"windows": self.windows, "is_sharpe": self.is_sharpe, "oos_sharpe": self.oos_sharpe,
                "is_return": self.is_return, "oos_return": self.oos_return,
                "verdict": self.verdict, "flags": self.flags}


def walk_forward(windows: Sequence[tuple[list[str], list[str]]],
                 evaluator: Callable[[list[str]], dict[str, Any]]) -> WalkForwardReport:
    """``evaluator(dates)`` runs a backtest on those dates and returns metrics."""
    ins, oos, ir, orr = [], [], [], []
    for train, test in windows:
        a = evaluator(train)
        b = evaluator(test)
        ins.append(float(a.get("sharpe", 0) or 0))
        oos.append(float(b.get("sharpe", 0) or 0))
        ir.append(float(a.get("total_return", 0) or 0))
        orr.append(float(b.get("total_return", 0) or 0))
    flags: list[str] = []
    if not oos:
        return WalkForwardReport(0, [], [], [], [], "INSUFFICIENT_DATA", ["no complete windows"])
    mean_is, mean_oos = statistics.fmean(ins), statistics.fmean(oos)
    if mean_oos <= 0:
        flags.append("样本外平均夏普 <= 0：策略在未见数据上不赚钱")
    elif mean_is > 0 and mean_oos / mean_is < OOS_SHARPE_FLOOR:
        flags.append(f"样本外夏普/样本内夏普 = {mean_oos / mean_is:.2f} < {OOS_SHARPE_FLOOR}：疑似过拟合")
    neg = sum(1 for x in orr if x <= 0)
    if neg / len(orr) > 0.4:
        flags.append(f"{neg}/{len(orr)} 个样本外窗口亏损：稳健性不足")
    ok = not flags and mean_oos > 0
    return WalkForwardReport(len(windows), [round(x, 4) for x in ins], [round(x, 4) for x in oos],
                             [round(x, 6) for x in ir], [round(x, 6) for x in orr],
                             "PASS" if ok else "FAIL", flags)


def overfit_diagnosis(ic: ICReport, layers: LayerReport, wf: WalkForwardReport,
                      *, span_years: float = 0.0) -> dict[str, Any]:
    """One gate that must ALL pass before a strategy may be called production-ready."""
    gates = {
        "factor_efficacy": ic.verdict == "PASS",
        "layer_monotonicity": layers.verdict == "PASS",
        "walk_forward": wf.verdict == "PASS",
        "sample_span": span_years >= 3.0,
    }
    notes: list[str] = []
    if not gates["sample_span"]:
        notes.append(f"回测跨度 {span_years:.2f} 年 < 3 年：未覆盖完整市场周期，不得用于实盘结论")
    notes.extend(ic.flags + wf.flags)
    passed = all(gates.values())
    return {
        "gates": gates, "passed": passed, "notes": notes,
        "verdict": "READY_FOR_PAPER" if passed else "NOT_READY",
        "next_step": "进入模拟盘连续运行 + 实盘小额验证" if passed else "补齐未通过项，禁止接真实资金",
    }
