# 自动执行与实盘安全

> **默认永远只跑模拟盘。** 本文描述的是「如果将来你决定接真实资金，需要显式做哪些事」。本项目作者未用真实资金运行过它，也不建议在没有充分测试、合规评估和小额验证之前这么做。

## 执行链路

```
LiveTradingEngine.run_cycle()
  ├─ 取最新 bars / 报价
  ├─ SignalEngine → 信号 + 目标仓位
  ├─ 组装 OrderRequest（client_order_id 幂等键）
  ├─ RiskManager.evaluate() → 12 条规则全部判定
  │    └─ 拒绝 → Journal: RISK_BLOCK
  ├─ Broker.submit_order()
  │    └─ Journal: ORDER_SUBMITTED
  └─ 账户快照 / 峰值与日初权益更新
```

`run(interval, max_cycles)` 只是给 `run_cycle()` 套一层循环。每周期都会重新读取 `QFI_KILL_SWITCH`；`halt()` 可随时冻结。

## 三重闸门

`AlpacaBroker(enable_live=True)` 在构造时调用 `_assert_live_gate()`，**全部**满足才允许创建实盘连接，否则抛 `PermissionError`：

| # | 条件 | 为什么 |
| --- | --- | --- |
| 1 | 配置 `trading.mode = "live"` 且代码里显式 `enable_live=True` | 防止配置文件被误改成 live |
| 2 | 环境变量 `QFI_ALLOW_LIVE=1` | 防止测试脚本/CI 环境误连生产 |
| 3 | 环境变量 `QFI_CONFIRM_LIVE_TRADING=I_UNDERSTAND` | 要求一次有意识的人工确认 |
| 4 | `base_url` 指向 `https://api.alpaca.markets`（不含 `paper`） | 防止「以为在实盘、其实连模拟」或反之 |
| 5 | `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` 非空 | 凭据不落代码库 |

此外 `LiveTradingEngine` 启动时会交叉校验：配置写 `live` 但券商是模拟实例 → 拒绝；配置写 `paper` 但券商是实盘实例 → 拒绝。

```python
from quantforge.brokers import AlpacaBroker
from quantforge.live import LiveTradingEngine

# 安全默认：paper 端点，不触发任何闸门
broker = AlpacaBroker()                      # 读 ALPACA_* 环境变量，默认 PAPER_URL
engine = LiveTradingEngine(cfg, broker, data)

# 真要实盘：先在 shell 里 export 两个变量，然后
broker = AlpacaBroker(
    api_key=..., secret_key=...,
    base_url="https://api.alpaca.markets",
    enable_live=True,                        # 少这一样就抛错
)
```

**不要**把 `ALPACA_API_KEY` 写进 `.json` / `.py` / 提交记录。用 `.env`（已 gitignore）或系统密钥管理。

## 紧急停机

三种方式，任意一种都能冻结下单：

```bash
export QFI_KILL_SWITCH=1        # 环境变量，加载配置时强制 risk.kill_switch=true
```

```python
engine.halt("drawdown review")  # 代码内立即冻结调度循环
```

```bash
curl -X POST http://127.0.0.1:8000/api/trading/halt -H 'Content-Type: application/json' -d '{"reason":"manual"}'
```

看板左侧也有「紧急停机」勾选框，勾选后回测与模拟盘里每一笔委托都会被 `KILL_SWITCH` 规则拦下，可以直接看到效果。

停机**不会自动平仓**，也不会撤销已提交到券商的委托；需要的话显式调用 `broker.cancel_order()` 并写审计。

## 审计日志

`Journal` 以 JSONL 只追加写入 `logs/trading-journal.jsonl`，事件类型：

`ENGINE_START` / `ENGINE_HALT` / `ENGINE_RESUME` / `ENGINE_STOP` / `ORDER_SUBMITTED` / `RISK_BLOCK` / `BACKTEST`。

键名含 `key` / `secret` / `token` / `password` / `authorization` 的字段会自动写成 `***`。日志里保留 `client_order_id` 用于幂等排查。

## 上线前清单

- [ ] 用真实（前复权）数据做样本外 / 滚动窗口检验，不是只看仓库合成数据
- [ ] 至少跑满一个完整周期的 paper trading，逐笔核对 `Journal` 与券商回单
- [ ] 确认手续费、滑点、整手、交易日历、T+1、涨跌停等市场规则已按目标市场建模
- [ ] 把 `risk` 各项限额调到明显小于你能承受的最大亏损
- [ ] 明确「熔断后是否减仓」的策略，并单独实现 + 测试
- [ ] 确认停机路径能在进程崩溃 / 重启后仍然生效（例如把 kill switch 放在持久存储）
- [ ] 检查网络失败、重复提交、部分成交、订单状态回调的处理
- [ ] 确认符合所在司法辖区的监管要求与券商 API 条款
- [ ] 用极小金额验证，再考虑任何规模调整

## 明确不做的事

不内置任何「稳赚策略」，不提供杠杆建议，不自动替你调大限额，不在代码里保存凭据，不绕过任何券商的风控。
