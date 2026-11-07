"""Config loader for the A-share path. One JSON file drives backtest and monitor."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import FactorSpec, SignalConfig
from .engine import AShareBacktestConfig
from .monitor import MonitorConfig

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "ashare" / "strategy.json"


@dataclass
class AShareSettings:
    symbols: list[str] = field(default_factory=list)
    factors: list[FactorSpec] = field(default_factory=list)
    signal: SignalConfig = field(default_factory=SignalConfig)
    backtest: dict[str, Any] = field(default_factory=dict)
    monitor: dict[str, Any] = field(default_factory=dict)
    feed: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AShareSettings":
        return cls(
            symbols=list(d.get("symbols", [])),
            factors=[FactorSpec(**f) for f in d.get("factors", [])],
            signal=SignalConfig(**d.get("signal", {})),
            backtest=dict(d.get("backtest", {})),
            monitor=dict(d.get("monitor", {})),
            feed=dict(d.get("feed", {})),
            quality=dict(d.get("quality", {})),
            raw=dict(d),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AShareSettings":
        p = Path(path or DEFAULT_PATH)
        if not p.exists():
            raise FileNotFoundError(f"A-share config not found: {p}")
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def backtest_config(self, **overrides: Any) -> AShareBacktestConfig:
        allowed = {k for k in AShareBacktestConfig.__dataclass_fields__}
        kwargs = {k: v for k, v in self.backtest.items() if k in allowed}
        kwargs.update({k: v for k, v in overrides.items() if k in allowed})
        kwargs.setdefault("factors", self.factors)
        kwargs.setdefault("signal", self.signal)
        return AShareBacktestConfig(**kwargs)

    def monitor_config(self, **overrides: Any) -> MonitorConfig:
        allowed = {k for k in MonitorConfig.__dataclass_fields__}
        kwargs = {k: v for k, v in self.monitor.items() if k in allowed}
        kwargs.update({k: v for k, v in overrides.items() if k in allowed})
        kwargs.setdefault("symbols", self.symbols)
        kwargs.setdefault("factors", self.factors)
        kwargs.setdefault("signal", self.signal)
        kwargs.setdefault("max_stale_seconds", self.quality.get("max_stale_seconds", 60))
        return MonitorConfig(**kwargs)
