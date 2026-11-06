# 策略配置

策略就是一份 JSON（或 YAML）文件。同一个文件既能被 CLI、API、回测引擎加载，也会被自动生成到 `web/presets.js` 供看板使用。改因子不用改代码。

```bash
quantforge backtest -c config/strategies/momentum.json
quantforge signals  -c config/strategies/mean_reversion.json
# YAML 需要 pip install -e '.[yaml]'
quantforge backtest -c config/strategies/aggressive_breakout.yaml
```

## 字段全表

### 顶层

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `name` | str | `"default"` | 报告标题、审计日志标识 |
| `description` | str | `""` | 看板预设说明 |
| `symbols` | list[str] | 4 个示例标的 | 参与的标的；数据中找不到的会被跳过 |

### `factors[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | str | 已注册因子名，见 [factors.md](factors.md) |
| `weight` | float ≥ 0 | 权重；0 = 关闭；会被重新归一化 |
| `params` | dict | 覆盖该因子的 `default_params` |

至少需要一个因子，未知因子名会直接报错并列出可用列表。

### `signal`

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `buy_threshold` | 0.18 | 综合得分 ≥ 此值 → BUY |
| `sell_threshold` | -0.18 | 综合得分 ≤ 此值 → SELL |
| `smoothing` | 0.0 | EMA 衰减，`[0,1)`，越大越平滑、越迟钝 |
| `min_holding_bars` | 2 | 方向翻转前至少持有的 bar 数 |
| `combine_method` | `"weighted"` | `weighted` / `majority` / `min` / `max` |

要求 `buy_threshold > sell_threshold`。

### `backtest`

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `initial_cash` | 100000 | 期初资金 |
| `commission_bps` | 5.0 | 单边手续费（基点） |
| `slippage_bps` | 5.0 | 单边滑点（基点） |
| `lot_size` | 1 | 最小交易单位（A 股设 100） |
| `min_order_value` | 500 | 小于此金额的调仓忽略 |
| `max_position_pct` | 0.35 | 信号层单票目标仓位上限 |
| `max_gross_exposure_pct` | 0.95 | 组合总目标仓位上限 |
| `allow_short` | false | 回测层是否允许负目标仓位 |

### `risk`

见 [risk-controls.md](risk-controls.md) 全表。注意 `risk.max_position_pct` 是**硬校验**，`backtest.max_position_pct` 是**目标生成**，两者取小。

### `trading`

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `mode` | `"paper"` | `"paper"` / `"live"`；live 需要三重闸门 |
| `poll_seconds` | 60 | `run()` 的循环间隔 |
| `journal_path` | `logs/trading-journal.jsonl` | 审计日志路径 |
| `order_type` | `"market"` | 目前市价/限价均传给适配器 |
| `max_orders_per_cycle` | 10 | 单周期最多提交多少笔 |
| `live_confirmation_env` | `QFI_CONFIRM_LIVE_TRADING` | 确认短语的变量名 |

## 三份预设

| 文件 | 因子 | 组合 | 特点 |
| --- | --- | --- | --- |
| `momentum.json` | momentum / ma_cross / macd / volume_spike / low_volatility | weighted | 默认；阈值 0.18，平滑 0.25，滞后 3 bar |
| `mean_reversion.json` | bollinger_z / rsi / reversal_1d / low_volatility | weighted | 阈值更低、冷却 2 bar、拉黑 NVDA，用来演示风控拦截 |
| `aggressive_breakout.yaml` | breakout / atr_trend / volume_spike | **max** | 最激进组合、双倍成本、更高限额，用来演示激进配置的代价 |

## 环境变量覆盖

| 变量 | 作用 |
| --- | --- |
| `QFI_KILL_SWITCH=1` | **强制**把 `risk.kill_switch` 置为 true（加载配置时生效），所有下单被拒 |
| `QFI_ALLOW_LIVE=1` | 实盘闸门 1/3 |
| `QFI_CONFIRM_LIVE_TRADING=I_UNDERSTAND` | 实盘闸门 2/3 |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` / `ALPACA_BASE_URL` | Alpaca 凭据；不写入配置文件 |

只有 kill switch 会覆盖配置对象本身，且方向是**更保守**。其余环境变量只在实盘路径读取。复制 `.env.example` 为 `.env` 后再填，`.env` 已在 `.gitignore` 中。

## 用代码构造 / 修改配置

```python
from quantforge.config import FactorSpec, default_config

cfg = default_config()
cfg.signal.buy_threshold = 0.25
cfg.factors.append(FactorSpec("breakout", 0.5, {"channel": 30}))
cfg.risk.blacklist.append("NVDA")
cfg.risk.max_daily_loss_pct = 0.02

print(cfg.to_dict())          # 可直接 POST 到 /api/backtest
```
