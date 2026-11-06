# 贡献指南

欢迎提 issue / PR。几个能加快合并的约定：

## 开发环境

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,api,yaml]'
python -m unittest discover -s tests -v
python scripts/verify_parity.py && node scripts/verify_parity.js
```

## 三条硬规矩

1. **不许有未来函数。** 任何因子只能读 `bars[0..i]`。新增因子请同时加一个「截断未来数据后结果不变」的测试（参考 `tests/test_factors.py::test_no_lookahead`）。
2. **前后端数值要一致。** 改了 `quantforge/factors.py` / `signals.py` / `backtest.py` / `risk.py` / `metrics.py` 的计算逻辑，必须同步改 `web/engine.js`，并跑 `verify_parity.js`。CI 会卡住不一致的改动。
3. **实盘路径默认关闭。** 任何涉及真实下单的代码，不得降低 `AlpacaBroker._assert_live_gate` 的门槛；新增券商适配器要沿用同样的显式确认 + 环境变量 + 非模拟端点三重闸门。

## 代码风格

- 计算内核保持只用标准库；第三方依赖放进 `pyproject.toml` 的 optional extras。
- 因子函数签名统一为 `(bars, i, params) -> float | None`，返回值必须落在 `[-1, 1]`，数据不足返回 `None`。
- 新增因子后运行 `quantforge sample-data` 重新生成 `web/data.js` / `web/presets.js`（如果改了预设），并把新因子加进 `docs/factors.md`。
- 提交信息用中文或英文都行，写清楚「改了什么、为什么」。

## 不要提交的东西

`.env`、任何 API key/secret、真实账户数据、券商回单、含个人信息的持仓截图。`.gitignore` 已经挡了常见项，但请自己再确认一次 `git diff --cached`。
