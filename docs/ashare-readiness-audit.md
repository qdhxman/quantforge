# A 股实盘就绪度审计（2026-11-06）

> 结论先行：**`PIPELINE_OK_BUT_NOT_READY_FOR_LIVE`**。代码链路已全部跑通、87 个测试通过，但当前**不具备**接真实资金的条件，缺的是外部条件与验证证据，不是代码量。见文末「放行清单」。

审计对象：上一版 QuantForge 通用研究内核用于 A 股真实投资时的适用性；以及本版新增 `quantforge/ashare/` 生产路径的完成度。

---

## 一、上一版 10 条硬伤的处置

| # | 硬伤 | 状态 | 落地位置 | 验收测试 |
| --- | --- | --- | --- | --- |
| R-01 | 按开盘价全额成交，涨停买不进 / 跌停卖不出 | ✅ 已修 | `engine.py` `_limits()` + 执行循环；`LIMIT_UP_NO_FILL` / `LIMIT_DOWN_NO_FILL` 计数 | `test_limit_up_blocks_buy_and_fees_are_real` |
| R-02 | 无 T+1 | ✅ 已修 | `engine.py` `available[]` 每日开盘释放；`T1_LOCKED` | `test_no_same_day_sell_after_buy` |
| R-03 | 无 100 股整手；科创板规则不同 | ✅ 已修 | `rules.normalise_qty()` 按板块区分；科创板 ≥200 股、1 股递增 | `test_lot_rules_differ_by_board`；管线中 `BELOW_STAR_MIN_200: 46` 次 |
| R-04 | 费用只有线性 bps | ✅ 已修 | `rules.calculate_fees()`：佣金(最低 5 元) + 卖出印花税 0.05% + 双向过户费 0.001% | `test_fee_schedule` |
| R-05 | 无复权处理 | ✅ 已修 | 全链路前复权连续价；`synthetic.py` 内置一次除权跳变验证不产生假亏 | `test_result_is_auditable`；管线 `bad_adj: 0` |
| R-06 | 连续 weekday 当交易日历 | ✅ 已修（强门禁） | `TradingCalendar.authoritative`；**非权威日历直接拒绝回测**，除非显式 `allow_unverified_calendar=True` | `test_refuses_unverified_calendar`；管线 `[3] PASS` |
| R-07 | 单一种子、无样本外 | ✅ 已修 | `validation.py`：IC/IR、分层回测、样本外切分、walk-forward、过拟合诊断、3 年跨度门槛 | `ValidationTests` 5 项；管线 `[5][6][7]` |
| R-08 | 固定 4 个合成 ticker，无 ST/停牌/新股过滤 | ✅ 已修 | 6 位代码 + 板块识别、ST/新股/停牌排除并计数 | 管线 `ST_EXCLUDED: 504`、`SUSPENDED: 4`、`NEW_LISTING_EXCLUDED: 20` |
| R-09 | 盘中无行情新鲜度、无订单跟踪 | ✅ 已修（监控路径） | `feeds.DataQualityGate` 失败闭合；`monitor.py` 交易时段感知、审计日志、SQLite 状态 | `FeedTests` / `MonitorTests` 共 8 项 |
| R-10 | 没有「可执行」的产出边界 | ✅ 已修 | 本轮按你的选择只做**监控 + 人工执行建议单**，源码级禁止下单调用 | `assert_no_execution_path()` + `test_no_execution_calls_in_source` |

**新增门禁**：数据源来源/时点（`Provenance`）、缓存与监控同源（`CachedFeed`）、规则常量逐个挂一手来源与生效日（`RULES_SOURCES`）、结果内嵌 `assumptions` 可审计报告。

---

## 二、本版**仍存在**的已知局限（必须显式告知，不粉饰）

| 编号 | 局限 | 影响 | 缓解 / 出路 |
| --- | --- | --- | --- |
| L-01 | **价格口径近似**：引擎全程用前复权连续价，公司行动吸收进价格 | 绝对成交额、5 元最低佣金触发点、整手数量与真实券商对账单有偏差 | 定位为**策略有效性验证**，不是实盘对账；对账需券商成交回报，属后续工作 |
| L-02 | 涨跌停按「开盘封板即不成交」保守处理 | 未建模盘中开板、排队、部分成交 | 中低频日频策略影响有限；做打板/日内策略必须重写撮合 |
| L-03 | 无现金分红再投资的精确建模 | 高股息标的收益略有偏差 | 需 `corporate_actions` 事件表 |
| L-04 | 因子仍为纯价量，未做行业/市值中性化、未做因子正交化 | 因子有效性结论可能受风格暴露污染 | `validation.py` 的 IC/IR 会暴露问题；中性化列为下一阶段 |
| L-05 | 无涨跌停/停牌期间的持仓估值细节、无融资融券与 T+0 ETF 特例 | 组合估值近似 | 明确排除在标的范围外，配置中可关 |
| L-06 | **当前没有任何真实行情接入** | 全部数字来自明确标注的合成 fixture | 需你在装有券商 QMT 的 Windows 机器上运行，见 [runbook](ashare-runbook.md) |
| L-07 | 未做券商成交回报对账、未做实盘小额验证 | 无法声称「可实盘」 | 放行清单第 6~9 项 |

这些不是遗漏，是**有意写进报告 `assumptions.known_limitation` 的边界**。一个不说明边界的回测框架，比一个说明边界的更危险。

---

## 三、规则数值与一手来源（2026-11-06 核实）

| 规则 | 取值 | 一手来源 | 交叉印证（非一手，需核实原文） | 生效 |
| --- | --- | --- | --- | --- |
| 程序化交易报备 | 个人投资者首次程序化交易前须向券商报告，券商核查并报交易所后方可交易 | 证监会《证券市场程序化交易管理规定(试行)》(2024-05-15)；[深交所《程序化交易管理实施细则》第 7~9 条](https://www.szse.cn/lawrules/rule/trade/t20250403_612770.html) | 证券时报报道 | **2025-07-07** |
| 程序化委托协议 | 券商与客户签署 | [中证协《程序化交易委托协议(示范文本)》](https://www.sac.net.cn/sjb/zlgl/zlgz/202512/t20251231_69956.html) | — | 2025-12-31 |
| 主板涨跌幅 | ±10% | 沪深交易所《交易规则》 | 新华网投教 | 2023-02-17 |
| 创业板/科创板 | ±20% | [上交所科创板交易机制](https://www.sse.com.cn/star/en/gettingstarted/features/trading/) | 中国基金报 | 2020-08-24 |
| **主板 ST/*ST** | **5% → 10%** | 沪深北《交易规则(2026 年修订)》2026-04-24 发布 | [央视网 2026-07-06](https://news.cctv.cn/2026/07/06/ARTIJUkfhAGrSpiQqDrUizkG260706.shtml)、[央广网](https://finance.cnr.cn/gstj/20260706/t20260706_527692978.shtml) | **2026-07-06** |
| 创业板/科创板 ST | 仍 20% | 同上 | 同上 | 2026-07-06 |
| 新股 | 上市前 5 个交易日不设涨跌幅 | 交易所《交易规则》 | 中国基金报《全面注册制》第五期 | 2023-02-17 |
| 印花税 | 卖出单边 0.05% | 财政部 税务总局公告 2023 年第 39 号；[上交所「股票投资一件事」](https://one.sse.com.cn/onething/gptz) | 百度百科 | 2023-08-28 |
| 过户费 | 双向 0.001% | 中国结算；[上交所](https://one.sse.com.cn/onething/gptz) | 券商收费公示（财信证券，2026-03-05 更新） | 2022-04-29 |
| 佣金 | 上限 0.3%，**单笔最低 5 元** | [上交所](https://one.sse.com.cn/onething/gptz) | 券商收费公示 | 2002-05-01 |
| 规费 | 经手费 0.00341% + 证管费 0.002% = 0.00541%，通常含在佣金内 | [上交所收费一览表](https://www.sse.com.cn/services/tradingservice/charge/ssecharge/) | — | 2023-08-28 |
| 申报数量 | 主板/创业板 100 股整数倍；**科创板 ≥200 股、超出 1 股递增** | [上交所科创板 Order Submission](https://www.sse.com.cn/star/en/gettingstarted/features/trading/) | 中国投资者网投教 PDF | 2019-07-22 |
| 交易时段 | 09:15-09:25 开盘集合竞价；09:30-11:30 / 13:00-14:57 连续竞价；14:57-15:00 收盘集合竞价；15:05-15:30 盘后固定价格（2026-07-06 起扩至全部 A 股与沪深 ETF） | 沪深北《交易规则(2026 年修订)》 | 央视网、中国投资者网投教 PDF | 2026-07-06 |

> **规则会变。** 代码常量集中在 `quantforge/ashare/rules.py::RULE_SOURCES`，每次实盘部署前必须重新核对交易所原文；本表的日期即上次核对日期。

---

## 四、端到端验收结果（合成数据，2026-11-06 实跑）

```
[1] 无下单调用检查: PASS
[2] 缓存写入: 3024 bars, license=synthetic-test-fixture
[3] 交易日历权威门禁: PASS (拒绝非权威日历)
[4] 严格回测: 收益 -4.54% | 夏普 -0.6166 | 回撤 -7.10% | 成交 344 笔 | 规则拦截 1466 次
    规则拦截分布: ST_EXCLUDED 504 / MIN_ORDER_VALUE 892 / BELOW_STAR_MIN_200 46
                  / SUSPENDED 4 / NEW_LISTING_EXCLUDED 20
[5] 因子检验: 2718 截面行, IC=-0.0479, IR=-0.107, 正率 46.14%, 判定 FAIL
[6] Walk-forward: 7 窗口, 判定 FAIL (样本外平均夏普 <= 0, 4/7 窗口亏损)
[7] 就绪度: NOT_READY | 四道 gate 全 False
[8] 监控守护: 质量门禁 PASS, 人工执行建议单 2 张
[9] 报告: reports/ashare_readiness.json
```

**这个「难看」的结果恰恰是严谨的证据**：输入是随机游走的合成行情，系统如实给出 IC 为负、分层不单调、样本外不赚钱、就绪度 `NOT_READY`，没有把噪声包装成一条漂亮的净值曲线。真实数据上如果同样 FAIL，就不该上实盘。

全量测试：`python -m unittest discover -s tests -v` → **87 passed**。

---

## 五、放行清单（全部打勾之前，禁止接真实资金）

1. [ ] 在券商 QMT 客户端登录的 Windows 机器上跑通 `examples/ashare_verify_feed.py`（行情字段自检 + 交易日历权威性）
2. [ ] 把真实行情落盘到 `data/ashare_cache/`，`manifest.calendar_authoritative = true`，`license` 标注实际授权
3. [ ] 用**至少 3 年、含完整牛熊**的真实数据重跑 `scripts/ashare_pipeline.py`，四项 gate 全 PASS
4. [ ] 数据质量门禁连续运行 20 个交易日无 `CRITICAL` 告警
5. [ ] 默认标的池替换为你自己的池，并处理成分股历史变更（避开幸存者偏差）
6. [ ] 用真实券商佣金率覆盖 `commission_rate`；确认规费是否含在佣金内
7. [ ] 模拟盘连续运行 ≥ 1 个月，人工按建议单在券商客户端执行并逐笔记录，核对实际成交与建议的偏差
8. [ ] 确认板块权限（创业板/科创板）、风险测评等级、资金规模符合你的账户实际
9. [ ] 明确「熔断后是否减仓」的策略并单独实现 + 测试
10. [ ] **若将来改为自动下单**：向券商完成程序化交易报告、签署《程序化交易委托协议》、取得确认回执，再启用 `QMT/PTrade` 交易权限；本轮交付的监控路径不涉及此项
11. [ ] 极小金额验证，逐笔对账，再考虑任何规模调整

> 任何投资建议、操作价位、买卖判断的输出都仅供参考，不构成投资建议。市场有风险，投资需谨慎。
