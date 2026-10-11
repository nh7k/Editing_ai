"""Accuracy as the catalog grows (docs/UNDERSTANDING_REVIEW.md §2.2): the real skills + N synthetic distractor
skills, scored on the hand-written dev single-skill prompts. Two kinds of distractors:

  hard    synonyms recombined from the words of real skills of the SAME category (the realistic case: a
          catalog of 2,000 grows by more colour / motion / text skills that share words)
  random  synonyms recombined from the whole vocabulary

Two rankers:
  flat           tools.resolve.score_skills over every skill
  category-first pick the 2 best categories by a category lexicon (words that are typical of one category),
                 then score only the skills inside them

Only the retrieval step is measured (the exact parser is not part of this test). Writes eval/results/scale.json.

    backend/.venv/Scripts/python.exe eval/scale_test.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cutmind.tools import resolve as R  # noqa: E402
from cutmind.tools import spec  # noqa: E402
from cutmind.tools.fuzzy import FILLER, canonical_words  # noqa: E402

REAL = spec.load()


def synthetic(n: int, kind: str, seed: int = 7) -> dict[str, dict]:
    rnd = random.Random(seed)
    by_cat: dict[str, list[str]] = defaultdict(list)
    for s in REAL.values():
        for ps in s["synonyms"].values():
            for p in ps:
                by_cat[s["category"]] += [w for w in canonical_words(p) if w not in FILLER and w.isalpha()]
    every = [w for ws in by_cat.values() for w in ws]
    cats = sorted(by_cat)
    out = {}
    for i in range(n):
        cat = rnd.choice(cats)
        pool = by_cat[cat] if kind == "hard" else every
        made_up = "".join(rnd.choice("bcdfghjklmnprstvz") + rnd.choice("aeiou") for _ in range(3))
        syns = [" ".join(rnd.sample(pool, k=rnd.choice([2, 3])) + ([made_up] if rnd.random() < 0.5 else []))
                for _ in range(8)]
        out[f"syn_{i}"] = {"id": f"syn_{i}", "category": cat, "name": f"synthetic {made_up}",
                           "synonyms": {"en": syns}, "params": {}, "time_modes": ["whole"], "examples": []}
    return out


def use_catalog(cat: dict[str, dict]) -> None:
    spec.load = lambda: cat  # type: ignore[assignment]  # noqa: E731
    for f in (R._index, R._phrase_table, R._vocab_by_len, R._near):
        f.cache_clear()


def category_lexicon(cat: dict[str, dict]) -> dict[str, dict[str, float]]:
    """word → {category: weight}: how much a word points at a category (share of its uses there × idf)."""
    count: dict[str, Counter] = defaultdict(Counter)
    for s in cat.values():
        for ps in s["synonyms"].values():
            for p in ps:
                for w in set(canonical_words(p)) - FILLER:
                    count[w][s["category"]] += 1
    n_cat = len({s["category"] for s in cat.values()})
    lex = {}
    for w, c in count.items():
        tot = sum(c.values())
        idf = math.log(1 + n_cat / len(c))
        lex[w] = {k: v / tot * idf for k, v in c.items()}
    return lex


def rank(words: list[str], cat: dict[str, dict], lex: dict | None) -> list[str]:
    scores = R.score_skills(words)
    if lex is not None:
        cs: Counter = Counter()
        for w in words:
            for k, v in lex.get(w, {}).items():
                cs[k] += v
        keep = {k for k, _ in cs.most_common(2)}
        if keep:
            scores = {k: v for k, v in scores.items() if cat[k]["category"] in keep}
    return [k for k, _ in sorted(scores.items(), key=lambda kv: -kv[1][0])]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    items = [x for x in yaml.safe_load((ROOT / "eval" / "understanding_corpus.yaml").read_text(encoding="utf-8"))["items"]
             if x["split"] == "dev" and x["kind"] == "single" and not x.get("context")]
    real = dict(REAL)
    rows = []
    for kind in ("hard", "random"):
        for total in (len(real), 500, 2000, 10000):
            cat = {**real, **synthetic(max(0, total - len(real)), kind)}
            use_catalog(cat)
            t0 = time.perf_counter()
            R._phrase_table()
            build = time.perf_counter() - t0
            lex = category_lexicon(cat)
            for mode in ("flat", "category-first"):
                t1 = time.perf_counter()
                top1 = top3 = 0
                for it in items:
                    ids = rank(canonical_words(it["prompt"]), cat, lex if mode == "category-first" else None)
                    top1 += bool(ids) and ids[0] == it["expect"]
                    top3 += it["expect"] in ids[:3]
                ms = (time.perf_counter() - t1) * 1000 / len(items)
                row = {"distractors": kind, "skills": len(cat), "ranker": mode, "top1": round(top1 / len(items), 3),
                       "top3": round(top3 / len(items), 3), "ms_per_prompt": round(ms, 1), "index_build_s": round(build, 1)}
                rows.append(row)
                print(row, flush=True)
    use_catalog(real)
    (ROOT / "eval" / "results" / "scale.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
