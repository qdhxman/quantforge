import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.backtest import BacktestEngine  # noqa: E402
from quantforge.config import default_config  # noqa: E402
from quantforge.data import Bar, generate_synthetic  # noqa: E402


class BacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_synthetic(n_bars=260, seed=42)
        cls.cfg = default_config()

    def test_deterministic(self):
        a = BacktestEngine(self.cfg).run(self.data)
        b = BacktestEngine(self.cfg).run(self.data)
        self.assertEqual(a.metrics, b.metrics)
        self.assertEqual(a.trades, b.trades)
        self.assertEqual(a.equity_curve, b.equity_curve)

    def test_metrics_shape(self):
        r = BacktestEngine(self.cfg).run(self.data)
        for key in ("total_return", "cagr", "sharpe", "sortino", "max_drawdown",
                    "win_rate", "num_trades", "buy_hold_return", "excess_return", "risk_blocks"):
            self.assertIn(key, r.metrics)
        self.assertEqual(len(r.equity_curve), 260)
        self.assertEqual(r.metrics["bars"], 260)
        self.assertLessEqual(r.metrics["max_drawdown"], 0)
        self.assertGreater(r.metrics["num_trades"], 0)

    def test_no_lookahead_in_trades(self):
        """Corrupt every bar after index 120; trades before that stay identical."""
        base = BacktestEngine(self.cfg).run(self.data)
        corrupted = {}
        for symbol, bars in self.data.items():
            rows = list(bars)
            for i in range(121, len(rows)):
                b = rows[i]
                rows[i] = Bar(b.date, b.close * 5, b.close * 5, b.close * 5, b.close * 5, b.volume)
            corrupted[symbol] = rows
        changed = BacktestEngine(self.cfg).run(corrupted)
        cutoff = self.data["AAPL"][121].date
        self.assertEqual(
            [t for t in base.trades if t["date"] < cutoff],
            [t for t in changed.trades if t["date"] < cutoff],
        )

    def test_execution_is_next_bar(self):
        r = BacktestEngine(self.cfg).run(self.data)
        first_signal = min(s["date"] for s in r.signals)
        first_trade = min(t["date"] for t in r.trades)
        self.assertGreater(first_trade, first_signal)

    def test_costs_reduce_equity(self):
        free = default_config()
        free.backtest.commission_bps = 0.0
        free.backtest.slippage_bps = 0.0
        expensive = default_config()
        expensive.backtest.commission_bps = 30.0
        expensive.backtest.slippage_bps = 30.0
        a = BacktestEngine(free).run(self.data).metrics["final_equity"]
        b = BacktestEngine(expensive).run(self.data).metrics["final_equity"]
        self.assertGreater(a, b)

    def test_kill_switch_blocks_all_orders(self):
        cfg = default_config()
        cfg.risk.kill_switch = True
        r = BacktestEngine(cfg).run(self.data)
        self.assertEqual(r.metrics["num_trades"], 0)
        self.assertGreater(r.metrics["risk_blocks"], 0)
        self.assertTrue(all(e["blocked_by"] == "KILL_SWITCH" for e in r.risk_events))

    def test_report_and_summary(self):
        r = BacktestEngine(self.cfg).run(self.data)
        self.assertIn("夏普比率", r.markdown())
        self.assertIn("收益", r.summary())
        d = r.as_dict()
        self.assertEqual(set(d), {"config", "metrics", "equity_curve", "trades", "signals",
                                  "latest_signals", "risk_events", "factor_impact"})
        self.assertIsInstance(d["equity_curve"][0]["equity"], float)

    def test_missing_symbols_raise(self):
        cfg = default_config()
        cfg.symbols = ["NOT_IN_DATA"]
        with self.assertRaises(ValueError):
            BacktestEngine(cfg).run(self.data)


if __name__ == "__main__":
    unittest.main()
