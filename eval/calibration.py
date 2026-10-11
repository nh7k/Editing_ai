"""Confidence vs correctness (docs/UNDERSTANDING_EVAL.md): for single-skill prompts, bucket the resolver's top score
(and whether the exact matcher fired) and report how often the top reading was right. Thresholds are read off this
table, not guessed. Writes eval/results/calibration.json.

    backend/.venv/Scripts/python.exe eval/calibration.py [--heldout]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cutmind.tools.resolve import resolve, warm  # noqa: E402

BINS = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01), (1.01, 9.0)]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    held = "--heldout" in sys.argv
    warm()
    items = [x for x in yaml.safe_load((ROOT / "eval" / "understanding_corpus.yaml").read_text(encoding="utf-8"))["items"]
             if x["kind"] == "single" and (x["split"] == "heldout") == held and x["split"] != "generated"]
    by_bin: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_decision: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for it in items:
        r = resolve(it["prompt"], it.get("context") or {})
        if not r.choices:
            continue
        top = float(r.choices[0]["score"]) if r.trace.get("exact", {}).get("calls") is None or r.decision != "apply" \
            else 1.0
        ok = r.choices[0]["id"] == it["expect"]
        b = next(f"{lo:.1f}-{hi:.1f}" for lo, hi in BINS if lo <= top < hi)
        by_bin[b][0] += 1
        by_bin[b][1] += ok
        by_decision[r.decision][0] += 1
        by_decision[r.decision][1] += ok
    rows = {"bins": {k: {"n": v[0], "right": v[1], "accuracy": round(v[1] / v[0], 3)} for k, v in sorted(by_bin.items())},
            "decisions": {k: {"n": v[0], "right": v[1], "accuracy": round(v[1] / v[0], 3)} for k, v in by_decision.items()}}
    out = ROOT / "eval" / "results" / f"calibration{'_heldout' if held else ''}.json"
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
