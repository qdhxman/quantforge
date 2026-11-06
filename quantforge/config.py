"""Strategy configuration as plain, serialisable dataclasses.

A strategy is one JSON/YAML file. That makes it diffable in git, sendable over
the API, and reproducible months later: same file + same bars = same result.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

VALID_COMBINE_METHODS = ("weighted", "majority", "min", "max")


@dataclass
class FactorSpec:
    """One selected factor and how much it contributes to the composite score."""

    name: str
    weight: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("factor name must be a non-empty string")
        self.weight = float(self.weight)
        if self.weight < 0:
            raise ValueError(f"factor '{self.name}' weight must be >= 0 (use a negative-facing factor instead)")


@dataclass
class SignalConfig:
    buy_threshold: float = 0.18
    sell_threshold: float = -0.18
    smoothing: float = 0.0          # 0 = none; EMA decay in [0, 1)
    min_holding_bars: int = 2       # hysteresis: minimum bars before flipping direction
    combine_method: str = "weighted"

    def __post_init__(self) -> None:
        if not 0 <= self.smoothing < 1:
            raise ValueError("smoothing must be in [0, 1)")
        if self.combine_method not in VALID_COMBINE_METHODS:
            raise ValueError(f"combine_method must be one of {VALID_COMBINE_METHODS}")
        if self.buy_threshold <= self.sell_threshold:
            raise ValueError("buy_threshold must be greater than sell_threshold")


@dataclass
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission_bps: float = 5.0     # per side, on notional
    slippage_bps: float = 5.0       # adverse price movement, per side
    lot_size: int = 1               # 100 for A-shares
    min_order_value: float = 500.0  # ignore tiny rebalancing noise
    max_position_pct: float = 0.35
    max_gross_exposure_pct: float = 0.95
    allow_short: bool = False


@dataclass
class RiskConfig:
    """Hard limits checked BEFORE an order reaches any broker."""

    max_order_notional: float = 30_000.0
    max_position_pct: float = 0.35
    max_gross_exposure_pct: float = 0.95
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.20
    cooldown_bars: int = 1
    blacklist: list[str] = field(default_factory=list)
    kill_switch: bool = False
    allow_short: bool = False

    def __post_init__(self) -> None:
        for key in ("max_position_pct", "max_gross_exposure_pct", "max_daily_loss_pct", "max_drawdown_pct"):
            if not 0 <= getattr(self, key) <= 1:
                raise ValueError(f"{key} must be in [0, 1]")


@dataclass
class TradingConfig:
    mode: str = "paper"             # "paper" | "live"
    poll_seconds: int = 60
    journal_path: str = "logs/trading-journal.jsonl"
    order_type: str = "market"
    max_orders_per_cycle: int = 10
    live_confirmation_env: str = "QFI_CONFIRM_LIVE_TRADING"

    def __post_init__(self) -> None:
        if self.mode not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")


@dataclass
class StrategyConfig:
    name: str = "default"
    description: str = ""
    symbols: list[str] = field(default_factory=lambda: ["AAPL", "MSFT", "NVDA", "SPY"])
    factors: list[FactorSpec] = field(default_factory=list)
    signal: SignalConfig = field(default_factory=SignalConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def clone(self) -> "StrategyConfig":
        return StrategyConfig.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StrategyConfig":
        d = copy.deepcopy(raw)
        factor_specs = [FactorSpec(**f) for f in d.pop("factors", [])]
        signal = SignalConfig(**d.pop("signal", {}))
        backtest = BacktestConfig(**d.pop("backtest", {}))
        risk = RiskConfig(**d.pop("risk", {}))
        trading = TradingConfig(**d.pop("trading", {}))
        return cls(factors=factor_specs, signal=signal, backtest=backtest, risk=risk, trading=trading, **d)


def default_config() -> StrategyConfig:
    """A sensible momentum + confirmation blend over four synthetic symbols."""
    return StrategyConfig.from_dict(
        {
            "name": "momentum-blend",
            "description": "Trend following with volume and volatility confirmation",
            "symbols": ["AAPL", "MSFT", "NVDA", "SPY"],
            "factors": [
                {"name": "momentum", "weight": 1.0, "params": {"lookback": 20}},
                {"name": "ma_cross", "weight": 0.8, "params": {"fast": 10, "slow": 30}},
                {"name": "macd", "weight": 0.6, "params": {}},
                {"name": "volume_spike", "weight": 0.4, "params": {"period": 20}},
                {"name": "low_volatility", "weight": 0.3, "params": {"period": 20}},
            ],
        }
    )


def _read_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError("Loading YAML configs needs `pip install -e '.[yaml]'`, or use the .json files") from exc
        return yaml.safe_load(text) or {}
    raise ValueError(f"Unsupported config format: {path.suffix} (use .json or .yaml)")


def load_config(path: str | Path | None) -> StrategyConfig:
    """Load a strategy file. ``None``/missing path returns the built-in default."""
    if path is None:
        cfg = default_config()
    else:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Strategy config not found: {p}")
        cfg = StrategyConfig.from_dict(_read_mapping(p))

    # Environment overrides are deliberately few and always fail-safe.
    if os.environ.get("QFI_KILL_SWITCH", "0") == "1":
        cfg.risk.kill_switch = True
    return cfg


def validate_factors(cfg: StrategyConfig, registry: dict) -> None:
    missing = [f.name for f in cfg.factors if f.name not in registry]
    if missing:
        raise ValueError(f"Unknown factor(s): {', '.join(missing)}. Available: {', '.join(sorted(registry))}")
    if not cfg.factors:
        raise ValueError("At least one factor must be selected")
