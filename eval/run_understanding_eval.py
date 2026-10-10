"""Understanding eval v2 on eval/understanding_corpus.yaml (docs/UNDERSTANDING_REVIEW.md, Phase 7).

    backend/.venv/Scripts/python.exe eval/run_understanding_eval.py [--tag before|after] [--heldout]

Every prompt goes through tools.resolve.resolve() and the Resolution is read as an outcome:
  applied   tool calls that would run without a tap
  shown     every skill on screen: applied ones + alternative chips
  non_edit  the system answered without editing (greeting / question)
Metrics per kind (see the corpus file); "dead end" = nothing applied, nothing to tap, and not a non-edit answer.
"Silent wrong edit" = something wrong was applied AND no alternative was shown (the user cannot fix it in one tap).
Writes eval/results/understanding_<tag>.json.
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
from cutmind.tools.resolve import resolve  # noqa: E402


def outcome(r) -> dict:  # noqa: ANN001
    d = r.to_dict()
    applied = [c for c in d.get("apply", [])] if "apply" in d else []
    if not applied and d["decision"] in ("apply", "act") and d["choices"]:
        applied = list(d["choices"][0]["calls"])
    alt = d["choices"][1:] if d["decision"] in ("apply", "act") else d["choices"]
    shown = [c["id"] for c in applied] + [c["id"] for c in alt]
    for u in d.get("unclear", []):
        shown += [c["id"] for c in u.get("choices", [])]
    return {"decision": d["decision"], "applied": applied, "applied_ids": [c["id"] for c in applied],
            "alternatives": [c["id"] for c in alt], "shown": shown, "non_edit": d["decision"] == "non_edit",
            "unclear": len(d.get("unclear", []))}


def direction(call: dict, recent: dict, param: str) -> str:
    if call.get("remove"):
        return "remove"
    a = (call.get("params") or {}).get(param)
    b = (recent.get("params") or {}).get(param)
    if a is None or b is None:
        return "same" if call["id"] == recent["id"] else "?"
    return "up" if float(a) > float(b) + 1e-9 else "down" if float(a) < float(b) - 1e-9 else "same"


def judge(it: dict, o: dict) -> dict:
    kind = it["kind"]
    res = {"dead_end": not o["applied"] and not o["shown"] and not o["non_edit"]}
    if kind == "single":
        first = (o["applied_ids"] or o["alternatives"] or [None])[0]
        res["top1"] = first == it["expect"]
        res["top3"] = it["expect"] in o["shown"][:3] and all(a in o["shown"][:3] for a in it.get("also_top3", []))
        res["silent_wrong"] = bool(o["applied"]) and not res["top1"] and not o["alternatives"]
        res["wrong_applied"] = bool(o["applied"]) and it["expect"] not in o["applied_ids"]
    elif kind == "multi":
        res["all_applied"] = all(s in o["applied_ids"] for s in it["expect_all"])
        res["share_applied"] = sum(s in o["applied_ids"] for s in it["expect_all"]) / len(it["expect_all"])
        res["unsupported_flagged"] = it["unsupported"] == 0 or o["unclear"] >= 1 or bool(o["alternatives"])
    elif kind == "relative":
        recent = it["context"]["recent_edits"][-1]
        calls = [c for c in o["applied"] if c["id"] == it["expect"]]
        res["right"] = bool(calls) and direction(calls[0], recent, it.get("param") or "") == it["direction"]
    elif kind == "non_edit":
        res["right"] = o["non_edit"] or (not o["applied"])
        res["no_edit_started"] = not o["applied"]
    elif kind == "unsupported":
        res["right"] = not o["applied"] and bool(o["shown"])
        res["no_edit_started"] = not o["applied"]
    return res


def summarize(rows: list[dict]) -> dict:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["kind"]].append(r)
    out: dict = {"n": len(rows), "dead_end": sum(r["res"]["dead_end"] for r in rows)}
    s = by.get("single", [])
    if s:
        out["single"] = {"n": len(s), "top1": round(sum(r["res"]["top1"] for r in s) / len(s), 3),
                         "top3": round(sum(r["res"]["top3"] for r in s) / len(s), 3),
                         "silent_wrong": sum(r["res"]["silent_wrong"] for r in s),
                         "wrong_applied": sum(r["res"]["wrong_applied"] for r in s)}
    m = by.get("multi", [])
    if m:
        out["multi"] = {"n": len(m), "all_applied": sum(r["res"]["all_applied"] for r in m),
                        "mean_share_applied": round(sum(r["res"]["share_applied"] for r in m) / len(m), 3),
                        "unsupported_flagged": sum(r["res"]["unsupported_flagged"] for r in m)}
    for k in ("relative", "non_edit", "unsupported"):
        if by.get(k):
            out[k] = {"n": len(by[k]), "right": sum(r["res"]["right"] for r in by[k])}
    lat = sorted(r["ms"] for r in rows)
    out["latency_ms"] = {"p50": round(lat[len(lat) // 2], 1), "p95": round(lat[int(len(lat) * 0.95)], 1),
                         "max": round(lat[-1], 1)}
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "now"
    held = "--heldout" in sys.argv
    items = yaml.safe_load((ROOT / "eval" / "understanding_corpus.yaml").read_text(encoding="utf-8"))["items"]
    from cutmind.tools.resolve import warm

    warm()
    rows = []
    for it in items:
        if (it["split"] == "heldout") != held:
            continue
        t = time.perf_counter()
        r = resolve(it["prompt"], it.get("context") or {})
        ms = (time.perf_counter() - t) * 1000
        o = outcome(r)
        rows.append({"kind": it["kind"], "group": it["group"], "split": it["split"], "prompt": it["prompt"],
                     "expect": it.get("expect") or it.get("expect_all"), "decision": o["decision"],
                     "applied": o["applied_ids"], "shown": o["shown"][:6], "ms": round(ms, 1), "res": judge(it, o)})
    report = {"tag": tag, "split": "heldout" if held else "dev+generated",
              "all": summarize(rows),
              "handwritten": summarize([r for r in rows if r["split"] != "generated"]),
              "generated": summarize([r for r in rows if r["split"] == "generated"]) if not held else None,
              "by_group": {g: summarize([r for r in rows if r["group"] == g]) for g in sorted({r["group"] for r in rows})},
              "fails": [r for r in rows if not (r["res"].get("top1") or r["res"].get("all_applied") or r["res"].get("right"))]}
    out = ROOT / "eval" / "results" / f"understanding_{tag}{'_heldout' if held else ''}.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("all", "handwritten", "generated")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
