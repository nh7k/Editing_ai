"""From a prompt + where the user is (marker / playhead / what is on screen there) to ranked interpretations.

Never a dead end (docs/INTENT_FAILURE_REVIEW.md):
1. The exact Tier 1 matcher (tools.parse) first: a clear request keeps working exactly as before.
2. Otherwise a weighted token scorer: every skill synonym is scored by how much of its MEANING the prompt covers.
   Each word weighs log(1 + skills / skills-using-it): "white" is rare and decides, "kar" is everywhere and
   counts 0 (fuzzy.FILLER). Words meet through fuzzy.canonical_words / fuzzy.sim (typos, Hinglish spellings,
   Devanagari).
3. Context: "yaha / here / is jagah" (and every timeline comment) is bound to the marker or playhead; the effects
   present there are evidence — "normal jaisa tha" with a black-and-white effect there means "take it off here".
4. Decision: apply directly when the best reading is clearly ahead (DECIDE thresholds, calibrated on
   eval/intent_corpus.yaml — docs/INTENT_EVAL.md); otherwise up to 3 tap-able choices with plain Hinglish labels;
   when nothing is close, the 3 nearest skills computed from the user's own words (still choices, never a fixed
   list).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from . import spec
from .fuzzy import FILLER, canonical_words, sim

# apply directly when top >= APPLY_MIN and (top - second) >= MARGIN; choose when top >= CHOOSE_MIN
APPLY_MIN, MARGIN, CHOOSE_MIN = 0.80, 0.30, 0.30  # dev sweep (eval/results/intent_sweep.json): margin 0.3 → 7 silent wrong of 335
# an exact match is applied without asking only when the prompt's meaning words are mostly explained by the matched
# skills: "CHUP wale part nikal do" matched delete_segment on "nikal do" and ignored "chup" (calibrated on the dev
# corpus: 0.4 cut silent wrong edits 42 → 12 — docs/INTENT_EVAL.md)
UNEXPLAINED_MAX = 0.4
NUMERIC = re.compile(r"\d+(?:\.\d+)?|sec|second|seconds|s|se|to|tak|x|min|minute|qtk\d+")
DEICTIC = {"yaha", "idhar"}  # not "abhi" / "now": in a command they mean "right away", not "at this second"
RESTORE_WORDS = {"normal", "original", "wapas", "pehle"}
REMOVE_WORDS = {"hatao", "hata", "nikal", "nikalo", "remove", "hatana", "band", "uda"}
EFFECT_CATEGORIES = {"color", "motion", "stylize", "transitions"}
FAMILY_OF_CATEGORY = {"color": "color", "motion": "motion", "stylize": "style", "transitions": "style"}
WHITE_FAMILY = ("flash", "fade_white", "brighten_to_white", "white_screen_card")  # order = prior on a tie
WINDOW_S = 2.5  # how long an effect placed "here" lasts
# verbs that say "do it" but not WHAT: a synonym made only of these ("yahan dikhao") is weak evidence
VERBS = {"dikhao", "dikha", "lagao", "laga", "daalo", "dalo", "daal", "add", "banao", "bana", "chahiye", "put", "show",
         "make", "apply", "use", "karo", "lagado", "dikhana", "chalao"}
VERB_WEIGHT = 0.5  # dev sweep: 0.25 → 10 silent wrong edits, 0.5 → 8
QUOTED = re.compile(r"['\"‘“][^'\"’”]{1,80}['\"’”]")


@dataclass
class Resolution:
    choices: list[dict[str, Any]]
    decision: str  # "apply" | "choose" | "unknown"
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "choices": self.choices, "trace": self.trace}


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, list[list[str]]], dict[str, float]]:
    """skill → its synonym phrases as canonical words; word → weight (0 for filler, else idf over skills)."""
    phrases: dict[str, list[list[str]]] = {}
    for sid, s in spec.load().items():
        ps = [canonical_words(p) for lang in s["synonyms"].values() for p in lang]
        ps.append(canonical_words(s["name"]))
        phrases[sid] = [p for p in ps if p]
    df: dict[str, int] = {}
    for _sid, ps in phrases.items():
        for w in {w for p in ps for w in p}:
            df[w] = df.get(w, 0) + 1
    n = len(phrases)
    weight = {w: (0.0 if w in FILLER else math.log(1 + n / d)) for w, d in df.items()}
    return phrases, weight


def _weight(w: str, weights: dict[str, float]) -> float:
    if w in FILLER or NUMERIC.fullmatch(w):
        return 0.0
    base = weights.get(w, math.log(1 + len(_index()[0])))
    return base * VERB_WEIGHT if w in VERBS else base


@lru_cache(maxsize=1)
def _vocab_by_len() -> dict[int, list[str]]:
    by: dict[int, list[str]] = {}
    for w in {t for ps in _index()[0].values() for p in ps for t in p}:
        by.setdefault(len(w), []).append(w)
    return by


@lru_cache(maxsize=20000)
def _near(word: str) -> dict[str, float]:
    """Synonym words alike to a prompt word (only lengths within 2 can be alike — sim() needs ≤ 2 edits or the same
    phonetic key, which keeps the length close): a few hundred comparisons instead of every word."""
    by = _vocab_by_len()
    out = {}
    for n in range(max(1, len(word) - 3), len(word) + 4):
        for t in by.get(n, ()):
            v = sim(word, t)
            if v > 0:
                out[t] = v
    return out


def _best(t: str, near: list[dict[str, float]]) -> float:
    return max((m.get(t, 0.0) for m in near), default=0.0)


def score_skills(words: list[str]) -> dict[str, tuple[float, str]]:
    """Every skill's best synonym coverage of the prompt words: {skill: (score 0..1, the synonym that matched)}."""
    phrases, weights = _index()
    prompt = [w for w in words if w not in FILLER and not NUMERIC.fullmatch(w)]  # numbers are read by the parser
    out: dict[str, tuple[float, str]] = {}
    if not prompt:
        return out
    near = [_near(q) for q in prompt]
    for sid, ps in phrases.items():
        best, best_p = 0.0, ""
        for p in ps:
            ws = [(t, _weight(t, weights)) for t in p]
            total = sum(x for _, x in ws)
            if total <= 0:
                continue
            got = sum(x * _best(t, near) for t, x in ws if x > 0)
            cov = got / total
            # a synonym that says more (more meaning words) is a slightly better witness than a one-word one
            # (a stronger length penalty was tried and lost: dev top-1 0.887 vs 0.913 — docs/INTENT_EVAL.md)
            sc = cov * (0.85 + 0.15 * min(1.0, total / 6.0))
            if sc > best:
                best, best_p = sc, " ".join(p)
        if best > 0:
            out[sid] = (round(best, 4), best_p)
    return out


def _family_of(s: dict[str, Any]) -> str | None:
    return FAMILY_OF_CATEGORY.get(s.get("category", ""))


def unexplained(words: list[str], skill_ids: list[str]) -> float:
    """Share (by weight) of the prompt's meaning words that none of these skills' synonyms explain."""
    phrases, weights = _index()
    vocab = {t for sid in skill_ids for p in phrases.get(sid, []) for t in p}
    ws = [w for w in words if w not in FILLER and not NUMERIC.fullmatch(w)]
    total = sum(_weight(w, weights) for w in ws)
    if total <= 0:
        return 0.0
    miss = sum(_weight(w, weights) for w in ws if max((v for t, v in _near(w).items() if t in vocab), default=0.0) < 0.8)
    return miss / total


def _effects_at(ctx: dict[str, Any], t: float | None) -> list[dict[str, Any]]:
    fx = [f for f in (ctx.get("effects_present_at_time") or []) if isinstance(f, dict)]
    if t is None:
        return fx
    return [f for f in fx if float(f.get("start", t)) - 0.05 <= t <= float(f.get("end", t)) + 0.05]


def _when(sid: str, t: float | None, ctx: dict[str, Any], s: dict[str, Any]) -> dict[str, Any] | None:
    """Where a skill goes when the user points at a moment (None: the whole video / the skill decides)."""
    if t is None:
        return None
    modes = s.get("time_modes") or []
    if sid == "restore_normal":
        fx = _effects_at(ctx, t)
        a = min((float(f["start"]) for f in fx if "start" in f), default=t)
        b = max((float(f["end"]) for f in fx if "end" in f), default=t + WINDOW_S)
        return {"mode": "between_times", "start": round(max(0.0, a), 3), "end": round(max(b, a + 0.2), 3)}
    if "at_time" in modes:
        return {"mode": "at_time", "at": round(t, 3)}
    if "between_times" in modes:
        end = t + WINDOW_S
        if ctx.get("duration"):
            end = min(end, float(ctx["duration"]))
        return {"mode": "between_times", "start": round(t, 3), "end": round(end, 3)}
    return None


def label(sid: str, when: dict[str, Any] | None, ctx: dict[str, Any], params: dict[str, Any] | None = None) -> str:
    """Plain Hinglish words for a choice chip."""
    s = spec.load().get(sid, {})
    at = (f"{when['at']:.1f}s par " if when and when.get("mode") == "at_time" else
          f"{when['start']:.1f}s par " if when and "start" in when else "")
    if sid == "restore_normal":
        names = sorted({str(f.get("label") or f.get("type")) for f in _effects_at(ctx, ctx.get("_t"))})
        what = f" ({', '.join(names[:2])} hatega)" if names else ""
        return f"Yaha ka effect hata ke normal karo{what}"[:68]
    fixed = {
        "flash": f"{at}white flash (0.3 sec)",
        "fade_white": f"{at}white me fade",
        "brighten_to_white": f"{at}screen bright / white karo",
        "white_screen_card": f"{at}1 sec safed screen",
    }
    if sid in fixed:
        return fixed[sid][:68]
    name = s.get("name_hi") or s.get("name") or sid
    return f"{at}{name}"[:68]


def resolve(prompt: str, context: dict[str, Any] | None = None) -> Resolution:
    ctx = dict(context or {})
    specs = spec.load()
    words = canonical_words(prompt)
    t = ctx.get("marker_time", ctx.get("playhead"))
    t = float(t) if t is not None else None
    deictic = bool(DEICTIC & set(words)) or "is jagah" in " ".join(words)
    point = t if (t is not None and (deictic or ctx.get("comment", True))) else None
    ctx["_t"] = point
    trace: dict[str, Any] = {"words": words, "time": point}

    # 1. the exact matcher: a clear request stays exactly what it was
    from .parse import parse

    exact = parse(prompt)
    trace["exact"] = {"calls": [c["id"] for c in exact["calls"]], "unknown": [u["text"] for u in exact["unknown"]],
                      "negated": exact["negated"]}
    present = _effects_at(ctx, point)
    calls_in = exact["calls"]
    if any(c["id"] == "add_music" for c in calls_in) and any(
            (c.get("params") or {}).get("what") == "music" for c in calls_in if c["id"] != "add_music"):
        # "music ki awaaz kam karo": the music is what is changed, not something to add
        exact = {**exact, "calls": [c for c in calls_in if c["id"] != "add_music"]}
    if any(c["id"] == "restore_normal" for c in exact["calls"]):
        # "yaha zoom hata ke normal karo": the other skills named are WHAT to take off, not new effects
        named = [c["id"] for c in exact["calls"] if c["id"] != "restore_normal"]
        fams = {_family_of(specs[x]) for x in named} - {None}
        rc = next(c for c in exact["calls"] if c["id"] == "restore_normal")
        if len(fams) == 1:
            rc = {**rc, "params": {**rc.get("params", {}), "what": fams.pop()}}
        exact = {**exact, "calls": [rc]}
    exact_ids = [c["id"] for c in exact["calls"]]
    # "ye black white hatao yaha se" with that effect on screen: take it off (restore), not add it again
    on_screen = {w for f in present for w in canonical_words(f"{f.get('label', '')} {f.get('type', '')}")} - FILLER
    removing = bool(REMOVE_WORDS & set(words)) and bool(present) and (
        any(specs[x]["category"] in EFFECT_CATEGORIES for x in exact_ids)
        or bool(on_screen & set(words)) or bool({"effect", "filter"} & set(words)))
    restore_said = bool(RESTORE_WORDS & set(words)) or "jaisa tha" in " ".join(words) or removing
    # a clear request is applied as it is — unless it also says "like it was / normal" and the matcher did not read
    # that part, or leaves too many of the prompt's meaning words unexplained: then the readings are ranked
    trace["unexplained"] = round(unexplained(words, exact_ids), 3) if exact_ids else None
    clear = (bool(exact["calls"]) and not exact["unknown"] and unexplained(words, exact_ids) < UNEXPLAINED_MAX
             and not (restore_said and "restore_normal" not in exact_ids))
    if clear:
        calls = []
        for c in exact["calls"]:
            if point is not None and not c.get("time"):
                c = {**c, "time": _when(c["id"], point, ctx, specs[c["id"]])}
            calls.append(c)
        first = calls[0]
        choice = {"id": first["id"], "params": first.get("params", {}), "time": first.get("time"), "score": 1.0,
                  "calls": calls, "label": " + ".join(label(c["id"], c.get("time"), ctx) for c in calls)[:68]}
        return Resolution([choice], "apply", trace)

    # 2. weighted token scores
    scores = {k: v[0] for k, v in score_skills(words).items()}
    trace["matched"] = {k: v for k, v in sorted(score_skills(words).items(), key=lambda kv: -kv[1][0])[:6]}
    for sid in exact_ids:  # what the exact matcher read is a strong candidate
        scores[sid] = max(scores.get(sid, 0.0), 0.75)
    for neg in exact["negated"]:
        scores.pop(neg, None)  # "zoom mat lagao" never offers zoom
    if QUOTED.search(prompt) and "text_overlay" in specs:
        # words in quotes are almost always text to put on screen ("'Nice' word dikhao")
        scores["text_overlay"] = max(scores.get("text_overlay", 0.0), 0.5) + 0.3

    # 3. context evidence
    if "restore_normal" in specs:
        r = scores.get("restore_normal", 0.0)
        if restore_said and present:
            r = max(r, 0.6) + 0.3  # "normal jaisa tha" + something is there to take off
        elif present and r > 0:
            r += 0.15
        elif point is not None and ctx.get("effects_present_at_time") is not None and not present:
            r *= 0.35  # nothing is on screen there to restore
        elif not present:
            r *= 0.6
        if r > 0:
            scores["restore_normal"] = min(r, 1.0)
    # a tie inside the white family is broken by how common the reading is
    for k, sid in enumerate(WHITE_FAMILY):
        if sid in scores:
            scores[sid] = scores[sid] + 0.01 * (len(WHITE_FAMILY) - k)
    for sid, n in (ctx.get("learned") or {}).items():  # this user picked it for these same words before
        if sid in scores or sid in specs:
            scores[sid] = scores.get(sid, 0.3) + 0.12 * min(int(n), 3)
    if restore_said and present and "restore_normal" in scores:
        # "…normal jaisa tha" while an effect IS there: taking it off is the likeliest reading; the other readings
        # stay as choices (a close margin → the user picks with one tap)
        others = max((v for k, v in scores.items() if k != "restore_normal"), default=0.0)
        scores["restore_normal"] = max(scores["restore_normal"], others + 0.02)
    trace["scores"] = {k: round(v, 3) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:6]}

    ranked = sorted(scores, key=lambda k: -scores[k])[:3]
    if len(ranked) < 3:
        # never an empty answer ("yaha whitish kar do" scored nothing): fill with the nearest skills to the words
        from .parse import nearest

        for n in nearest(prompt):
            if len(ranked) >= 3:
                break
            if n["id"] not in ranked and n["id"] not in exact["negated"]:
                ranked.append(n["id"])
                scores.setdefault(n["id"], 0.0)
    choices = []
    for sid in ranked:
        when = _when(sid, point, ctx, specs[sid])
        call = {"id": sid, "params": {}, "time": when}
        choices.append({"id": sid, "params": {}, "time": when, "score": round(min(scores[sid], 1.0), 3),
                        "calls": [call], "label": label(sid, when, ctx)})
    top = choices[0]["score"] if choices else 0.0
    second = choices[1]["score"] if len(choices) > 1 else 0.0
    trace["margin"] = round(top - second, 3)
    if top >= APPLY_MIN and top - second >= MARGIN:
        return Resolution(choices[:1], "apply", trace)
    if top >= CHOOSE_MIN:
        return Resolution(choices, "choose", trace)
    return Resolution(choices, "unknown", trace)


def context_from_plan(plan: Any, t: float | None) -> dict[str, Any]:
    """What is on screen at output second t of a saved plan: effects (with their shot's span), graphics, stickers,
    the whole-video colour grade — the evidence for "normal jaisa tha" (sent by the API, so the app need not)."""
    ctx: dict[str, Any] = {"duration": round(plan.total_duration(), 3)}
    if t is None:
        return ctx
    ctx["marker_time"] = round(float(t), 3)
    tl = plan.timeline()
    shot = next((e for e in tl if e.start - 1e-3 <= t < e.end + 1e-3), None)
    present: list[dict[str, Any]] = []
    for e in plan.effects:
        if e.target == -1 and shot is not None:
            present.append({"type": e.type, "label": e.type, "start": round(shot.start, 3), "end": round(shot.end, 3)})
        elif shot is not None and e.target == shot.index:
            present.append({"type": e.type, "label": e.type, "start": round(shot.start, 3), "end": round(shot.end, 3)})
    for g in plan.graphics:
        if g.start - 0.05 <= t <= g.end + 0.05:
            present.append({"type": g.kind, "label": f"{g.kind} graphic", "start": g.start, "end": g.end})
    for st in plan.stickers:
        if st.start - 0.05 <= t <= st.end + 0.05:
            present.append({"type": "sticker", "label": f"sticker {st.emoji}", "start": st.start, "end": st.end})
    if plan.color.preset != "none" and shot is not None:
        present.append({"type": "color_preset", "label": f"{plan.color.preset} colour",
                        "start": round(shot.start, 3), "end": round(shot.end, 3)})
    ctx["effects_present_at_time"] = present
    return ctx


def warm() -> None:
    """Build the index once (about 2 s on a laptop) — called in the background when the server starts."""
    _index()
    _vocab_by_len()
    resolve("zoom karo", {})
