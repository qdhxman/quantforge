import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.config import (  # noqa: E402
    FactorSpec, SignalConfig, StrategyConfig, default_config, load_config, validate_factors,
)
from quantforge.factors import FACTOR_REGISTRY  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class ConfigTests(unittest.TestCase):
    def test_load_json_preset(self):
        cfg = load_config(ROOT / "config" / "strategies" / "momentum.json")
        self.assertEqual(cfg.name, "momentum-blend")
        self.assertEqual(len(cfg.factors), 5)
        self.assertEqual(cfg.signal.combine_method, "weighted")
        validate_factors(cfg, FACTOR_REGISTRY)

    def test_default_config(self):
        cfg = default_config()
        self.assertEqual(cfg.trading.mode, "paper")
        self.assertFalse(cfg.risk.allow_short)
        self.assertEqual(cfg.clone().to_dict(), cfg.to_dict())

    def test_partial_dict_uses_defaults(self):
        cfg = StrategyConfig.from_dict({"name": "x", "factors": [{"name": "rsi"}]})
        self.assertEqual(cfg.backtest.initial_cash, 100_000.0)
        self.assertEqual(cfg.factors[0].weight, 1.0)

    def test_unknown_factor_rejected(self):
        cfg = StrategyConfig.from_dict({"factors": [{"name": "not_real"}]})
        with self.assertRaises(ValueError) as ctx:
            validate_factors(cfg, FACTOR_REGISTRY)
        self.assertIn("not_real", str(ctx.exception))

    def test_invalid_values_rejected(self):
        with self.assertRaises(ValueError):
            SignalConfig(buy_threshold=-0.1, sell_threshold=0.1)
        with self.assertRaises(ValueError):
            SignalConfig(smoothing=1.0)
        with self.assertRaises(ValueError):
            SignalConfig(combine_method="magic")
        with self.assertRaises(ValueError):
            FactorSpec("rsi", -1)
        with self.assertRaises(ValueError):
            StrategyConfig.from_dict({"trading": {"mode": "YOLO"}})

    def test_env_kill_switch_forces_safety(self):
        path = ROOT / "config" / "strategies" / "momentum.json"
        with patch.dict(os.environ, {"QFI_KILL_SWITCH": "1"}):
            self.assertTrue(load_config(path).risk.kill_switch)
        self.assertFalse(load_config(path).risk.kill_switch)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_config(ROOT / "nope.json")

    def test_yaml_optional(self):
        path = ROOT / "config" / "strategies" / "aggressive_breakout.yaml"
        try:
            cfg = load_config(path)
        except RuntimeError as exc:
            self.skipTest(str(exc))
        self.assertEqual(cfg.name, "aggressive-breakout")
        self.assertEqual(cfg.signal.combine_method, "max")


if __name__ == "__main__":
    unittest.main()
