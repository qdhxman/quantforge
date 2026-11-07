# QuantForge

**因子自由组合 → 回测验证 → 数据驱动信号 → 受风控约束的自动执行。**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Core deps](https://img.shields.io/badge/core%20deps-0%20(stdlib%20only)-orange.svg)](#设计取舍)

> English: QuantForge is a dependency-light quantitative research platform. Pick and weight factors,
> backtest them with realistic next-bar execution, inspect explainable signals on a dashboard, and
> run an autonomous order loop that is **paper-first and guarded by 12 pre-trade risk rules**.

🌐 **[在线交互看板 · 点开就能玩](https://quantforge-dashboard.app.workbuddy.host/?sharecode=BW7RIDSIEK)** — 浏览器里自由勾选因子、调权重和阈值、跑回测、看净值曲线与风控拦截，不需要安装任何东西，也不依赖后端。

📡 同一站点右上角「A 股监控台 ↗」进入 **[A 股盘中监控页](https://quantforge-dashboard.app.workbuddy.host/ashare.html?sharecode=BW7RIDSIEK)** — 人工执行建议单、11 项合规检查、涨跌停/T+1/费用预估与数据质量门禁。**该页当前展示的是明确标注的合成演示快照，不是实时行情，不可用于交易决策**；真实数据接入见 [A 股运行手册](docs/ashare-runbook.md)。

---

## ⚠️ 先读这一段

- 项目**默认只跑模拟盘**。真实下单需要同时打开配置开关、两个环境变量、并把 Alpaca 地址切到实盘端点；任何一项缺失都会抛 `PermissionError`。见 [docs/live-trading.md](docs/live-trading.md)。
- 仓库自带的行情是**程序生成的合成数据**（含一段刻意加入的熊市区间），不是真实市场数据，不能用来评价任何策略好坏。
- 本项目是研究/教学框架，**不是投资建议，也不是开箱即用的赚钱系统**。回测收益不代表未来收益。见 [docs/disclaimer.md](docs/disclaimer.md)。

---

## 5 分钟上手

需要 Python 3.10+，不需要数据库、不需要 API key、不需要联网。

```bash
git clone https://github.com/qdhxman/quantforge.git
cd quantforge
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
```

```bash
quantforge factors                                   # 列出 10 个内置因子
quantforge backtest -c config/strategies/momentum.json --report report.md
quantforge signals  -c config/strategies/momentum.json
quantforge paper    -c config/strategies/momentum.json --steps 30
```

第一次回测（内置合成数据，504 根日线，4 个标的）的真实输出：

```
[momentum-blend] 2024-01-02→2025-12-05 | 收益 13.77% | 夏普 0.7705 | 最大回撤 -14.66% | 成交 476 笔 | 风控拦截 0 次
```

同期等权买入持有 32.90%，但最大回撤 -26.51%。**这个对比不是「策略跑赢了」，而是「策略用一部分上涨弹性换来了近乎减半的回撤」**——样例里那段熊市区间就是为了让风控和防御性因子的作用看得见。因子怎么选、阈值怎么调，全都可以在看板里改，结果会立刻重算。

启动决策看板（本地 API + 静态页面）：

```bash
pip install -e '.[api]'
quantforge serve --port 8000
# API 文档 http://127.0.0.1:8000/docs
# 交互看板 把浏览器指向 web/index.html，或用下面的一行静态服务器
python -m http.server 8080 --directory web      # http://127.0.0.1:8080
```

`web/index.html` 是**零后端依赖**的：因子、信号、回测、风控、模拟盘都在浏览器里用 `web/engine.js` 实时算，双击文件也能打开（数据来自 `web/data.js`）。

---

## 能做什么

| 能力 | 实现 | 入口 |
| --- | --- | --- |
| 自由选因子 / 加权组合 | 10 个内置因子 + `@register` 插件式注册；4 种组合方式（加权 / 投票 / 最保守 / 最激进） | `quantforge/factors.py` |
| 参数化信号 | 买卖阈值、EMA 平滑、翻转滞后（最短持仓 bar）、目标仓位 | `quantforge/signals.py` |
| 回测 | 逐 bar 事件驱动、**信号用 t 日收盘、成交在 t+1 日开盘**，含手续费/滑点/整手 | `quantforge/backtest.py` |
| 绩效与归因 | 总收益、CAGR、波动率、夏普、索提诺、最大回撤、Calmar、胜率、盈亏比、因子贡献度、买入持有对照 | `quantforge/metrics.py` |
| 决策支持看板 | 净值/回撤曲线、KPI、最新信号及**文字依据**、因子贡献、成交明细、风控拦截明细 | `web/` |
| 自动执行 | 订单状态机 → 风控闸门 → 券商适配器 → JSONL 审计日志 → 可暂停/可停机调度循环 | `quantforge/live.py` |
| 风控 | 12 条盘前硬规则，逐条返回判定结果（不是只给一个「拒绝」） | `quantforge/risk.py` |
| 券商 | `PaperBroker`（默认，完整撮合）、`AlpacaBroker`（REST，三重闸门） | `quantforge/brokers.py` |
| API / CLI | FastAPI 可选扩展 + 7 个 CLI 子命令 | `quantforge/api.py`, `quantforge/cli.py` |

---

## 项目结构

```
quantforge/
├── quantforge/                  # 计算内核：零第三方依赖
│   ├── config.py                #   策略配置 dataclass / JSON·YAML 加载 / 环境变量覆盖
│   ├── data.py                  #   Bar、CSV、yfinance 适配器、确定性合成行情
│   ├── factors.py               #   因子注册表 + 10 个因子 + 组合器
│   ├── signals.py               #   综合得分 → 可解释的 BUY/SELL/HOLD 信号
│   ├── portfolio.py             #   现金 / 持仓 / 已实现盈亏 / 成本
│   ├── backtest.py              #   次-bar-open 回测引擎
│   ├── metrics.py               #   绩效指标 + Markdown 报告
│   ├── risk.py                  #   12 条盘前风控规则
│   ├── orders.py                #   订单状态机（非法状态转换直接抛错）
│   ├── brokers.py               #   Broker ABC / PaperBroker / AlpacaBroker
│   ├── live.py                  #   自动执行调度循环（run_cycle 可单步测试）
│   ├── journal.py               #   只追加 JSONL 审计日志 + 敏感字段脱敏
│   ├── api.py                   #   可选 FastAPI 服务
│   └── cli.py                   #   命令行
├── web/                         # 零依赖交互看板（可直接静态部署）
│   ├── index.html  styles.css  app.js
│   ├── engine.js                #   Python 内核的逐行 JS 移植（数值一致性有测试）
│   ├── data.js                  #   由 CLI 生成的合成行情
│   └── presets.js               #   由 config/strategies/*.json 自动生成的预设
├── config/strategies/           # momentum.json / mean_reversion.json / aggressive_breakout.yaml
├── data/sample_prices.csv       # 同一份样例数据的长表 CSV（演示 CSV 适配器）
├── examples/                    # quickstart / 自定义因子 / 模拟盘 / 真实数据
├── scripts/
│   ├── verify_parity.py         #   生成 Python 回测基准
│   └── verify_parity.js         #   Node 对比浏览器引擎，CI 里会跑
├── tests/                       # unittest，零外部依赖（Node 可选）
├── docs/                        # 架构 / 因子 / 风控 / 配置 / API / 实盘安全 / 免责声明
└── .github/workflows/ci.yml     # 单元测试 + JS 数值一致性 + ruff
```

---

## 设计取舍

**为什么核心不依赖 pandas / numpy？** 三个理由：① `pip install -e .` 秒装、在任何环境都能跑；② 逐 bar 的事件循环比向量化更容易讲清楚「哪根 K 线用了什么信息」，这对审计和避免未来函数更重要；③ 让浏览器版引擎能逐行对照移植，并做数值一致性校验。代价是大规模参数网格会慢，需要时把 `factors.py` 换成向量化实现即可，接口不变。

**为什么信号和成交隔一根 K 线？** 用 t 日收盘价算出的信号，如果按 t 日收盘价成交，就是最典型的前视偏差，回测夏普会虚高。本项目把「决策」和「执行」在代码里物理分开（见 `backtest.py` 顶部注释）。

**为什么风控返回全部规则判定？** 生产里最难受的不是「单子被拒」，而是「不知道为什么被拒」。`RiskDecision.checks` 把 12 条规则的通过/失败和具体数值全部返回，看板能直接展示。

**为什么实盘要三重闸门？** 配置文件写错、环境变量残留、测试脚本误连生产，是自动交易最常见的三类事故。单一开关挡不住。详见 [docs/live-trading.md](docs/live-trading.md)。

---

## 用真实数据

```python
from quantforge.config import load_config
from quantforge.data import load_csv, load_yfinance
from quantforge.backtest import BacktestEngine

cfg = load_config("config/strategies/momentum.json")

data = load_csv("data/sample_prices.csv")          # 长表：date,symbol,open,high,low,close,volume
# data = load_yfinance(["AAPL", "MSFT"], "2023-01-01", "2025-01-01")  # 需要 pip install -e '.[market]'
cfg.symbols = list(data)

result = BacktestEngine(cfg).run(data)
print(result.summary())
open("report.md", "w", encoding="utf-8").write(result.markdown())
```

自定义因子只要一个装饰器：

```python
from quantforge.factors import register

@register("my_factor", "我的因子", "自定义", "示例：5 日收益率方向",
          {"period": 5}, 5)
def f_my_factor(bars, i, p):
    n = p["period"]
    if i < n or bars[i - n].close == 0:
        return None
    return max(-1.0, min(1.0, (bars[i].close / bars[i - n].close - 1) * 10))
```

完整示例见 [examples/](examples/)。

---

## A 股路径（`quantforge/ashare/`）

> **当前状态：`PIPELINE_OK_BUT_NOT_READY_FOR_LIVE`。** 链路完整、87 个测试通过，但**不具备接真实资金的条件**。
> 本轮按「只监控 + 信号 + 人工下单」实现：**系统不生成、不发送任何交易指令**，产出的是人工执行建议单。
> 缺的是真实行情授权、3 年以上样本外验证与模拟盘连续运行，不是代码。逐条见 [实盘就绪度审计](docs/ashare-readiness-audit.md)。

新增了一条**独立于通用演示内核**的 A 股生产路径，不改动上一版已通过数值一致性校验的代码：

| 模块 | 作用 |
| --- | --- |
| `ashare/rules.py` | 板块识别、涨跌停（含 **2026-07-06 主板 ST 由 5% 调为 10%**）、申报数量（**科创板 ≥200 股、1 股递增**）、T+1、真实费用（佣金最低 5 元 / 卖出印花税 0.05% / 双向过户费 0.001%）、交易时段、**权威交易日历门禁**；每个常量挂一手来源与生效日 |
| `ashare/feeds.py` | `QMT/xtquant` 同源行情适配器（缺依赖明确报错，**绝不退化到模拟数据**）、本地缓存、数据质量门禁（新鲜度 / OHLC / 涨跌停 / 复权 / 双源一致性） |
| `ashare/engine.py` | 严格回测：涨停买不进、跌停卖不出、停牌、T+1、整手、真实费用；每笔拦截按规则计数；结果内嵌可审计的 `assumptions` |
| `ashare/validation.py` | IC/IR、分层回测、样本外切分、walk-forward、过拟合诊断、3 年跨度门槛 |
| `ashare/monitor.py` | 盘中监控：时段感知、质量门禁失败闭合、因子信号、**人工执行建议单**（11 项合规检查）、SQLite + JSONL 审计；源码级禁止下单调用 |

```bash
python -m unittest discover -s tests -v            # 87 项
python scripts/ashare_pipeline.py                  # 端到端验收（输入为明确标注的合成 fixture）
# 打开 web/ashare.html 看人工执行建议单

# 在装有券商 QMT 客户端并登录的 Windows 机器上：
python examples/ashare_verify_feed.py              # 行情字段自检，必做
python examples/ashare_monitor.py --once           # 单周期监控
python examples/ashare_monitor.py --cycles 100     # 连续监控
```

端到端验收在**随机游走合成数据**上如实给出 `IC=-0.0479`、样本外夏普为负、四道就绪 gate 全 False、`NOT_READY` —— 系统不会把噪声包装成有效策略。这个「难看」的结果正是严谨性的证据。

**合规要点**：A 股散户没有官方开放的交易 API；自动下单需券商 QMT/PTrade 权限，且依《程序化交易管理实施细则》（**2025-07-07 施行**）个人投资者须在首次程序化交易前向券商报告并取得确认。本轮的监控路径不自动下达指令，不触发该义务；若将来改为自动下单，须先完成报告与协议签署。详见 [运行手册](docs/ashare-runbook.md) 与 [就绪度审计](docs/ashare-readiness-audit.md)。

---

## 测试

```bash
python -m unittest discover -s tests -v        # 不需要装任何测试框架
python scripts/verify_parity.py                # 生成 Python 基准回测
node scripts/verify_parity.js                  # 校验浏览器引擎与 Python 数值一致
```

CI 会在 Python 3.10 / 3.12 / 3.13 上跑单元测试，并用 Node 校验前后端数值一致性（当前基准：**23 项指标、504 个净值点、476 笔成交完全一致**）。

---

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | 数据流、模块边界、时序图 |
| [docs/factors.md](docs/factors.md) | 10 个因子的公式、方向、预热长度、自定义方法 |
| [docs/backtest-methodology.md](docs/backtest-methodology.md) | 成交假设、成本、仓位映射、已知局限 |
| [docs/risk-controls.md](docs/risk-controls.md) | 12 条规则逐条说明与配置建议 |
| [docs/strategy-config.md](docs/strategy-config.md) | 配置字段全表、三份预设、JSON/YAML |
| [docs/api.md](docs/api.md) | REST 端点与请求示例 |
| [docs/live-trading.md](docs/live-trading.md) | 实盘三重闸门、Alpaca 接入、上线前清单 |
| [docs/disclaimer.md](docs/disclaimer.md) | 风险与免责声明 |
| [docs/ashare-readiness-audit.md](docs/ashare-readiness-audit.md) | **A 股实盘就绪度审计**：10 条硬伤处置、已知局限、规则一手来源、放行清单 |
| [docs/ashare-runbook.md](docs/ashare-runbook.md) | **A 股运行手册**：QMT 数据接入、合规清单、盘中监控、故障处理 |

---

## License

MIT © 2026 Xuman Hou (Frank). 见 [LICENSE](LICENSE)。
