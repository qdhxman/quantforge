# A 股路径运行手册（数据源接入 / 合规 / 盘中监控）

配套阅读：[就绪度审计](ashare-readiness-audit.md)、[规则与来源表](ashare-readiness-audit.md#三规则数值与一手来源2026-11-06-核实)、[通用架构](architecture.md)。

**本轮交付的工作模式：只监控 + 给信号，人工在券商客户端下单。** 系统不生成、不发送任何交易指令。

---

## 0. 先分清两条路径

| | 通用研究内核 (`quantforge/`) | A 股生产路径 (`quantforge/ashare/`) |
| --- | --- | --- |
| 用途 | 教学、因子组合演示、浏览器看板 | A 股策略验证、盘中监控 |
| 数据 | 合成行情（固定种子） | 券商 QMT/xtquant 同源行情 + 本地缓存 |
| 规则 | 通用连续竞价近似 | A 股涨跌停 / T+1 / 整手 / 真实费用 / 交易日历 |
| 验证 | Python↔JS 数值一致性 | IC/IR、分层、样本外、walk-forward、就绪度门禁 |
| 下单 | PaperBroker / Alpaca（三重闸门） | **无下单通道** |

两条路径**共用同一套因子库和信号引擎**，所以 A 股数字与通用数字的差异只来自市场规则，不会来自「动量」定义不同。

---

## 1. 本机（无 QMT 客户端）先跑验收

```bash
cd quantforge
python -m unittest discover -s tests -v        # 87 项
python scripts/ashare_pipeline.py              # 端到端验收，输入为明确标注的合成数据
```

产物：

| 路径 | 内容 |
| --- | --- |
| `data/ashare_synthetic_fixture/` | 合成行情缓存，`license=synthetic-test-fixture`，**绝不用于生产** |
| `reports/ashare_readiness.json` | 完整验收报告（含 assumptions、来源、gate 结果） |
| `reports/ashare_pipeline_log.txt` | 九步摘要 |
| `web/ashare_signals.json` | 监控面板快照 |
| `reports/ashare_monitor.db` | SQLite 监控历史 |

打开 `web/ashare.html` 看人工执行建议单。页面会明确标注 `SYNTHETIC TEST FIXTURE - NOT REAL MARKET DATA`。

---

## 2. 接入真实行情（QMT/xtquant 同源）

### 2.1 前置条件

- Windows 64 位机器（QMT 客户端要求；macOS/Linux 原生不支持）
- 已安装你券商的 **QMT 客户端**并用资金账号登录
- 行情权限可用（**注意：行情权限 ≠ 量化交易权限**；只做监控不需要交易权限，也不触发程序化报备）
- Python 能 import `xtquant`：用 QMT 自带解释器，或把 `<QMT>/bin.x64/Lib/site-packages` 加入 `PYTHONPATH`

### 2.2 字段自检（必做）

```bash
python examples/ashare_verify_feed.py
```

它会检查：xtquant 是否可用、`get_trading_dates` 是否返回真实交易日历、历史 K 线是否非空、`get_full_tick` 字段是否齐全、标的信息是否能读到。**任何一项失败就退出非零，绝不用模拟数据顶替。**

券商 xtquant 版本字段名可能不同。若报 `field mismatch`，在 `config/ashare/strategy.json` 的 `feed.field_map` 里校准，例如：

```json
"field_map": { "tick_last": "lastPrice", "tick_prev_close": "lastClose" }
```

### 2.3 落盘缓存

回测与监控必须读**同一份**数据，避免历史/实时口径漂移。`write_cache()` 会写入 `manifest.json`（来源、授权、构建时间、日期范围、日历权威性）、`calendar.csv`、`instruments.csv`、`bars/<code>.csv`、`snapshots.json`。

```python
from quantforge.ashare import XtdataFeed, write_cache, DataQualityGate
from quantforge.ashare.config import AShareSettings

s = AShareSettings.load()
feed = XtdataFeed(s.symbols, field_map=s.feed.get("field_map", {}),
                  market=s.feed.get("market", "SH"))
assert feed.preflight()["available"]

cal = feed.trading_calendar("2023-01-01", "2026-12-31")
assert cal.authoritative                      # 拒绝 weekday 猜测
bars = feed.history(s.symbols, cal.dates[0], cal.dates[-1])
ins = feed.instruments(s.symbols)
gate = DataQualityGate()
gate.check_history(bars, cal).assert_healthy()

write_cache("data/ashare_cache", bars, cal, ins,
            source="QMT/xtquant:<你的券商>", license="broker-terminal",
            note="授权范围自查；禁止再分发")
```

> **合规提醒**：数据授权因券商/供应商而异。`license` 字段不是法律意见，请自行确认「研究 / 展示 / 落地缓存 / 再分发」的许可范围；Tushare Pro 商用需另签。AkShare 属网页抓取封装，无 SLA、无授权，**本生产路径不采用**。

### 2.4 严格回测 + 验证

```bash
python scripts/ashare_pipeline.py --config config/ashare/strategy.json
```

真实数据下把 `--allow-unverified-calendar` 保持关闭；就绪度四道 gate（因子有效性 / 分层单调 / walk-forward / 3 年跨度）**全 PASS** 才有资格进入模拟盘。

---

## 3. 盘中监控

```bash
python examples/ashare_monitor.py --once          # 单周期，打印完整结果
python examples/ashare_monitor.py --cycles 100    # 连续监控
python examples/ashare_monitor.py --offline --once # 用缓存回放（非实时，标注 OFFLINE）
```

监控循环每周期：

1. 判断交易时段（`market_phase`）：非连续竞价时段直接跳过，不发信号
2. 拉快照 → `DataQualityGate` 检查时间戳新鲜度（默认 60s）、来源、OHLC 一致性、价格是否越涨跌停
3. **质量门禁失败 → 抑制本周期全部信号并告警**（fail-closed），不会拿脏数据算因子
4. 用与回测同源的前复权历史算信号
5. 生成 `ManualOrderTicket`（人工执行建议单），逐条列出 11 项检查
6. 写 SQLite、JSON 快照、JSONL 审计日志；告警默认只打印到控制台

`webhook_url` 默认为空——**默认不向外部发任何请求**。要推送到手机需你显式配置，那属于外部动作。

### 人工执行建议单字段

| 字段 | 含义 |
| --- | --- |
| `symbol / name / board` | 6 位代码、名称、板块 |
| `side / signal_score / signal_reason` | 方向、综合得分、可解释依据 |
| `last_price / limit_up / limit_down` | 最新价与当日涨跌停价 |
| `suggested_qty` | 已按板块整手规则规范化后的数量 |
| `suggested_price_low/high` | 建议限价区间（±0.5%，仅参考） |
| `estimated_fees` | 佣金 / 印花税 / 过户费分项预估 |
| `tradable` | 11 项检查全通过才为 true |
| `checks` | 逐条规则判定（数据质量、停牌、ST、涨跌停、T+1、仓位、金额、板块权限等） |
| `notes` | 明确写「系统不会自动下单」「数量按假设资金估算」 |

**执行前必须人工复核**：实际可用资金与持仓、券商客户端里的实时涨跌停价、板块权限、T+1 可用数量。系统不接入你的账户，因此 `T+1 可用持仓` 与数量估算默认基于 `assumed_equity`，不是真实账户。

---

## 4. 合规清单（按你的选择：只监控、人工下单）

| 事项 | 本轮状态 | 说明 |
| --- | --- | --- |
| 程序化交易报告义务 | **不触发** | 细则定义为「通过计算机程序自动生成或下达交易指令」；本系统不下达指令，由人手工下单。若将来改为自动下单，**必须**在首次交易前向券商报告并取得确认 |
| 《程序化交易委托协议》 | 不需要 | 同上；改为自动下单时需签署 |
| QMT/PTrade **交易**权限 | 不需要 | 监控只需行情权限 |
| 板块权限 | 需自查 | 科创板通常要求 50 万资产 + 24 个月经验；创业板需单独开通 |
| 数据源授权 | 需自查 | 券商终端行情的使用范围、落地缓存、再分发条款 |
| 风险测评 | 需自查 | 券商对量化相关功能的等级要求 |
| 投资建议合规 | 不适用 | 输出为内部决策支持，不对外提供投顾服务 |

**如果未来要改成自动下单**（本轮未实现，也不建议现在做）：依次完成券商量化权限开通 → 程序化交易报告 → 委托协议签署 → 取得回执 → 实现 `QMTBroker`（`xtquant.xttrader`）/ PTrade 适配器 → 全链路 paper 验证 → 实盘小额验证 → 逐笔对账。任何一步缺失都不要打开实盘开关。

---

## 5. 故障处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `FeedUnavailable: QMT/xtquant 不可用` | 客户端未登录 / xtquant 不在 PYTHONPATH | 按报错里 5 步指引检查；系统不会退化到模拟数据 |
| `[CRITICAL] stale quote` | 行情时间戳超过 60s（休市、断线、QMT 卡住） | 本周期信号被抑制；检查客户端连接。休市时属正常 |
| `[CRITICAL] outside limit` | 快照最新价越过按前收盘算的涨跌停 | 多为前收盘口径不一致或新股/ST 特例；核对 `instruments.csv` 的 `is_st` 与 `listing_date` |
| `field mismatch` | 券商 xtquant 版本字段不同 | 用 `feed.field_map` 校准，重跑 `ashare_verify_feed.py` |
| `refusing to backtest on a NON-authoritative calendar` | 用了 `weekday_fallback` | 从 QMT `get_trading_dates` 或授权数据商加载真实交易日历 |
| 回测 `NOT_READY` | IC/IR、分层、walk-forward 或 3 年跨度未过 | 这是**正确拦截**，不要改阈值绕过；回去改策略或补数据 |

---

## 6. 目录速查

```
quantforge/ashare/
├── rules.py        规则常量 + 一手来源 + 板块/涨跌停/整手/T+1/费用/时段/日历
├── feeds.py        数据契约、XtdataFeed、CachedFeed、DataQualityGate
├── engine.py       A 股严格回测（涨停/跌停/停牌/T+1/真实费用/拦截统计）
├── validation.py   IC/IR、分层回测、样本外、walk-forward、就绪度门禁
├── monitor.py      盘中监控 + 人工执行建议单（零下单调用）
├── config.py       配置加载
└── synthetic.py    明确标注的合成测试 fixture
config/ashare/strategy.json     一份配置驱动回测与监控
examples/ashare_verify_feed.py 行情接入自检
examples/ashare_monitor.py     监控运行入口
scripts/ashare_pipeline.py     端到端验收
docs/ashare-readiness-audit.md 差距审计与放行清单
docs/ashare-runbook.md         本文件
web/ashare.html                人工执行建议单看板
```
