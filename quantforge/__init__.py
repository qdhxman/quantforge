"""QuantForge: factor-driven quant research, backtesting and guarded execution.

Design goal: every number on the dashboard must be reproducible from a config
file and a list of OHLCV bars. The computation core depends only on the Python
standard library; FastAPI, PyYAML and yfinance are optional extras.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import StrategyConfig, default_config, load_config  # noqa: E402,F401
from .data import Bar  # noqa: E402,F401
from .backtest import BacktestEngine, BacktestResult  # noqa: E402,F401

__all__ = [
    "__version__",
    "StrategyConfig",
    "default_config",
    "load_config",
    "Bar",
    "BacktestEngine",
    "BacktestResult",
]
