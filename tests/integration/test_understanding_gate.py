"""CI gate (docs/UNDERSTANDING_REVIEW.md): no skill may lose first-try accuracy, no dead end, no over-limit confusion.
Slow-ish (~1-2 min): it scores the whole understanding corpus."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("script", ["regression_gate.py", "confusability.py"])
def test_gate(script):
    r = subprocess.run([sys.executable, str(ROOT / "eval" / script)], capture_output=True, text=True, timeout=900,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
