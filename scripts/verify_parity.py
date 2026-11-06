"""Dump a Python reference backtest for scripts/verify_parity.js to compare against.

Usage:
    python scripts/verify_parity.py --out /tmp/qf_python.json
    node  scripts/verify_parity.js /tmp/qf_python.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.backtest import BacktestEngine  # noqa: E402
from quantforge.config import load_config  # noqa: E402
from quantforge.data import generate_synthetic  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "reports" / "python_reference.json"))
    ap.add_argument("--config", default=str(ROOT / "config" / "strategies" / "momentum.json"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    result = BacktestEngine(cfg).run(generate_synthetic())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.as_dict(), ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
