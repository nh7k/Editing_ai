"""Scores the skill matcher (synonyms + the rule parser) on the held-out prompts in eval/skill_prompts.yaml.

    python eval/run_skill_eval.py           # writes eval/results/skill_eval.json and prints the summary
Metrics: per-skill hit rate (the expected skill is among the matched ones), multi-skill recall, contradictory prompts
never crash, unsupported prompts are refused with 3 suggestions, share of prompts that would need the LLM.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_PROVIDER", "rules")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Devanagari prompts in the miss list
    from cutmind import skill_registry as R
    from cutmind.prompt_enhancer import enhance

    data = yaml.safe_load((ROOT / "eval" / "skill_prompts.yaml").read_text(encoding="utf-8"))
    rows, by_skill = [], {}
    t0 = time.monotonic()
    for sid, prompts in data["per_skill"].items():
        hits = 0
        for p in prompts:
            r = enhance(p)
            ok = sid in r["skills"]
            hits += ok
            rows.append({"skill": sid, "prompt": p, "ok": ok, "got": r["skills"], "needs_model": r["needs_model"]})
        by_skill[sid] = f"{hits}/{len(prompts)}"
    single = [r for r in rows]
    multi = []
    for m in data["multi_skill"]:
        got = set(enhance(m["prompt"])["skills"])
        multi.append({"prompt": m["prompt"], "recall": round(len(got & set(m["expect"])) / len(m["expect"]), 2),
                      "missing": sorted(set(m["expect"]) - got)})
    contra = []
    for c in data["contradictory"]:
        try:
            enhance(c["prompt"])
            contra.append({"prompt": c["prompt"], "ok": True})
        except Exception as exc:  # noqa: BLE001
            contra.append({"prompt": c["prompt"], "ok": False, "error": str(exc)})
    unsup = []
    for u in data["unsupported"]:
        r = enhance(u["prompt"])
        planned = [s for s in R.understand(u["prompt"])["skills"] if R.load()[s]["status"] in ("planned", "blocked")]
        unsup.append({"prompt": u["prompt"], "understood": r["understood"], "skills": r["skills"],
                      "suggestions": [s["id"] for s in r["suggestions"]], "planned_named": planned,
                      "said_not_available": [x["id"] for x in r["not_available"]]})
    hit = sum(r["ok"] for r in single)
    rep = {
        "single": {"prompts": len(single), "hits": hit, "accuracy": round(hit / len(single), 3)},
        "by_skill": by_skill,
        "needs_model_share": round(sum(r["needs_model"] for r in single) / len(single), 3),
        "multi_skill": multi, "contradictory": contra, "unsupported": unsup,
        "misses": [r for r in single if not r["ok"]], "seconds": round(time.monotonic() - t0, 1),
    }
    out = ROOT / "eval" / "results" / "skill_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "misses"}, ensure_ascii=False, indent=1))
    print("misses:")
    for r in rep["misses"]:
        print(f"  {r['skill']:16} {r['prompt']!r} -> {r['got']}")


if __name__ == "__main__":
    main()
