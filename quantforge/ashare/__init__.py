"""A-share production path: market rules, data feeds, strict backtest,
validation and a monitor-only (no execution) decision-support loop.

This subpackage is deliberately SEPARATE from the generic research core:
  * generic core  -> dependency-free, synthetic demo, parity-checked with web/
  * ashare path   -> A-share microstructure, provenance-gated data, OOS checks

Nothing in here talks to a broker. See monitor.py for the no-execution contract.
"""

from __future__ import annotations

__all__ = [
    "ABar", "Snapshot", "Provenance", "MarketDataFeed", "CachedFeed", "XtdataFeed", "FeedUnavailable",
    "DataQualityGate", "DataQualityError", "QualityReport", "write_cache",
    "TradingCalendar", "Instrument", "FeeSchedule", "FeeBreakdown", "calculate_fees",
    "board_of", "price_limit_pct", "price_limits", "normalise_qty", "market_phase",
    "is_continuous_session", "RULE_SOURCES",
    "AShareBacktestConfig", "AShareBacktestEngine", "AShareBacktestResult",
    "compute_ic_ir", "layered_backtest", "build_factor_panel", "walk_forward",
    "rolling_windows", "split_oos", "ICReport", "LayerReport", "WalkForwardReport",
    "overfit_diagnosis", "Monitor", "MonitorConfig", "MonitorCycle", "ManualOrderTicket",
    "AccountSnapshot", "ConsoleAlert", "WebhookAlert", "assert_no_execution_path",
    "AShareSettings", "SYNTHETIC_LICENSE", "build_synthetic_fixture",
]

from .rules import (  # noqa: E402
    RULE_SOURCES, FeeBreakdown, FeeSchedule, Instrument, TradingCalendar, board_of,
    calculate_fees, is_continuous_session, market_phase, normalise_qty,
    price_limit_pct, price_limits,
)
from .feeds import (  # noqa: E402
    ABar, CachedFeed, DataQualityError, DataQualityGate, FeedUnavailable, MarketDataFeed,
    Provenance, QualityReport, Snapshot, XtdataFeed, write_cache,
)
from .engine import AShareBacktestConfig, AShareBacktestEngine, AShareBacktestResult  # noqa: E402
from .validation import (  # noqa: E402
    ICReport, LayerReport, WalkForwardReport, build_factor_panel, compute_ic_ir,
    layered_backtest, overfit_diagnosis, rolling_windows, split_oos, walk_forward,
)
from .monitor import (  # noqa: E402
    AccountSnapshot, ConsoleAlert, ManualOrderTicket, Monitor, MonitorConfig, MonitorCycle,
    WebhookAlert, assert_no_execution_path,
)
from .config import AShareSettings  # noqa: E402
from .synthetic import SYNTHETIC_LICENSE, build_synthetic_fixture  # noqa: E402
