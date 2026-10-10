"""CutMind eval harness: every case in eval/cases.yaml goes through the SAME path as a chat message in the app
(validate_prompt → PhraseBook.expand [rules → planner LLM router → translator] → parse_intent) and its expected
properties are checked.

    python eval/run_eval.py                                  # rules only (deterministic, the baseline)
    python eval/run_eval.py --provider llamacpp --model qwen3-1.7b
    python eval/run_eval.py --provider llamacpp --model qwen3-1.7b --big qwen3-4b
    python eval/run_eval.py --only paraphrase,devanagari     # some kinds only

Writes eval/results/<label>.json and prints a table. The translator model is off (CUTMIND_TRANSLATOR=off) so only
the provider under test adds understanding.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CUTMIND_TRANSLATOR", "off")


def check(intent: dict[str, Any], understood: bool, expect: dict[str, Any], error: str | None) -> list[str]:
    """The failed expectations (empty = pass)."""
    bad = []
    for key, want in expect.items():
        if key == "error":
            if error != want:
                bad.append(f"error {error!r} != {want!r}")
            continue
        if error:
            bad.append(f"refused ({error})")
            break
        if key == "understood":
            if understood != want:
                bad.append(f"understood {understood} != {want}")
            continue
        field, _, op = key.partition("__")
        got = intent.get(field)
        if op == "has":
            ok = (want in got) if isinstance(got, (list, str)) else False
            if isinstance(got, list) and field == "drop_clips":
                ok = want in got
        elif op == "not":
            ok = not (isinstance(got, (list, str)) and want in got) and got != want
        elif op == "min":
            ok = (len(got) if isinstance(got, list) else got) is not None and \
                (len(got) if isinstance(got, list) else got) >= want
        elif op == "max":
            ok = got is not None and got <= want
        else:
            ok = got == want
        if not ok:
            bad.append(f"{key}: got {got!r}, want {want!r}")
    return bad


def run(provider: str, model: str | None, big: str | None, only: set[str] | None) -> dict[str, Any]:
    os.environ["LLM_PROVIDER"] = provider
    if model:
        os.environ["LLM_MODEL"] = model
    if big:
        os.environ["LLM_MODEL_BIG"] = big
    from cutmind import llm_router
    from cutmind.db import Database
    from cutmind.intent import PromptError, parse_intent, validate_prompt
    from cutmind.phrasebook import PhraseBook

    cases = yaml.safe_load((ROOT / "eval" / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    if only:
        cases = [c for c in cases if c["kind"] in only]
    warm = None
    if provider in ("llamacpp", "auto"):  # production warms the model at startup (api.py); so does the eval
        from cutmind.llm_provider import get_provider

        p = get_provider(model=model)
        if hasattr(p, "warm_up"):
            warm = p.warm_up()
            print(f"warm-up {warm}s", flush=True)
    db = Database(Path(tempfile.mkdtemp()) / "eval.sqlite3")
    book = PhraseBook(db)
    rows, llm_calls = [], []
    t_all = time.monotonic()
    for c in cases:
        t0 = time.monotonic()
        error = None
        intent: dict[str, Any] = {}
        understood = False
        traces: list[dict[str, Any]] = []
        try:
            prompt = validate_prompt(c["prompt"])
            llm_router.last_trace = []
            expanded = book.expand(prompt, ask=False)[0]
            traces = list(llm_router.last_trace)
            it = parse_intent(expanded)
            intent, understood = it.model_dump(), not it.is_empty()
        except PromptError:
            error = "bad_prompt"
        except Exception as exc:  # noqa: BLE001 — a crash is a failed case, never a crashed eval
            error = f"crash: {exc}"
        fails = check(intent, understood, c["expect"], error)
        for t in traces:
            if t.get("provider") not in (None, "rules"):
                llm_calls.append(t)
        rows.append({"id": c["id"], "kind": c["kind"], "lang": c["lang"], "prompt": c["prompt"], "pass": not fails,
                     "fails": fails, "seconds": round(time.monotonic() - t0, 2), "llm": traces,
                     "recognized": intent.get("recognized", [])})
        print(f"{'PASS' if not fails else 'FAIL'} {c['id']:4s} {rows[-1]['seconds']:5.1f}s  {c['prompt'][:50]!r}"
              + ("" if not fails else f"  -> {fails[:2]}"), flush=True)
    by_kind: dict[str, list[bool]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r["pass"])
    lat = sorted(t["seconds"] for t in llm_calls if "seconds" in t)
    valid = [t for t in llm_calls if "seconds" in t]  # the model answered with parseable JSON
    return {
        "label": f"{provider}" + (f"-{model}" if model and provider != "rules" else "") + (f"+{big}" if big else ""),
        "cases": len(rows), "passed": sum(r["pass"] for r in rows),
        "accuracy": round(sum(r["pass"] for r in rows) / max(1, len(rows)), 3),
        "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_kind.items())},
        "llm": {"calls": len(llm_calls), "json_valid": len(valid),
                "json_valid_rate": round(len(valid) / len(llm_calls), 3) if llm_calls else None,
                "used": sum(1 for t in llm_calls if t.get("result") == "used"),
                "rejected": sum(1 for t in llm_calls if str(t.get("result", "")).startswith("rejected")),
                "p50_s": round(statistics.median(lat), 2) if lat else None,
                "p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2) if lat else None},
        "total_seconds": round(time.monotonic() - t_all, 1), "warm_up_s": warm,
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="rules")
    ap.add_argument("--model")
    ap.add_argument("--big")
    ap.add_argument("--only")
    ap.add_argument("--label")
    a = ap.parse_args()
    rep = run(a.provider, a.model, a.big, set(a.only.split(",")) if a.only else None)
    if a.label:
        rep["label"] = a.label
    out = ROOT / "eval" / "results" / f"{rep['label']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "rows"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
