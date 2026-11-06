# REST API

API 是可选扩展，计算内核不依赖它。

```bash
pip install -e '.[api]'
quantforge serve --host 127.0.0.1 --port 8000
# Swagger 文档: http://127.0.0.1:8000/docs
```

默认加载内置合成数据；`--csv` 可换成本地长表 CSV。服务只绑定本地回环地址，不要把未经认证的实例直接暴露到公网。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 版本、可用标的、券商名 |
| GET | `/api/factors` | 10 个因子的元数据 + 组合方式列表 |
| GET | `/api/risk-rules` | 12 条风控规则 + 当前风控配置 |
| GET | `/api/data/symbols` | 每个标的的 bars 数与日期范围 |
| GET | `/api/config` | 当前策略配置 |
| PUT | `/api/config` | 替换内存中的策略配置（422 返回校验错误） |
| POST | `/api/backtest` | 跑回测，返回净值/成交/信号/拦截/指标/因子贡献 |
| GET | `/api/signals/latest` | 最新一根 K 线上每个标的的信号与文字依据 |
| GET | `/api/trading/status` | 自动执行状态、账户快照、是否停机 |
| POST | `/api/trading/step` | 跑 N 个周期（`{"cycles": 5}`），返回每周期详情 |
| POST | `/api/trading/halt` | 紧急停机 |
| POST | `/api/trading/resume` | 解除停机 |
| GET | `/api/journal?limit=100&event_type=RISK_BLOCK` | 审计日志 |
| GET | `/api/risk/events` | 最近一次回测的拦截记录 |
| GET | `/` | 若存在 `web/index.html` 则直接返回看板 |

## 示例

```bash
curl http://127.0.0.1:8000/api/factors

curl -X POST http://127.0.0.1:8000/api/backtest \
  -H 'Content-Type: application/json' \
  -d '{"config": {
        "name": "api-demo",
        "symbols": ["AAPL", "MSFT", "NVDA", "SPY"],
        "factors": [{"name": "momentum", "weight": 1.0},
                    {"name": "rsi", "weight": 0.6}],
        "signal": {"buy_threshold": 0.2, "sell_threshold": -0.2}
      }}'

curl -X POST http://127.0.0.1:8000/api/trading/step \
  -H 'Content-Type: application/json' -d '{"cycles": 5}'

curl -X POST http://127.0.0.1:8000/api/trading/halt \
  -H 'Content-Type: application/json' -d '{"reason": "manual review"}'
```

`POST /api/backtest` 的 body 可以省略 `config`，此时使用服务启动时加载的策略。所有字段都有默认值，可以只写想改的部分。

## 看板与 API 的关系

`web/index.html` 是**完全自包含**的：`web/engine.js` 在浏览器里完成同样计算，不需要 API。API 更适合把这些能力接进你自己的 notebook、后台服务或调度系统。两者共用 `config/strategies/*.json` 生成的预设，不会出现「看板一套数、API 另一套数」。
