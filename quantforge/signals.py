"""Composite score -> an actionable, explainable signal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .config import StrategyConfig
from .data import Bar
from .factors import CompositeScore, evaluate


@dataclass
class Signal:
    date: str
    symbol: str
    action: str                       # BUY | SELL | HOLD
    score: float                      # smoothed composite in [-1, 1]
    raw_score: float
    target_weight: float | None       # None = keep the current position untouched
    contributions: dict[str, float] = field(default_factory=dict)
    raw_values: dict[str, float] = field(default_factory=dict)
    coverage: float = 1.0
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "date": self.date, "symbol": self.symbol, "action": self.action,
            "score": round(self.score, 6), "raw_score": round(self.raw_score, 6),
            "target_weight": None if self.target_weight is None else round(self.target_weight, 6),
            "contributions": {k: round(v, 6) for k, v in self.contributions.items()},
            "raw_values": {k: round(v, 6) for k, v in self.raw_values.items()},
            "coverage": round(self.coverage, 4), "reason": self.reason,
        }


class SignalEngine:
    """Stateful across bars for score smoothing and flip hysteresis.

    One instance per backtest / live run. State is per-symbol so the same
    engine can drive a whole portfolio.
    """

    def __init__(self, config: StrategyConfig):
        self.cfg = config
        self._eff: dict[str, float] = {}
        self._side: dict[str, int] = {}
        self._last_flip: dict[str, int] = {}
        self._last_weight: dict[str, float] = {}

    def reset(self) -> None:
        self._eff.clear()
        self._side.clear()
        self._last_flip.clear()
        self._last_weight.clear()

    def _panel(self, bars: Sequence[Bar], i: int) -> CompositeScore:
        return evaluate(bars, i, self.cfg.factors, self.cfg.signal.combine_method)

    def evaluate(self, bars: Sequence[Bar], i: int, symbol: str) -> Signal:
        sc = self.cfg.signal
        panel = self._panel(bars, i)
        raw = panel.value
        smoothing = sc.smoothing
        prev = self._eff.get(symbol, raw)
        eff = (1.0 - smoothing) * raw + smoothing * prev
        self._eff[symbol] = eff

        desired = 1 if eff >= sc.buy_threshold else (-1 if eff <= sc.sell_threshold else 0)
        side = self._side.get(symbol, 0)
        blocked = False
        if desired != 0 and desired != side:
            since = i - self._last_flip.get(symbol, -10 ** 9)
            if since < sc.min_holding_bars:
                desired = side  # whipsaw suppressed
                blocked = True
            else:
                self._side[symbol] = desired
                self._last_flip[symbol] = i

        max_pos = min(self.cfg.backtest.max_position_pct, self.cfg.risk.max_position_pct)
        # Crossing the threshold earns a meaningful base position; score strength
        # then modulates within [base, max]. Scaling linearly from zero would
        # leave the portfolio ~85% in cash on an ordinary signal.
        thr = min(0.95, max(abs(sc.buy_threshold), abs(sc.sell_threshold), 0.01))
        intensity = min(1.0, max(0.0, (abs(eff) - thr) / (1.0 - thr)))
        scale = 0.45 + 0.55 * intensity
        if desired == 1:
            action, weight = "BUY", max_pos * scale
            self._last_weight[symbol] = weight
        elif desired == -1:
            action = "SELL"
            weight = -max_pos * scale if self.cfg.risk.allow_short else 0.0
            self._last_weight[symbol] = weight
        else:
            action, weight = "HOLD", None

        if blocked:
            reason = f"方向翻转被 min_holding_bars={sc.min_holding_bars} 抑制，维持原方向"
        elif panel.coverage < 1.0:
            reason = f"综合得分 {eff:+.3f}（{action}），因子覆盖率 {panel.coverage:.0%}，其余因子仍在预热"
        else:
            reason = f"综合得分 {eff:+.3f}（{action}），阈值 ±{abs(sc.buy_threshold):.2f}"

        leaders = sorted(panel.contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)[:2]
        if leaders:
            reason += "；主导因子 " + "、".join(f"{k}({v:+.2f})" for k, v in leaders)

        return Signal(
            date=bars[i].date, symbol=symbol, action=action, score=eff, raw_score=raw,
            target_weight=weight, contributions=panel.contributions, raw_values=panel.raw_values,
            coverage=panel.coverage, reason=reason,
        )

    def evaluate_many(self, data: dict[str, list[Bar]], index_by_symbol: dict[str, int]) -> list[Signal]:
        out = []
        for symbol, bars in data.items():
            i = index_by_symbol.get(symbol)
            if i is None or i >= len(bars):
                continue
            out.append(self.evaluate(bars, i, symbol))
        return out
