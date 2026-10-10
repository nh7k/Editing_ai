"""Language test for Tier 1: every example prompt of every skill (skills/tier1/*.yaml) must resolve to that skill
with the expected parameters, and a multi prompt must also find its other skills.

    backend/.venv/Scripts/python.exe eval/run_tier1_lang.py            # YAML examples (seen while writing synonyms)
    backend/.venv/Scripts/python.exe eval/run_tier1_lang.py heldout    # eval/tier1_heldout.yaml (never used to tune)

Writes eval/results/tier1_lang[_heldout].json. Parameters are compared after defaults are filled (engine.fill_params).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def _same(a: object, b: object) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def check(sid: str, ex: dict, specs: dict) -> tuple[bool, str, dict]:
    from cutmind.tools.engine import fill_params
    from cutmind.tools.parse import parse

    r = parse(ex["prompt"])
    got = next((c for c in r["calls"] if c["id"] == sid), None)
    if got is None:
        return False, "skill not found", r
    try:
        full, _ = fill_params(specs[sid], got["params"])
    except Exception as exc:  # noqa: BLE001 — a missing required param is a miss
        full = dict(got["params"])
        if ex.get("params"):
            return False, f"params: {exc}", r
    for k, v in (ex.get("params") or {}).items():
        if not _same(full.get(k), v):
            return False, f"{k}={full.get(k)!r} want {v!r}", r
    for k, v in (ex.get("time") or {}).items():
        if not got["time"] or not _same(got["time"].get(k), v):
            return False, f"time {k}={got['time'] and got['time'].get(k)!r} want {v!r}", r
    missing = [a for a in ex.get("also", []) if a not in {c["id"] for c in r["calls"]}]
    if missing:
        return False, f"multi: missing {missing}", r
    return True, "", r


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from cutmind.tools import spec

    specs = spec.load()
    heldout = len(sys.argv) > 1 and sys.argv[1] == "heldout"
    if heldout:
        data = yaml.safe_load((ROOT / "eval" / "tier1_heldout.yaml").read_text(encoding="utf-8"))["prompts"]
        cases = [(d["skill"], d) for d in data]
    else:
        cases = [(sid, ex) for sid, s in specs.items() for ex in s["examples"]]
    per: dict[str, list[int]] = {}
    misses = []
    for sid, ex in cases:
        ok, why, r = check(sid, ex, specs)
        per.setdefault(sid, [0, 0])
        per[sid][0] += ok
        per[sid][1] += 1
        if not ok:
            misses.append({"skill": sid, "prompt": ex["prompt"], "lang": ex.get("lang"), "why": why,
                           "got": [(c["id"], c["params"], c["time"]) for c in r["calls"]]})
    hit = sum(v[0] for v in per.values())
    tot = sum(v[1] for v in per.values())
    by_lang: dict[str, list[int]] = {}
    for sid, ex in cases:
        by_lang.setdefault(ex.get("lang", "?"), [0, 0])[1] += 1
    for m in misses:
        by_lang[m["lang"]][0] -= 1
    rep = {"prompts": tot, "correct": hit, "accuracy": round(hit / max(1, tot), 3),
           "by_lang": {k: f"{v[1] + v[0]}/{v[1]}" for k, v in by_lang.items()},
           "per_skill": {k: f"{v[0]}/{v[1]}" for k, v in sorted(per.items())}, "misses": misses}
    if heldout:
        from cutmind.skill_registry import named_later
        from cutmind.tools.parse import parse

        full = yaml.safe_load((ROOT / "eval" / "tier1_heldout.yaml").read_text(encoding="utf-8"))
        multi = []
        for m in full.get("multi", []):
            got = {c["id"] for c in parse(m["prompt"])["calls"]}
            multi.append({"prompt": m["prompt"], "recall": round(len(got & set(m["expect"])) / len(m["expect"]), 2),
                          "exact": got == set(m["expect"]), "missing": sorted(set(m["expect"]) - got),
                          "extra": sorted(got - set(m["expect"]))})
        contra = []
        for c in full.get("contradictory", []):
            try:
                r = parse(c["prompt"])
                contra.append({"prompt": c["prompt"], "ok": True, "calls": [x["id"] for x in r["calls"]], "negated": r["negated"]})
            except Exception as exc:  # noqa: BLE001
                contra.append({"prompt": c["prompt"], "ok": False, "error": str(exc)})
        unsup = []
        for u in full.get("unsupported", []):
            r = parse(u["prompt"])
            nearest = [x["id"] for k in r["unknown"] for x in k["nearest"]][:3]
            unsup.append({"prompt": u["prompt"], "refused": not r["calls"], "wrong_calls": [c["id"] for c in r["calls"]],
                          "not_available_yet": named_later(u["prompt"]), "nearest": nearest, "has_3": len(nearest) == 3})
        rep["multi"] = {"prompts": len(multi), "mean_recall": round(sum(x["recall"] for x in multi) / max(1, len(multi)), 3),
                        "exact": sum(x["exact"] for x in multi), "items": multi}
        rep["contradictory"] = contra
        rep["unsupported"] = unsup
        print(f"multi: {rep['multi']['exact']}/{len(multi)} exact, mean recall {rep['multi']['mean_recall']}")
        for x in multi:
            if not x["exact"]:
                print(f"  MULTI {x['prompt']!r}: missing {x['missing']} extra {x['extra']}")
        print("contradictory:", [(c["prompt"], c.get("calls"), c.get("negated")) for c in contra])
        for u in unsup:
            print(f"  UNSUPPORTED {u['prompt']!r}: refused={u['refused']} wrong={u['wrong_calls']} "
                  f"later={u['not_available_yet']} nearest={u['nearest']}")
    out = ROOT / "eval" / "results" / f"tier1_lang{'_heldout' if heldout else ''}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{hit}/{tot} = {rep['accuracy']:.1%}  by language: {rep['by_lang']}")
    for m in misses:
        print(f"  MISS {m['skill']:18} {m['prompt']!r}: {m['why']} -> {m['got']}")


if __name__ == "__main__":
    main()
