import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.data import (  # noqa: E402
    dataset_to_jsonable, generate_synthetic, load_csv, slice_dataset,
)


class DataTests(unittest.TestCase):
    def test_synthetic_is_deterministic(self):
        a = generate_synthetic(n_bars=60, seed=123)
        b = generate_synthetic(n_bars=60, seed=123)
        c = generate_synthetic(n_bars=60, seed=999)
        self.assertEqual(a, b)
        self.assertNotEqual(a["AAPL"][-1].close, c["AAPL"][-1].close)

    def test_ohlc_consistency(self):
        data = generate_synthetic(n_bars=80, seed=5)
        for symbol, bars in data.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(len(bars), 80)
                for b in bars:
                    self.assertGreater(b.close, 0)
                    self.assertGreaterEqual(b.high, max(b.open, b.close))
                    self.assertLessEqual(b.low, min(b.open, b.close))
                    self.assertGreater(b.volume, 0)

    def test_csv_roundtrip(self):
        data = generate_synthetic(n_bars=30, seed=8)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "prices.csv"
            with p.open("w", encoding="utf-8", newline="") as fh:
                fh.write("date,symbol,open,high,low,close,volume\n")
                for symbol, bars in data.items():
                    for b in bars:
                        fh.write(f"{b.date},{symbol},{b.open},{b.high},{b.low},{b.close},{b.volume}\n")
            loaded = load_csv(p)
            self.assertEqual(set(loaded), set(data))
            self.assertEqual(loaded["AAPL"], data["AAPL"])

    def test_slice_and_jsonable(self):
        data = generate_synthetic(n_bars=30, seed=8)
        sliced = slice_dataset(data, data["AAPL"][5].date, data["AAPL"][10].date)
        self.assertEqual(len(sliced["AAPL"]), 6)
        js = dataset_to_jsonable(data)
        self.assertEqual(js["AAPL"][0]["date"], data["AAPL"][0].date)

    def test_repo_sample_csv_loads(self):
        p = Path(__file__).resolve().parent.parent / "data" / "sample_prices.csv"
        if not p.exists():
            self.skipTest("generated CSV not present")
        loaded = load_csv(p)
        self.assertEqual(len(loaded), 4)
        self.assertEqual(len(loaded["AAPL"]), 504)


if __name__ == "__main__":
    unittest.main()
