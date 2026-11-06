"""Autonomous loop against the paper broker, including an emergency stop.

    python examples/live_paper_session.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.brokers import PaperBroker  # noqa: E402
from quantforge.config import load_config  # noqa: E402
from quantforge.data import generate_synthetic  # noqa: E402
from quantforge.journal import Journal  # noqa: E402
from quantforge.live import LiveTradingEngine  # noqa: E402


def main() -> None:
    cfg = load_config(ROOT / "config" / "strategies" / "momentum.json")
    cfg.trading.mode = "paper"
    data = generate_synthetic()
    broker = PaperBroker(cfg.backtest.initial_cash)
    journal = Journal(ROOT / "reports" / "paper_journal.jsonl")
    engine = LiveTradingEngine(cfg, broker, data, journal=journal)

    for cycle in range(1, 16):
        step = engine.run_cycle()
        print(f"cycle {cycle:2d} {step.date} | signals={len(step.signals)} "
              f"orders={len(step.orders)} blocked={len(step.blocked)} "
              f"equity={step.account.get('equity', 0):,.2f}")

    engine.halt("demo: manual emergency stop")
    after = engine.run_cycle()
    print(f"\n停机后：halted={after.halted}, orders={len(after.orders)}（应为 0）")
    print("状态：", engine.status())
    print("审计事件：", [e["type"] for e in journal.events[:6]], "...")


if __name__ == "__main__":
    main()
