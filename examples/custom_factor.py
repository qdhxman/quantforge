"""Register a custom factor and drop it into a strategy.

    python examples/custom_factor.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.backtest import BacktestEngine  # noqa: E402
from quantforge.config import FactorSpec, default_config  # noqa: E402
from quantforge.data import generate_synthetic  # noqa: E402
from quantforge.factors import FACTOR_REGISTRY, register  # noqa: E402


@register(
    name="skewness_reversal",
    label="偏度反转",
    category="自定义",
    description="过去 N 日收益分布的偏度取反：单边急涨后给负分",
    default_params={"period": 20},
    min_bars=21,
)
def f_skewness_reversal(bars, i, p):
    period = int(p.get("period", 20))
    if i < period:
        return None
    rets = [bars[k].close / bars[k - 1].close - 1 for k in range(i - period + 1, i + 1)]
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / len(rets)
    if var < 1e-12:
        return 0.0
    skew = sum((r - mu) ** 3 for r in rets) / len(rets) / (var ** 1.5)
    return math.tanh(-skew / 2.0)


def main() -> None:
    print(f"已注册 {len(FACTOR_REGISTRY)} 个因子，新增：skewness_reversal")
    cfg = default_config()
    cfg.name = "custom-factor-demo"
    cfg.factors = [
        FactorSpec("momentum", 1.0),
        FactorSpec("skewness_reversal", 0.7, {"period": 20}),
    ]
    result = BacktestEngine(cfg).run(generate_synthetic())
    print(result.summary())
    print("因子贡献：", [(f["name"], f["share"]) for f in result.factor_impact])


if __name__ == "__main__":
    main()
