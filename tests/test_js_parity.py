"""Optional cross-language test: Python engine vs the browser engine.

Skipped when Node.js is unavailable. CI runs it explicitly via
scripts/verify_parity.js as well.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NODE_CANDIDATES = [
    shutil.which("node"),
    r"C:\Users\DELL\.workbuddy\binaries\node\versions\22.22.2-3\node.exe",
]


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = next((p for p in NODE_CANDIDATES if p and Path(p).exists()), None)

    def test_python_matches_javascript(self):
        if not self.node:
            self.skipTest("Node.js not available")
        if not (ROOT / "web" / "data.js").exists():
            self.skipTest("web/data.js not generated")
        with tempfile.TemporaryDirectory() as d:
            ref = Path(d) / "reference.json"
            a = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_parity.py"),
                                "--out", str(ref)], capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(a.returncode, 0, a.stderr)
            b = subprocess.run([self.node, str(ROOT / "scripts" / "verify_parity.js"), str(ref)],
                               capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(b.returncode, 0, b.stdout + b.stderr)
            self.assertIn("PARITY OK", b.stdout)


if __name__ == "__main__":
    unittest.main()
