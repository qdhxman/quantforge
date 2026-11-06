import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.config import FactorSpec  # noqa: E402
from quantforge.data import Bar, generate_synthetic  # noqa: E402
from quantforge.factors import FACTOR_REGISTRY, evaluate, list_factors  # noqa: E402


class FactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = generate_synthetic(n_bars=120, seed=7)["AAPL"]

    def test_registry_complete(self):
        self.assertEqual(len(FACTOR_REGISTRY), 10)
        for meta in list_factors():
            self.assertTrue(meta["name"] and meta["label"] and meta["description"])
            self.assertGreater(meta["min_bars"], 0)
            self.assertIsInstance(meta["default_params"], dict)

    def test_scores_bounded_or_none(self):
        for name, meta in FACTOR_REGISTRY.items():
            with self.subTest(factor=name):
                for i in (0, 5, 20, 40, 80, 119):
                    v = meta.fn(self.bars, i, meta.default_params)
                    if v is not None:
                        self.assertFalse(math.isnan(v))
                        self.assertTrue(-1.0 <= v <= 1.0, f"{name}@{i} = {v}")

    def test_warmup_returns_none(self):
        for name, meta in FACTOR_REGISTRY.items():
            with self.subTest(factor=name):
                self.assertIsNone(meta.fn(self.bars, 0, meta.default_params))

    def test_no_lookahead(self):
        """Truncating or corrupting future bars must not change a past score."""
        specs = [FactorSpec(n, 1.0) for n in FACTOR_REGISTRY]
        for i in (40, 70, 100):
            full = evaluate(self.bars, i, specs, "weighted")
            truncated = evaluate(self.bars[: i + 1], i, specs, "weighted")
            self.assertAlmostEqual(full.value, truncated.value, places=12)
            self.assertEqual(full.raw_values, truncated.raw_values)

        for i in (40, 70):
            # Rebuild for each i: only bars AFTER i may differ.
            corrupted = list(self.bars[: i + 1]) + [
                Bar(b.date, 1e9 if j % 2 else 1.0, 1e9, 1e-9, 1e9 if j % 2 else 1.0, 1e12)
                for j, b in enumerate(self.bars[i + 1 :], start=i + 1)
            ]
            before = evaluate(self.bars, i, specs, "weighted")
            after = evaluate(corrupted, i, specs, "weighted")
            self.assertAlmostEqual(before.value, after.value, places=12)
            self.assertEqual(before.raw_values, after.raw_values)

    def test_combine_methods(self):
        specs = [FactorSpec("momentum", 1.0), FactorSpec("rsi", 1.0), FactorSpec("macd", 0.5)]
        raw = {}
        for m in ("weighted", "majority", "min", "max"):
            raw[m] = evaluate(self.bars, 80, specs, m).value
            self.assertTrue(-1 <= raw[m] <= 1)
        values = [evaluate(self.bars, 80, [FactorSpec("momentum")], "weighted").value,
                  evaluate(self.bars, 80, [FactorSpec("rsi")], "weighted").value,
                  evaluate(self.bars, 80, [FactorSpec("macd")], "weighted").value]
        self.assertAlmostEqual(raw["min"], min(values), places=12)
        self.assertAlmostEqual(raw["max"], max(values), places=12)

    def test_unknown_factor_and_empty(self):
        with self.assertRaises(ValueError):
            evaluate(self.bars, 80, [FactorSpec("does_not_exist")])
        with self.assertRaises(ValueError):
            evaluate(self.bars, 80, [])
        with self.assertRaises(ValueError):
            evaluate(self.bars, 80, [FactorSpec("momentum")], "bogus")

    def test_coverage_reports_warmup(self):
        specs = [FactorSpec("reversal_1d", 1.0), FactorSpec("macd", 3.0)]
        early = evaluate(self.bars, 2, specs)
        self.assertAlmostEqual(early.coverage, 0.25)  # only weight-1 factor ready
        late = evaluate(self.bars, 80, specs)
        self.assertEqual(late.coverage, 1.0)


if __name__ == "__main__":
    unittest.main()
