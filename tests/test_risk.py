import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.config import RiskConfig  # noqa: E402
from quantforge.orders import OrderRequest, Side  # noqa: E402
from quantforge.portfolio import Portfolio  # noqa: E402
from quantforge.risk import RiskContext, RiskManager, list_rules  # noqa: E402


def buy(qty=10, symbol="AAPL"):
    return OrderRequest(symbol=symbol, side=Side.BUY, qty=qty)


def sell(qty=10, symbol="AAPL"):
    return OrderRequest(symbol=symbol, side=Side.SELL, qty=qty)


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.cfg = RiskConfig()
        self.rm = RiskManager(self.cfg, env={})
        self.pf = Portfolio(100_000.0)
        self.pf.set_price("AAPL", 100.0)
        self.ctx = RiskContext(equity=100_000.0, day_start_equity=100_000.0,
                               peak_equity=100_000.0, bars_since_last_trade=10 ** 6)

    def decide(self, req, price=100.0, ctx=None):
        return self.rm.evaluate(req, self.pf, price, ctx or self.ctx)

    def test_rules_documented(self):
        self.assertEqual(len(list_rules()), 12)
        self.assertEqual({r["rule"] for r in list_rules()},
                         {c.rule for c in self.decide(buy()).checks})

    def test_clean_order_passes_all(self):
        d = self.decide(buy(10))
        self.assertTrue(d.allowed)
        self.assertIsNone(d.blocked_by)
        self.assertTrue(all(c.passed for c in d.checks))

    def test_kill_switch(self):
        self.cfg.kill_switch = True
        d = self.decide(buy(10))
        self.assertFalse(d.allowed)
        self.assertEqual(d.blocked_by, "KILL_SWITCH")

    def test_env_kill_switch(self):
        rm = RiskManager(RiskConfig(), env={"QFI_KILL_SWITCH": "1"})
        self.assertFalse(rm.evaluate(buy(10), self.pf, 100.0, self.ctx).allowed)

    def test_blacklist(self):
        self.cfg.blacklist = ["AAPL"]
        self.assertEqual(self.decide(buy(10)).blocked_by, "SYMBOL_BLACKLIST")

    def test_min_qty(self):
        self.assertEqual(self.decide(buy(0)).blocked_by, "MIN_QTY")

    def test_max_order_notional(self):
        self.cfg.max_order_notional = 500.0
        self.assertEqual(self.decide(buy(10)).blocked_by, "MAX_ORDER_NOTIONAL")

    def test_max_position_weight(self):
        self.cfg.max_position_pct = 0.05
        self.assertEqual(self.decide(buy(100)).blocked_by, "MAX_POSITION_WEIGHT")

    def test_max_gross_exposure(self):
        self.cfg.max_gross_exposure_pct = 0.005
        self.assertEqual(self.decide(buy(10)).blocked_by, "MAX_GROSS_EXPOSURE")

    def test_max_daily_loss(self):
        ctx = RiskContext(equity=95_000.0, day_start_equity=100_000.0,
                          peak_equity=100_000.0, bars_since_last_trade=10 ** 6)
        self.assertEqual(self.decide(buy(10), ctx=ctx).blocked_by, "MAX_DAILY_LOSS")

    def test_max_drawdown(self):
        ctx = RiskContext(equity=70_000.0, day_start_equity=70_000.0,
                          peak_equity=100_000.0, bars_since_last_trade=10 ** 6)
        self.assertEqual(self.decide(buy(10), ctx=ctx).blocked_by, "MAX_DRAWDOWN")

    def test_cooldown(self):
        self.cfg.cooldown_bars = 5
        ctx = RiskContext(equity=100_000.0, day_start_equity=100_000.0,
                          peak_equity=100_000.0, bars_since_last_trade=1)
        self.assertEqual(self.decide(buy(10), ctx=ctx).blocked_by, "COOLDOWN")

    def test_buying_power(self):
        self.pf.cash = 500.0
        self.assertEqual(self.decide(buy(10)).blocked_by, "BUYING_POWER")

    def test_shorting_disabled(self):
        self.assertEqual(self.decide(sell(10)).blocked_by, "SHORTING_DISABLED")
        self.cfg.allow_short = True
        self.assertTrue(self.decide(sell(10)).allowed)

    def test_pending_order_limit(self):
        ctx = RiskContext(equity=100_000.0, day_start_equity=100_000.0,
                          peak_equity=100_000.0, bars_since_last_trade=10 ** 6,
                          pending_count=10, max_pending=10)
        self.assertEqual(self.decide(buy(10), ctx=ctx).blocked_by, "PENDING_ORDER_LIMIT")

    def test_all_checks_returned_even_on_failure(self):
        self.cfg.kill_switch = True
        d = self.decide(buy(10))
        self.assertEqual(len(d.checks), 12)
        self.assertEqual(sum(1 for c in d.checks if not c.passed), 1)


if __name__ == "__main__":
    unittest.main()
