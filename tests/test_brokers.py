import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.brokers import LIVE_URL, PAPER_URL, AlpacaBroker, PaperBroker  # noqa: E402
from quantforge.orders import Order, OrderRequest, OrderStatus, OrderType, Side  # noqa: E402


class OrderStateMachineTests(unittest.TestCase):
    def test_illegal_transition(self):
        o = Order(request=OrderRequest("AAPL", Side.BUY, 1))
        o.transition(OrderStatus.SUBMITTED)
        with self.assertRaises(ValueError):
            o.transition(OrderStatus.PENDING)
        o.transition(OrderStatus.FILLED)
        with self.assertRaises(ValueError):
            o.transition(OrderStatus.CANCELLED)

    def test_limit_price_in_notional(self):
        r = OrderRequest("AAPL", Side.BUY, 10, OrderType.LIMIT, 123.0)
        self.assertEqual(r.notional, 1230.0)
        self.assertEqual(r.as_dict()["side"], "BUY")


class PaperBrokerTests(unittest.TestCase):
    def test_fill_updates_cash_and_position(self):
        b = PaperBroker(100_000, commission_bps=10, slippage_bps=10)
        o = b.submit_order(OrderRequest("AAPL", Side.BUY, 10), 100.0)
        self.assertEqual(o.status, OrderStatus.FILLED)
        self.assertAlmostEqual(o.avg_fill_price, 100.1, places=6)
        self.assertAlmostEqual(b.get_positions()["AAPL"], 10)
        self.assertLess(b.get_account()["cash"], 100_000)
        self.assertEqual(len(b.fills), 1)

        sell = b.submit_order(OrderRequest("AAPL", Side.SELL, 10), 110.0)
        self.assertEqual(sell.status, OrderStatus.FILLED)
        self.assertNotIn("AAPL", b.get_positions())
        self.assertGreater(b.get_account()["realized_pnl"], 0)

    def test_invalid_order_rejected(self):
        b = PaperBroker()
        o = b.submit_order(OrderRequest("AAPL", Side.BUY, 0), 100.0)
        self.assertEqual(o.status, OrderStatus.REJECTED)


class AlpacaGateTests(unittest.TestCase):
    GOOD_ENV = {
        "QFI_ALLOW_LIVE": "1",
        "QFI_CONFIRM_LIVE_TRADING": "I_UNDERSTAND",
    }

    def test_paper_by_default_no_gate(self):
        b = AlpacaBroker("k", "s", PAPER_URL, env={})
        self.assertFalse(b.is_live)
        self.assertIn("paper", b.base_url)

    def test_live_requires_all_flags(self):
        cases = [
            ({}, LIVE_URL),
            ({"QFI_ALLOW_LIVE": "1"}, LIVE_URL),
            (self.GOOD_ENV, PAPER_URL),          # still a paper endpoint
            (self.GOOD_ENV, LIVE_URL),           # missing credentials
        ]
        for env, url in cases:
            with self.subTest(env=env, url=url):
                with self.assertRaises(PermissionError):
                    AlpacaBroker("", "", url, enable_live=True, env=env)

    def test_live_gate_opens_only_with_everything(self):
        b = AlpacaBroker("key", "secret", LIVE_URL, enable_live=True,
                         env=dict(self.GOOD_ENV))
        self.assertTrue(b.is_live)

    def test_submit_order_without_network(self):
        seen = {}

        def fake(method, path, headers, payload):
            seen.update(method=method, path=path, headers=headers, payload=payload)
            return {"id": "broker-123", "status": "filled", "filled_avg_price": "101.5"}

        b = AlpacaBroker("key", "secret", PAPER_URL, env={}, request_fn=fake)
        o = b.submit_order(OrderRequest("MSFT", Side.BUY, 3), 100.0)
        self.assertEqual(o.status, OrderStatus.FILLED)
        self.assertEqual(o.broker_order_id, "broker-123")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["path"], "/v2/orders")
        self.assertEqual(seen["payload"]["client_order_id"], o.request.client_order_id)

    def test_rejected_order_does_not_raise(self):
        def fake(*args, **kwargs):
            raise RuntimeError("Alpaca POST /v2/orders failed (422): insufficient buying power")

        b = AlpacaBroker("key", "secret", PAPER_URL, env={}, request_fn=fake)
        o = b.submit_order(OrderRequest("MSFT", Side.BUY, 3), 100.0)
        self.assertEqual(o.status, OrderStatus.REJECTED)
        self.assertIn("insufficient", o.message)

    def test_repr_does_not_leak_secret(self):
        b = AlpacaBroker("my-secret-key", "my-secret-value")
        self.assertNotIn("my-secret", repr(b))


if __name__ == "__main__":
    unittest.main()
