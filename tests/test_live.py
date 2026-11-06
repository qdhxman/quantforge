import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantforge.brokers import LIVE_URL, AlpacaBroker, PaperBroker  # noqa: E402
from quantforge.config import default_config  # noqa: E402
from quantforge.data import generate_synthetic  # noqa: E402
from quantforge.journal import Journal, redact  # noqa: E402
from quantforge.live import LiveTradingEngine  # noqa: E402


class LiveEngineTests(unittest.TestCase):
    def setUp(self):
        self.cfg = default_config()
        self.cfg.trading.mode = "paper"
        self.data = generate_synthetic(n_bars=140, seed=11)
        self.broker = PaperBroker(self.cfg.backtest.initial_cash)
        self.engine = LiveTradingEngine(self.cfg, self.broker, self.data,
                                       journal=Journal(), start_index=60, env={})

    def test_run_cycle_is_deterministic_and_audited(self):
        step = self.engine.run_cycle()
        self.assertEqual(len(step.signals), len(self.cfg.symbols))
        self.assertIn("orders", step.as_dict())
        self.assertEqual(self.engine.status()["cycles"], 1)
        self.engine.run(interval_seconds=0, max_cycles=5)
        self.assertEqual(self.engine.status()["cycles"], 6)
        types = [e["type"] for e in self.engine.journal.events]
        self.assertIn("ENGINE_START", types)
        self.assertIn("ENGINE_STOP", types)

    def test_halt_freezes_the_loop(self):
        self.engine.run(interval_seconds=0, max_cycles=3)
        self.engine.halt("unit test")
        after = self.engine.run_cycle()
        self.assertTrue(after.halted)
        self.assertEqual(after.orders, [])
        self.assertIn("ENGINE_HALT", [e["type"] for e in self.engine.journal.events])

    def test_env_kill_switch_halts_on_first_cycle(self):
        env = {"QFI_KILL_SWITCH": "1"}
        engine = LiveTradingEngine(self.cfg, PaperBroker(), self.data,
                                   journal=Journal(), start_index=60, env=env)
        step = engine.run_cycle()
        self.assertTrue(step.halted)
        self.assertEqual(step.orders, [])

    def test_mode_mismatch_refused(self):
        cfg = default_config()
        cfg.trading.mode = "live"
        with self.assertRaises(PermissionError):
            LiveTradingEngine(cfg, PaperBroker(), self.data, journal=Journal(), env={})

        live_broker = AlpacaBroker("k", "s", LIVE_URL, enable_live=True,
                                   env={"QFI_ALLOW_LIVE": "1", "QFI_CONFIRM_LIVE_TRADING": "I_UNDERSTAND"})
        cfg.trading.mode = "paper"
        with self.assertRaises(PermissionError):
            LiveTradingEngine(cfg, live_broker, self.data, journal=Journal(), env={})

    def test_journal_redacts_secrets(self):
        event = redact({"api_key": "abc", "nested": {"secret_key": "def", "qty": 3}})
        self.assertEqual(event["api_key"], "***")
        self.assertEqual(event["nested"]["secret_key"], "***")
        self.assertEqual(event["nested"]["qty"], 3)

    def test_journal_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "logs" / "j.jsonl"
            j = Journal(p)
            j.append("ORDER_SUBMITTED", symbol="AAPL", api_key="should-be-hidden")
            raw = p.read_text(encoding="utf-8")
            self.assertIn("ORDER_SUBMITTED", raw)
            self.assertNotIn("should-be-hidden", raw)
            self.assertEqual(len(j.read()), 1)


if __name__ == "__main__":
    unittest.main()
