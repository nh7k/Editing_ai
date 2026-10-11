"""Regression gate: no skill may get worse at being picked first (docs/UNDERSTANDING_REVIEW.md, Phase 7).

Per skill, counts how many of its single-skill prompts (hand-written dev + generated) put it first. Compares with
eval/results/per_skill_baseline.json and exits 1 if any skill lost even one, or if a dead end appears.

    backend/.venv/Scripts/python.exe eval/regression_gate.py            # check
    backend/.venv/Scripts/python.exe eval/regression_gate.py --update   # accept the current numbers as the baseline
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))
from cutmind.tools.resolve import resolve, warm  # noqa: E402
from run_understanding_eval import judge, outcome  # noqa: E402

BASE = ROOT / "eval" / "results" / "per_skill_baseline.json"


def measure() -> dict:
    warm()
    items = [x for x in yaml.safe_load((ROOT / "eval" / "understanding_corpus.yaml").read_text(encoding="utf-8"))["items"]
             if x["split"] in ("dev", "generated")]
    first, total, dead = Counter(), Counter(), 0
    for it in items:
        o = outcome(resolve(it["prompt"], it.get("context") or {}))
        j = judge(it, o)
        dead += j["dead_end"]
        if it["kind"] == "single":
            total[it["expect"]] += 1
            first[it["expect"]] += j["top1"]
    return {"dead_end": dead, "skills": {k: {"first": first[k], "n": total[k]} for k in sorted(total)}}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    now = measure()
    if "--update" in sys.argv or not BASE.exists():
        BASE.write_text(json.dumps(now, indent=1), encoding="utf-8")
        print(f"baseline written: {sum(v['first'] for v in now['skills'].values())} first-try hits over "
              f"{len(now['skills'])} skills")
        return
    base = json.loads(BASE.read_text(encoding="utf-8"))
    worse = [(k, base["skills"][k]["first"], v["first"]) for k, v in now["skills"].items()
             if k in base["skills"] and v["first"] < base["skills"][k]["first"]]
    better = [(k, base["skills"][k]["first"], v["first"]) for k, v in now["skills"].items()
              if k in base["skills"] and v["first"] > base["skills"][k]["first"]]
    print(f"dead ends {now['dead_end']} (baseline {base['dead_end']}); better {len(better)}; worse {len(worse)}")
    for k, a, b in worse:
        print(f"  WORSE {k}: {a} → {b}")
    if worse or now["dead_end"] > base["dead_end"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
