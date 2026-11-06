# 因子库

所有因子统一签名 `fn(bars, i, params) -> float | None`，返回值裁剪到 `[-1, +1]`：**正分看多，负分看空**；历史不足返回 `None`，该因子被跳过且剩余权重自动重新归一化。因子只能读 `bars[0..i]`。

| name | 名称 | 类别 | 公式 / 逻辑 | 方向 | 预热 | 默认参数 |
| --- | --- | --- | --- | --- | --- | --- |
| `momentum` | 动量 ROC | 趋势 | `tanh(ret_N / (σ_daily·√N) / 1.5)` | 涨得多 → 正 | 21 | `lookback=20` |
| `ma_cross` | 均线交叉 | 趋势 | `tanh((MA_fast − MA_slow)/MA_slow × 12)` | 多头排列 → 正 | 30 | `fast=10, slow=30` |
| `rsi` | RSI 超买超卖 | 反转 | `tanh((50 − RSI)/50)`，Cutler 版简单均值 | 超卖 → 正 | 15 | `period=14` |
| `macd` | MACD 柱 | 趋势 | `tanh(hist / (close×0.01))`，EMA(12,26,9) | 柱转正 → 正 | 35 | `fast=12, slow=26, signal=9` |
| `bollinger_z` | 布林带 Z 值 | 反转 | `tanh(−z/1.5)`，`z=(close−μ)/σ` | 跌破下轨 → 正 | 20 | `period=20` |
| `breakout` | 通道突破 | 趋势 | `tanh((pos−0.5)×3)`，`pos=(close−min)/(max−min)` | 接近上轨 → 正 | 20 | `channel=20` |
| `volume_spike` | 放量确认 | 量能 | `tanh((vol/MA_vol − 1)/0.8) × sign(当日涨跌)` | 放量上涨 → 正 | 21 | `period=20` |
| `low_volatility` | 低波偏好 | 风险 | `tanh((target − σ_daily)/target)` | 低波 → 正 | 21 | `period=20, target=0.018` |
| `atr_trend` | ATR 趋势 | 趋势 | `tanh(Δclose / (ATR×√N) / 1.5)` | 趋势向上 → 正 | 15 | `period=14` |
| `reversal_1d` | 隔夜反转 | 反转 | `tanh(−ret_1d × 40)` | 昨日下跌 → 正 | 1 | `scale=40` |

> 波动率统一用**总体标准差**（除以 n，不是 n−1），EMA 以序列首值作种子。这两条约定是 JS 引擎能逐位对齐的前提，改动时务必同步两边。

## 组合方式

`signal.combine_method`：

| 值 | 计算 | 适合 |
| --- | --- | --- |
| `weighted`（默认） | `Σ(wᵢ·vᵢ) / Σwᵢ` | 通用；权重表达置信度 |
| `majority` | `Σ(wᵢ·sign(vᵢ)) / Σwᵢ` | 因子量纲差异大时，只看方向 |
| `min` | `min(vᵢ)` | 保守：所有因子都看多才看多 |
| `max` | `max(vᵢ)` | 激进：任一因子看多就看多（回撤通常更大） |

权重为 0 的因子等于关闭；权重越大话语权越大。`CompositeScore.coverage` 报告本 bar 有多少比例的权重真正可用（预热期会小于 1），信号文字依据里会写明。

## 从得分到信号

1. `eff = (1−smoothing)·raw + smoothing·prev`（EMA 平滑，按标的独立维护）。
2. `eff ≥ buy_threshold` → `BUY`；`eff ≤ sell_threshold` → `SELL`；否则 `HOLD`（保持现有仓位不动）。
3. 方向翻转受 `min_holding_bars` 抑制，避免来回打脸；被抑制时 bar 上标记原因。
4. 目标仓位 `= max_position_pct × (0.45 + 0.55 × intensity)`，其中 `intensity = clamp((|eff|−thr)/(1−thr), 0, 1)`。跨过阈值就给一个有意义的基础仓位，得分越强仓位越接近上限；`HOLD` 不改仓位，`SELL` 在 `allow_short=false` 时目标为 0。
5. 所有标的的目标权重之和超过 `max_gross_exposure_pct` 时按比例缩放。

## 自定义因子

```python
from quantforge.factors import register
import math

@register("my_factor", "我的因子", "自定义", "说明", {"period": 5}, 5)
def f_my_factor(bars, i, p):
    n = p["period"]
    if i < n or bars[i - n].close == 0:
        return None
    return math.tanh((bars[i].close / bars[i - n].close - 1) * 10)
```

注册后即可写进策略 JSON：`{"name": "my_factor", "weight": 0.8, "params": {"period": 8}}`。完整可运行示例见 `examples/custom_factor.py`。

新增因子请补一条「截断未来数据结果不变」的测试，见 `tests/test_factors.py`。
