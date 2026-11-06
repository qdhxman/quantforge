# 风控规则

**任何** `OrderRequest` 在到达券商之前，都必须通过 `RiskManager.evaluate()`。它返回全部规则的判定结果（不只是第一个失败项），因此看板能精确显示「被哪条规则、因为什么数值拦下」。

规则按下面顺序检查，命中失败即拒绝该单（其余规则仍会全部计算并展示）：

| # | rule | 名称 | 判定 | 主要挡住什么 |
| --- | --- | --- | --- | --- |
| 1 | `KILL_SWITCH` | 紧急停机 | `risk.kill_switch=false` 且 `QFI_KILL_SWITCH≠"1"` 且引擎未 halt | 事故时一键冻结全部下单 |
| 2 | `SYMBOL_BLACKLIST` | 标的黑名单 | 标的不在 `risk.blacklist` | 停牌/财报/不熟悉的票 |
| 3 | `MIN_QTY` | 最小下单量 | `qty > 0` | 零股、空单 |
| 4 | `MAX_ORDER_NOTIONAL` | 单笔金额上限 | `qty×price ≤ max_order_notional` | fat finger、配置写错数量级 |
| 5 | `MAX_POSITION_WEIGHT` | 单票仓位上限 | 成交后 `|持仓市值|/权益 ≤ max_position_pct` | 单票集中度 |
| 6 | `MAX_GROSS_EXPOSURE` | 总敞口上限 | 成交后 `总持仓/权益 ≤ max_gross_exposure_pct` | 组合杠杆与相关性叠加 |
| 7 | `MAX_DAILY_LOSS` | 日内亏损熔断 | `当日权益/日初权益 − 1 > −max_daily_loss_pct` | 单日连续亏损扩大 |
| 8 | `MAX_DRAWDOWN` | 回撤熔断 | `权益/历史峰值 − 1 > −max_drawdown_pct` | 长周期失控 |
| 9 | `COOLDOWN` | 交易冷却 | 距该标的上次成交 ≥ `cooldown_bars` | 信号抖动导致过度交易 |
| 10 | `BUYING_POWER` | 购买力 | 买单金额 ≤ 可用现金 | 超额下单 |
| 11 | `SHORTING_DISABLED` | 禁止做空 | `allow_short=true` 或卖出量 ≤ 当前多仓 | 误发裸卖空 |
| 12 | `PENDING_ORDER_LIMIT` | 挂单数量 | 本周期挂单数 < `max_orders_per_cycle` | 循环异常导致刷单 |

## 配置示例

```json
"risk": {
  "max_order_notional": 30000,
  "max_position_pct": 0.35,
  "max_gross_exposure_pct": 0.95,
  "max_daily_loss_pct": 0.03,
  "max_drawdown_pct": 0.20,
  "cooldown_bars": 1,
  "blacklist": [],
  "kill_switch": false,
  "allow_short": false
}
```

`backtest.max_position_pct` 与 `risk.max_position_pct` 同时存在时，信号层取两者较小值，风控层再按 `risk` 的值硬校验。看板上的「单票仓位上限」滑块会同时更新两者，避免前后不一致。

## 三份预设的风控差异（用来观察效果）

| 预设 | 单票 | 单笔 | 日内熔断 | 回撤熔断 | 冷却 | 黑名单 | 典型现象 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| momentum | 35% | ¥30k | 3% | 20% | 1 | — | 默认 0 次拦截 |
| mean_reversion | 30% | ¥25k | 2% | 15% | 2 | NVDA | 大量 `COOLDOWN` / `SYMBOL_BLACKLIST` 拦截 |
| aggressive_breakout | 40% | ¥40k | 5% | 25% | 1 | — | 组合用 `max`、阈值低，成交更频繁 |

**在看板里试这个**：保持默认策略，勾选左侧「紧急停机」再运行回测 → 所有委托被 `KILL_SWITCH` 拦下，成交数归零、拦截数骤增，右下角能看到每条规则的判定明细。把「单票仓位上限」拉到 5% 也能看到 `MAX_POSITION_WEIGHT` 生效。

## 熔断之后的语义

`MAX_DAILY_LOSS` / `MAX_DRAWDOWN` 只**拒绝新开仓方向的委托**，不会自动平掉已有仓位；是否需要减仓由策略信号决定。这是刻意的设计：风控层不应该偷偷替策略做交易决策。如果需要「触发熔断即全平」，在 `LiveTradingEngine` 外层加一个显式的 de-risk 处理器，并写进审计日志。

## 实盘额外防线

风控规则是**代码内层**；外面还有 `AlpacaBroker` 的三重闸门（配置 + 环境变量 + 非 paper 端点）、`QFI_KILL_SWITCH` 环境变量、`engine.halt()`、以及只追加的 JSONL 审计日志。详见 [live-trading.md](live-trading.md)。
