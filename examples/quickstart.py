"""Minimal end-to-end example: config -> data -> backtest -> signals -> report.

    python examples/quickstart.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.backtest import BacktestEngine  # noqa: E402
from quantforge.config import load_config  # noqa: E402
from quantforge.data import generate_synthetic  # noqa: E402
from quantforge.signals import SignalEngine  # noqa: E402


def main() -> None:
    cfg = load_config(ROOT / "config" / "strategies" / "momentum.json")
    data = generate_synthetic()

    result = BacktestEngine(cfg).run(data)
    print(result.summary())
    print(result.markdown())

    engine = SignalEngine(cfg)
    print("\n最新信号（决策依据）:")
    for symbol, bars in data.items():
        if symbol in cfg.symbols:
            sig = engine.evaluate(bars, len(bars) - 1, symbol)
            print(f"  {symbol:5s} {sig.action:4s} score={sig.score:+.3f}  {sig.reason}")

    out = ROOT / "reports" / "quickstart_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(result.markdown(), encoding="utf-8")
    print(f"\n报告已写入 {out}")


if __name__ == "__main__":
    main()
