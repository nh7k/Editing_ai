"""Intent eval on eval/intent_corpus.yaml: BEFORE (tools.parse, then the old nearest()) vs AFTER (tools.resolve with
the context). Writes eval/results/intent_eval.json; docs/INTENT_EVAL.md is written from it by hand.

    backend/.venv/Scripts/python.exe eval/run_intent_eval.py            # dev + regression items
    backend/.venv/Scripts/python.exe eval/run_intent_eval.py --heldout  # once, at the end
    backend/.venv/Scripts/python.exe eval/run_intent_eval.py --sweep    # threshold calibration on dev

Silent wrong edit = the system would APPLY a skill without asking and it is the wrong one (the worst outcome).
BEFORE applies whenever the exact matcher returns calls; AFTER applies only on decision == "apply".
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cutmind.tools import resolve as R  # noqa: E402
from cutmind.tools.parse import nearest, parse  # noqa: E402


def before(prompt: str) -> tuple[list[str], bool]:
    r = parse(prompt)
    if r["calls"]:
        return [c["id"] for c in r["calls"]][:3], True
    return [n["id"] for n in nearest(prompt)][:3], False


def after(prompt: str, ctx: dict | None) -> tuple[list[str], bool, str]:
    res = R.resolve(prompt, ctx or {})
    return [c["id"] for c in res.choices][:3], res.decision == "apply", res.decision


def evaluate(items: list[dict], fn) -> dict:
    n = top1 = top3 = applied = silent_wrong = asked = 0
    per = defaultdict(lambda: [0, 0, 0])
    fails = []
    lat = []
    for it in items:
        t0 = time.perf_counter()
        out = fn(it)
        lat.append((time.perf_counter() - t0) * 1000)
        ids, apply_ = out[0], out[1]
        exp = it["expect"]
        ok1 = bool(ids) and ids[0] == exp
        ok3 = exp in ids and all(a in ids for a in it.get("also_top3", []))
        n += 1
        top1 += ok1
        top3 += ok3
        applied += apply_
        asked += not apply_
        silent_wrong += apply_ and not ok1
        p = per[exp]
        p[0] += 1
        p[1] += ok1
        p[2] += ok3
        if not ok1:
            fails.append({"prompt": it["prompt"], "expect": exp, "got": ids, "applied": apply_})
    lat.sort()
    return {"n": n, "top1": round(top1 / n, 3), "top3": round(top3 / n, 3), "applied": applied, "asked": asked,
            "silent_wrong": silent_wrong, "silent_wrong_rate": round(silent_wrong / n, 3),
            "latency_ms_p50": round(lat[len(lat) // 2], 1), "latency_ms_p95": round(lat[int(len(lat) * 0.95)], 1),
            "per_skill": {k: {"n": v[0], "top1": v[1], "top3": v[2]} for k, v in sorted(per.items())},
            "fails": fails}


def sweep(items: list[dict]) -> list[dict]:
    """Apply-directly thresholds: for each (APPLY_MIN, MARGIN), how many requests go straight through and how many
    of those are wrong. The rule we want: as many applied as possible with silent wrong edits ≤ 1 %."""
    rows = []
    keep = (R.APPLY_MIN, R.MARGIN)
    try:
        for amin in (0.6, 0.7, 0.8, 0.9):
            for marg in (0.05, 0.1, 0.2, 0.3):
                R.APPLY_MIN, R.MARGIN = amin, marg
                e = evaluate(items, lambda it: after(it["prompt"], it.get("context")))
                rows.append({"apply_min": amin, "margin": marg, "applied": e["applied"], "silent_wrong": e["silent_wrong"],
                             "top1": e["top1"], "top3": e["top3"]})
    finally:
        R.APPLY_MIN, R.MARGIN = keep
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    data = yaml.safe_load((ROOT / "eval" / "intent_corpus.yaml").read_text(encoding="utf-8"))["items"]
    held = "--heldout" in sys.argv
    items = [x for x in data if (x.get("split") == "heldout") == held or (not held and "split" not in x)]
    out_path = ROOT / "eval" / "results" / ("intent_eval_heldout.json" if held else "intent_eval.json")
    if "--sweep" in sys.argv:
        rows = sweep(items)
        (ROOT / "eval" / "results" / "intent_sweep.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
        for r in rows:
            print(r)
        return
    b = evaluate(items, lambda it: before(it["prompt"]))
    a = evaluate(items, lambda it: after(it["prompt"], it.get("context")))
    res = {"split": "heldout" if held else "dev+regression", "before": b, "after": a,
           "thresholds": {"apply_min": R.APPLY_MIN, "margin": R.MARGIN, "choose_min": R.CHOOSE_MIN}}
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    for k in ("before", "after"):
        e = res[k]
        print(f"{k:6}: n={e['n']} top1={e['top1']} top3={e['top3']} applied={e['applied']} asked={e['asked']} "
              f"silent_wrong={e['silent_wrong']} p50={e['latency_ms_p50']}ms p95={e['latency_ms_p95']}ms")
    print("worst AFTER failures:")
    for f in a["fails"][:25]:
        print("  ", f)


if __name__ == "__main__":
    main()
