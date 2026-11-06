"""Optional real-data adapter. NEVER point this at a live broker by accident.

    pip install -e '.[market]'
    python examples/fetch_real_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantforge.backtest import BacktestEngine  # noqa: E402
from quantforge.config import load_config  # noqa: E402


def main() -> None:
    from quantforge.data import load_csv, load_yfinance

    # Prefer a CSV you control (see data/sample_prices.csv for the schema).
    csv_path = ROOT / "data" / "sample_prices.csv"
    if csv_path.exists():
        print(f"使用本地 CSV：{csv_path}")
        data = load_csv(csv_path)
    else:
        print("从 Yahoo Finance 拉取…（需要联网，数据可能有延迟/复权差异）")
        data = load_yfinance(["AAPL", "MSFT", "NVDA", "SPY"], "2023-01-01", "2025-01-01")

    cfg = load_config(ROOT / "config" / "strategies" / "momentum.json")
    cfg.symbols = list(data)
    result = BacktestEngine(cfg).run(data)
    print(result.summary())
    print("\n提醒：任何真实数据上的回测结论都仍需样本外检验，且不构成投资建议。")


if __name__ == "__main__":
    main()
