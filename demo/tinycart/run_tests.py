"""Run TinyCart's tests without installing the demo package."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(ROOT / "tests"))
    raise SystemExit(0 if result.wasSuccessful() else 1)
