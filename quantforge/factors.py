"""Pluggable factor library.

Every factor maps (bars, index, params) -> a score clipped to [-1, +1],
where positive means "bullish" and negative means "bearish". A factor returns
``None`` while it lacks history; those factors are skipped and the remaining
weights are renormalised. That single convention is what makes free
combination safe: adding a slow factor cannot silently leak future data.

Add your own factor with ``@register(...)`` -- see examples/custom_factor.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .config import FactorSpec
from .data import Bar

FactorFn = Callable[[Sequence[Bar], int, dict[str, Any]], float | None]


@dataclass(frozen=True)
class FactorMeta:
    name: str
    label: str
    category: str
    description: str
    default_params: dict[str, Any]
    min_bars: int
    fn: FactorFn


FACTOR_REGISTRY: dict[str, FactorMeta] = {}


def register(name: str, label: str, category: str, description: str, default_params: dict[str, Any], min_bars: int):
    def deco(fn: FactorFn) -> FactorFn:
        if name in FACTOR_REGISTRY:
            raise ValueError(f"factor '{name}' already registered")
        FACTOR_REGISTRY[name] = FactorMeta(name, label, category, description, default_params, min_bars, fn)
        return fn
    return deco


# --------------------------------------------------------------------------- #
# shared numeric helpers (kept deliberately simple so the JS demo mirrors them)
# --------------------------------------------------------------------------- #
def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pstdev(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _ema_series(xs: Sequence[float], period: int) -> list[float]:
    if not xs:
        return []
    alpha = 2.0 / (period + 1)
    out = [float(xs[0])]
    for x in xs[1:]:
        out.append(alpha * float(x) + (1 - alpha) * out[-1])
    return out


def _closes(bars: Sequence[Bar], i: int, n: int) -> list[float]:
    return [b.close for b in bars[i - n + 1 : i + 1]]


def _returns(cs: Sequence[float]) -> list[float]:
    return [cs[k] / cs[k - 1] - 1.0 for k in range(1, len(cs)) if cs[k - 1] != 0]


def _true_ranges(bars: Sequence[Bar], i: int, n: int) -> list[float]:
    out = []
    for k in range(i - n + 1, i + 1):
        b, prev = bars[k], bars[k - 1]
        if k == 0 or prev.close == 0:
            out.append(b.high - b.low)
        else:
            out.append(max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close)))
    return out


def _safe_tanh(x: float) -> float:
    return math.tanh(max(-30.0, min(30.0, x)))


# --------------------------------------------------------------------------- #
# factors
# --------------------------------------------------------------------------- #
@register("momentum", "动量 ROC", "趋势", "N 日收益率除以同期波动率，衡量趋势强度（风险调整动量）", {"lookback": 20}, 21)
def f_momentum(bars, i, p):
    lb = int(p.get("lookback", 20))
    if i < lb:
        return None
    cs = _closes(bars, i, lb + 1)
    if cs[0] <= 0:
        return None
    ret = cs[-1] / cs[0] - 1.0
    vol = _pstdev(_returns(cs)) * math.sqrt(lb)
    return _safe_tanh(ret / max(vol, 1e-6) / 1.5)


@register("ma_cross", "均线交叉", "趋势", "快慢均线之差相对慢均线的偏离度", {"fast": 10, "slow": 30}, 30)
def f_ma_cross(bars, i, p):
    fast, slow = int(p.get("fast", 10)), int(p.get("slow", 30))
    if i < slow or fast >= slow:
        return None
    cs = _closes(bars, i, slow)
    maf, mas = _mean(cs[-fast:]), _mean(cs)
    return _safe_tanh((maf - mas) / max(mas, 1e-9) * 12.0)


@register("rsi", "RSI 超买超卖", "反转", "RSI 相对 50 中轴的反向偏离：超卖给正分、超买给负分", {"period": 14}, 15)
def f_rsi(bars, i, p):
    period = int(p.get("period", 14))
    if i < period:
        return None
    cs = _closes(bars, i, period + 1)
    diffs = [cs[k] - cs[k - 1] for k in range(1, len(cs))]
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    ag, al = _mean(gains), _mean(losses)
    rsi = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return _safe_tanh((50.0 - rsi) / 50.0)


@register("macd", "MACD 柱", "趋势", "MACD 柱相对价格归一化，捕捉趋势加速", {"fast": 12, "slow": 26, "signal": 9}, 35)
def f_macd(bars, i, p):
    fast, slow, sig = int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9))
    if i < slow + sig:
        return None
    cs = [b.close for b in bars[: i + 1]]
    ef, es = _ema_series(cs, fast), _ema_series(cs, slow)
    line = [a - b for a, b in zip(ef, es)]
    signal = _ema_series(line, sig)
    hist = line[-1] - signal[-1]
    return _safe_tanh(hist / max(cs[-1] * 0.01, 1e-9))


@register("bollinger_z", "布林带 Z 值", "反转", "价格偏离均线的标准差倍数，方向取反（均值回归）", {"period": 20}, 20)
def f_bollinger_z(bars, i, p):
    period = int(p.get("period", 20))
    if i < period - 1:
        return None
    cs = _closes(bars, i, period)
    sd = _pstdev(cs)
    if sd < 1e-9:
        return 0.0
    z = (cs[-1] - _mean(cs)) / sd
    return _safe_tanh(-z / 1.5)


@register("breakout", "通道突破", "趋势", "收盘价在 N 日高低通道中的相对位置", {"channel": 20}, 20)
def f_breakout(bars, i, p):
    c = int(p.get("channel", 20))
    if i < c:
        return None
    window = bars[i - c : i + 1]
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    if hi - lo < 1e-9:
        return 0.0
    pos = (bars[i].close - lo) / (hi - lo)
    return _safe_tanh((pos - 0.5) * 3.0)


@register("volume_spike", "放量确认", "量能", "成交量相对均值的放大程度，乘当日价格方向", {"period": 20}, 21)
def f_volume_spike(bars, i, p):
    period = int(p.get("period", 20))
    if i < period or bars[i - 1].close == 0:
        return None
    avg = _mean([b.volume for b in bars[i - period : i]])
    if avg <= 0:
        return 0.0
    direction = 1.0 if bars[i].close >= bars[i - 1].close else -1.0
    return _safe_tanh((bars[i].volume / avg - 1.0) / 0.8) * direction


@register("low_volatility", "低波偏好", "风险", "实现波动率低于目标时给正分，用于过滤高波动行情", {"period": 20, "target": 0.018}, 21)
def f_low_volatility(bars, i, p):
    period = int(p.get("period", 20))
    target = float(p.get("target", 0.018))
    if i < period:
        return None
    vol = _pstdev(_returns(_closes(bars, i, period + 1)))
    return _safe_tanh((target - vol) / max(target, 1e-9))


@register("atr_trend", "ATR 趋势", "趋势", "N 日价格变动除以 ATR×√N，波动率归一化的趋势强度", {"period": 14}, 15)
def f_atr_trend(bars, i, p):
    period = int(p.get("period", 14))
    if i < period:
        return None
    atr = _mean(_true_ranges(bars, i, period))
    change = bars[i].close - bars[i - period].close
    return _safe_tanh(change / max(atr * math.sqrt(period), 1e-9) / 1.5)


@register("reversal_1d", "隔夜反转", "反转", "单日涨跌幅的反向信号，捕捉短期过度反应", {"scale": 40}, 1)
def f_reversal_1d(bars, i, p):
    if i < 1 or bars[i - 1].close <= 0:
        return None
    ret = bars[i].close / bars[i - 1].close - 1.0
    return _safe_tanh(-ret * float(p.get("scale", 40)))


# --------------------------------------------------------------------------- #
# combination
# --------------------------------------------------------------------------- #
@dataclass
class CompositeScore:
    value: float
    contributions: dict[str, float]   # per-factor weighted contribution
    raw_values: dict[str, float]      # per-factor raw score, for the dashboard
    method: str
    coverage: float                   # fraction of selected weight that was available


def list_factors() -> list[dict[str, Any]]:
    return [
        {
            "name": m.name,
            "label": m.label,
            "category": m.category,
            "description": m.description,
            "default_params": dict(m.default_params),
            "min_bars": m.min_bars,
        }
        for m in FACTOR_REGISTRY.values()
    ]


def evaluate(bars: Sequence[Bar], i: int, specs: Sequence[FactorSpec], method: str = "weighted") -> CompositeScore:
    """Compute the composite score using ONLY bars[0..i] -- no look-ahead."""
    if not specs:
        raise ValueError("At least one factor must be selected")
    unknown = [s.name for s in specs if s.name not in FACTOR_REGISTRY]
    if unknown:
        raise ValueError(f"Unknown factor(s): {', '.join(unknown)}")
    if method not in ("weighted", "majority", "min", "max"):
        raise ValueError(f"Unknown combine method: {method}")

    raw: dict[str, float] = {}
    contributions: dict[str, float] = {}
    total_w = available_w = 0.0
    valid: list[tuple[float, float]] = []

    for spec in specs:
        total_w += spec.weight
        meta = FACTOR_REGISTRY[spec.name]
        params = {**meta.default_params, **spec.params}
        val = meta.fn(bars, i, params)
        if val is None:
            continue
        val = max(-1.0, min(1.0, float(val)))
        raw[spec.name] = val
        contributions[spec.name] = spec.weight * val
        available_w += spec.weight
        valid.append((spec.weight, val))

    if available_w <= 0:
        return CompositeScore(0.0, {}, raw, method, 0.0)

    if method == "majority":
        value = sum(w * (1.0 if v > 0 else (-1.0 if v < 0 else 0.0)) for w, v in valid) / available_w
    elif method == "min":
        value = min(v for _, v in valid)
    elif method == "max":
        value = max(v for _, v in valid)
    else:  # weighted
        value = sum(w * v for w, v in valid) / available_w

    return CompositeScore(max(-1.0, min(1.0, value)), contributions, raw, method, available_w / total_w if total_w else 0.0)
