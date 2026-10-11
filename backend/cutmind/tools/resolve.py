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
# act = apply the best guess AND show the alternatives (docs/UNDERSTANDING_REVIEW.md: act, show, undo). Not on a long
# video when the readings are close: a wrong render there costs minutes (eval/results/perf.json)
# dev sweep (docs/UNDERSTANDING_EVAL.md): 0.7 / 0.5 → 34 right acts, 7 wrong (all with chips), 1 unsupported acted on;
# 0.6 unexplained acted 47 right but 11 wrong and 4 unsupported
ACT_MIN, ACT_UNEXPLAINED, LONG_VIDEO_S = 0.70, 0.5, 120.0
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
# "take away" verbs: meaningful (remove, not add) but they do not say WHAT
REMOVE_VERBS = {"hatao", "hata", "remove", "delete", "nikal", "kaat", "kaato", "kat", "cut", "uda"}
WEAK_SYNONYM = 0.55  # a synonym with no word saying WHAT ("hatao do", "30 sec ka bana do") is weak evidence
QUOTED = re.compile(r"['\"‘“][^'\"’”]{1,80}['\"’”]")


@dataclass
class Resolution:
    """decision: apply (clearly understood) | act (best guess applied, alternatives shown) | choose (one tap needed)
    | unknown (nothing close: nearest skills from the user's words) | partial (the understood parts applied, the
    rest as choices) | non_edit (an answer, no edit) | undo (take the last edit back)."""

    choices: list[dict[str, Any]]
    decision: str
    trace: dict[str, Any] = field(default_factory=dict)
    apply: list[dict[str, Any]] = field(default_factory=list)   # calls that run without a tap
    unclear: list[dict[str, Any]] = field(default_factory=list)  # parts not done: {text, supported, choices}
    reply: str | None = None                                     # words for the user (non_edit, undo, disclosure)

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "choices": self.choices, "apply": self.apply, "unclear": self.unclear,
                "reply": self.reply, "trace": self.trace}


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


@lru_cache(maxsize=1)
def _phrase_table() -> dict[str, list[tuple[list[tuple[str, float]], float, bool, str]]]:
    """skill → [(meaning words with weights, total weight, says WHAT, text)] — computed once, not per prompt."""
    phrases, weights = _index()
    table: dict[str, list[tuple[list[tuple[str, float]], float, bool, str]]] = {}
    for sid, ps in phrases.items():
        rows = []
        for p in ps:
            ws = [(t, x) for t in p if (x := _weight(t, weights)) > 0]
            total = sum(x for _, x in ws)
            if total > 0:
                rows.append((ws, total, any(t not in VERBS and t not in REMOVE_VERBS for t, _ in ws), " ".join(p)))
        table[sid] = rows
    return table


def score_skills(words: list[str]) -> dict[str, tuple[float, str]]:
    """Every skill's best synonym coverage of the prompt words: {skill: (score 0..1, the synonym that matched)}."""
    prompt = [w for w in words if w not in FILLER and not NUMERIC.fullmatch(w)]  # numbers are read by the parser
    out: dict[str, tuple[float, str]] = {}
    if not prompt:
        return out
    best_of: dict[str, float] = {}  # synonym word → how well some prompt word matches it
    for q in prompt:
        for t, v in _near(q).items():
            if v > best_of.get(t, 0.0):
                best_of[t] = v
    for sid, rows in _phrase_table().items():
        best, best_p = 0.0, ""
        for ws, total, says_what, text in rows:
            got = sum(x * best_of.get(t, 0.0) for t, x in ws)
            if got <= 0:
                continue
            cov = got / total
            if not says_what:
                cov *= WEAK_SYNONYM  # "anime style bana do" matched "30 sec ka bana do" on "bana" alone
            # a synonym that says more (more meaning words) is a slightly better witness than a one-word one
            # (a stronger length penalty was tried and lost: dev top-1 0.887 vs 0.913 — docs/INTENT_EVAL.md)
            sc = cov * (0.85 + 0.15 * min(1.0, total / 6.0))
            if sc > best:
                best, best_p = sc, text
        if best > 0:
            out[sid] = (round(best, 4), best_p)
    return out


def _names_a_present_effect(words: list[str], present: list[dict[str, Any]], specs: dict[str, Any]) -> bool:
    """The words name an effect skill of the same family as an effect on screen ("black white" + a colour grade
    there) — so "hatao" means take THAT off, whatever label the effect carries."""
    from .b_restore import _family

    fams = {_family(str(f.get("type", ""))) for f in present}
    sc = score_skills(words)
    return any(v[0] >= 0.8 and specs[k]["category"] in EFFECT_CATEGORIES and _family_of(specs[k]) in fams
               for k, v in sc.items() if k in specs)


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
        where = "Yaha ka" if ctx.get("_t") is not None else "Poori video ka"
        return f"{where} effect hata ke normal karo{what}"[:68]
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


def _ranked(prompt: str, words: list[str], exact: dict[str, Any], ctx: dict[str, Any], point: float | None,
            restore_said: bool, present: list[dict[str, Any]], trace: dict[str, Any]
            ) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Up to 3 readings of (part of) a prompt, best first, each ready to run."""
    specs = spec.load()
    exact_ids = [c["id"] for c in exact["calls"]]
    # weighted token scores
    scored = score_skills(words)
    scores = {k: v[0] for k, v in scored.items()}
    trace["matched"] = {k: v for k, v in sorted(scored.items(), key=lambda kv: -kv[1][0])[:6]}
    for sid in exact_ids:  # what the exact matcher read is a strong candidate
        scores[sid] = max(scores.get(sid, 0.0), 0.75)
    for neg in exact["negated"]:
        scores.pop(neg, None)  # "zoom mat lagao" never offers zoom
    if QUOTED.search(prompt) and "text_overlay" in specs:
        # words in quotes are almost always text to put on screen ("'Nice' word dikhao")
        scores["text_overlay"] = max(scores.get("text_overlay", 0.0), 0.5) + 0.3

    # context evidence
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
    for sid, n in (ctx.get("learned") or {}).items():  # this user's reactions to these same words (signed, decayed)
        w = max(-3.0, min(3.0, float(n)))
        if sid in scores or (sid in specs and w > 0):
            scores[sid] = scores.get(sid, 0.3) + 0.12 * w
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
    return choices, scores


def _timed(c: dict[str, Any], point: float | None, ctx: dict[str, Any]) -> dict[str, Any]:
    if point is not None and not c.get("time"):
        return {**c, "time": _when(c["id"], point, ctx, spec.load()[c["id"]])}
    return c


def _not_available(text: str) -> list[str]:
    try:
        from ..skill_registry import named_later

        return list(named_later(text))
    except Exception:  # noqa: BLE001
        return []


def _meaning(words: list[str]) -> list[str]:
    return [w for w in words if w not in FILLER and not NUMERIC.fullmatch(w)]


def _partial(prompt: str, exact: dict[str, Any], ctx: dict[str, Any], point: float | None,
             present: list[dict[str, Any]], trace: dict[str, Any]) -> Resolution | None:
    from .parse import clauses, parse

    # split the spelling-fixed text: "blak and wite" must meet "black and white" (kept together by the splitter)
    # (commas survive: each comma-separated piece is fixed on its own, then joined again)
    fixed = ", ".join(" ".join(canonical_words(piece)) for piece in re.split(r"[,;]", prompt) if piece.strip())
    parts = clauses(fixed if not QUOTED.search(prompt) else prompt)
    if len(parts) < 2:
        return None
    # one skill whose own name has an "and" in it ("forward and backward" = boomerang, "black and white"): one clause
    best = max(score_skills(canonical_words(prompt)).values(), default=(0.0, ""))
    if best[0] >= 0.85 and re.search(r"\b(and|aur|n)\b", best[1]):
        return None
    known: list[str] = []
    unclear: list[dict[str, Any]] = []
    for text in parts:
        pw = canonical_words(text)
        if not _meaning(pw):
            continue  # "2 se 4 sec": a setting of the clause before it
        pr = parse(text)
        ids = [c["id"] for c in pr["calls"]]
        if pr["negated"] and not ids:
            continue  # "zoom mat lagao": understood (nothing to do)
        if ids and not pr["unknown"] and unexplained(pw, ids) < UNEXPLAINED_MAX:
            known += [i for i in ids if i not in known]
            continue
        sub = {"calls": [], "unknown": [], "negated": exact["negated"]}
        sub_choices, _ = _ranked(text, pw, sub, ctx, point, False, present, {})
        later = _not_available(text)
        supported = (not later and bool(sub_choices) and sub_choices[0]["score"] >= ACT_MIN
                     and unexplained(pw, [sub_choices[0]["id"]]) < ACT_UNEXPLAINED)
        unclear.append({"text": text.strip(), "supported": supported, "not_available": later,
                        "choices": [c for c in sub_choices if c["id"] not in known]})
    if not known or not unclear:
        return None
    # the calls come from the whole message (it keeps settings said in other clauses: times, numbers)
    calls = [c for c in exact["calls"] if c["id"] in known]
    calls += [c for t in parts for c in parse(t)["calls"] if c["id"] in known and c["id"] not in {x["id"] for x in calls}]
    calls = [_timed(c, point, ctx) for c in calls]
    first = calls[0]
    choice = {"id": first["id"], "params": first.get("params", {}), "time": first.get("time"), "score": 1.0,
              "calls": calls, "label": " + ".join(label(c["id"], c.get("time"), ctx) for c in calls)[:68]}
    trace["turn"] = "partial"
    trace["clauses"] = {"known": known, "unclear": [u["text"] for u in unclear]}
    undone = ", ".join(f'"{u["text"]}"' for u in unclear)
    return Resolution([choice], "partial", trace, apply=calls, unclear=unclear,
                      reply=f"Kiya: {choice['label']}. Ye nahi ho paaya: {undone} — neeche ke options dekho.")


MAX_CHARS = 1000  # a 5,000-character message took 8.5 s to read; the first 1,000 characters are understood


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def clean_context(context: Any) -> dict[str, Any]:
    """The context is data from the app: wrong types are dropped, never trusted (a corrupt field must not crash)."""
    raw = context if isinstance(context, dict) else {}
    specs = spec.load()
    ctx: dict[str, Any] = {}
    for k in ("marker_time", "playhead", "duration"):
        if (v := _num(raw.get(k))) is not None and v >= 0:
            ctx[k] = v
    if "comment" in raw:
        ctx["comment"] = bool(raw["comment"])
    fx = raw.get("effects_present_at_time")
    if isinstance(fx, list):
        ctx["effects_present_at_time"] = [
            {"type": str(f.get("type", ""))[:40], "label": str(f.get("label", f.get("type", "")))[:60],
             **({"start": _num(f["start"])} if _num(f.get("start")) is not None else {}),
             **({"end": _num(f["end"])} if _num(f.get("end")) is not None else {})}
            for f in fx[:50] if isinstance(f, dict)]
    rec = raw.get("recent_edits")
    if isinstance(rec, list):
        ctx["recent_edits"] = [{"id": r["id"], "params": r.get("params") if isinstance(r.get("params"), dict) else {},
                                "time": r.get("time") if isinstance(r.get("time"), dict) else None}
                               for r in rec[-10:] if isinstance(r, dict) and r.get("id") in specs]
    learned = raw.get("learned")
    if isinstance(learned, dict):
        ctx["learned"] = {str(k): v for k, v in ((k, _num(v)) for k, v in learned.items()) if v is not None}
    return ctx


def resolve(prompt: str, context: dict[str, Any] | None = None) -> Resolution:
    ctx = clean_context(context)
    prompt = str(prompt or "")
    clipped = len(prompt) > MAX_CHARS
    prompt = prompt[:MAX_CHARS]
    specs = spec.load()
    words = canonical_words(prompt)
    t = ctx.get("marker_time", ctx.get("playhead"))
    t = float(t) if t is not None else None
    deictic = bool(DEICTIC & set(words)) or "is jagah" in " ".join(words)
    point = t if (t is not None and (deictic or ctx.get("comment", True))) else None
    ctx["_t"] = point
    trace: dict[str, Any] = {"words": words, "time": point}
    if clipped:
        trace["clipped_to_chars"] = MAX_CHARS  # said to the user by the API

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
    from .turns import non_edit, relative

    # 0. not an edit at all (greeting, thanks, a question about the app, emoji only): an answer, never an edit
    reply = non_edit(prompt, exact["calls"])
    if reply is not None:
        trace["turn"] = "non_edit"
        return Resolution([], "non_edit", trace, reply=reply)
    # 0b. about the last edit: "aur thoda", "kam karo", "dobara", "isko hata do"
    rel = relative(prompt, ctx.get("recent_edits"), exact_ids)
    if rel is not None:
        trace["turn"] = f"relative:{rel['kind']}"
        c = rel["call"]
        choice = {"id": c["id"], "params": c.get("params", {}), "time": c.get("time"), "score": 1.0, "calls": [c],
                  "label": rel["said"][:68]}
        return Resolution([choice], "undo" if rel["kind"] == "remove" else "apply", trace, apply=[c], reply=rel["said"])
    # "ye black white hatao yaha se" with that effect on screen: take it off (restore), not add it again
    on_screen = {w for f in present for w in canonical_words(f"{f.get('label', '')} {f.get('type', '')}")} - FILLER
    # "ye black white HATAO" — the parser reads "hatao" as "not", so the named effect may sit in `negated`
    removing = bool(REMOVE_WORDS & set(words)) and bool(present) and (
        any(specs[x]["category"] in EFFECT_CATEGORIES for x in exact_ids + list(exact["negated"]))
        or bool(on_screen & set(words)) or bool({"effect", "filter"} & set(words))
        or _names_a_present_effect(words, present, specs))
    restore_said = bool(RESTORE_WORDS & set(words)) or "jaisa tha" in " ".join(words) or removing
    # a clear request is applied as it is — unless it also says "like it was / normal" and the matcher did not read
    # that part, or leaves too many of the prompt's meaning words unexplained: then the readings are ranked
    # words of a skill the user said NOT to use ("zoom mat lagao") are understood too
    said = exact_ids + list(exact["negated"])
    trace["unexplained"] = round(unexplained(words, said), 3) if exact_ids else None
    # a reading this user undid / rephrased for these same words is not applied blindly again
    disliked = any(float((ctx.get("learned") or {}).get(i, 0.0)) < 0 for i in exact_ids)
    # "purple video ko normal kar do" with a look on the video: the other words only say WHICH thing to take off
    restore_only = exact_ids == ["restore_normal"] and bool(present) and not exact["unknown"] and not disliked
    clear = restore_only or (bool(exact["calls"]) and not exact["unknown"] and unexplained(words, said) < UNEXPLAINED_MAX
             and not disliked
             and not (restore_said and "restore_normal" not in exact_ids))
    # partial: some parts are clear, some are not ("warm karo, captions lagao aur mere chehre ko jawan dikhao") — each
    # clause is judged on its own: the clear ones run, every unclear one gets its own choices. One unknown part never
    # sinks the whole message (before: the whole message became one "pick one" question)
    whole_clear = restore_only or (
        bool(exact["calls"]) and not exact["unknown"] and not (restore_said and "restore_normal" not in exact_ids)
        and unexplained(words, exact_ids + list(exact["negated"])) < UNEXPLAINED_MAX)
    # the whole message clearly understood ("blak and wite kro" = black and white) is never cut into clauses —
    # splitting on "and" turned it into "blak" + "wite kro" → a white flash
    if not whole_clear and not (restore_said and "restore_normal" not in exact_ids):
        part = _partial(prompt, exact, ctx, point, present, trace)
        if part is not None:
            return part
    if clear:
        calls = []
        for c in exact["calls"]:
            if point is not None and not c.get("time"):
                c = {**c, "time": _when(c["id"], point, ctx, specs[c["id"]])}
            calls.append(c)
        first = calls[0]
        choice = {"id": first["id"], "params": first.get("params", {}), "time": first.get("time"), "score": 1.0,
                  "calls": calls, "label": " + ".join(label(c["id"], c.get("time"), ctx) for c in calls)[:68]}
        return Resolution([choice], "apply", trace, apply=calls)

    choices, scores = _ranked(prompt, words, exact, ctx, point, restore_said, present, trace)
    top = choices[0]["score"] if choices else 0.0
    second = choices[1]["score"] if len(choices) > 1 else 0.0
    top_unexplained = unexplained(words, [choices[0]["id"]]) if choices else 1.0
    if choices and choices[0]["id"] == "restore_normal" and restore_said and present:
        top_unexplained = 0.0  # the effect on screen explains the words ("ye black white hatao" + a grade there)
    later = _not_available(prompt)
    trace.update({"margin": round(top - second, 3), "top_unexplained": round(top_unexplained, 3),
                  "not_available": later})
    long_video = float(ctx.get("duration") or 0.0) > LONG_VIDEO_S
    if later and not exact_ids:  # "4k upscale", "face swap": never apply something else instead
        return Resolution(choices, "unknown", trace,
                          reply=f"'{later[0]}' abhi available nahi hai. Ye paas wale options hain:")
    if top >= APPLY_MIN and top - second >= MARGIN and top_unexplained < UNEXPLAINED_MAX:
        return Resolution(choices[:1], "apply", trace, apply=list(choices[0]["calls"]))
    if top >= ACT_MIN and top_unexplained < ACT_UNEXPLAINED and not long_video:
        # act, show, undo: the best guess runs, the other readings stay one tap away
        return Resolution(choices, "act", trace, apply=list(choices[0]["calls"]),
                          reply=f"Maine ye kiya: {choices[0]['label']}. Galat ho to neeche se badlo ya ↶ Undo.")
    if top >= CHOOSE_MIN:
        # not "this is not supported": the share of unknown words overlaps completely between unsupported requests and
        # oddly worded supported ones (dev: 0.45-0.88 for both — docs/UNDERSTANDING_EVAL.md), so say only the truth
        return Resolution(choices, "choose", trace,
                          reply="Pakka nahi samjha — inme se koi chahiye? Na ho to apne shabdon me dobara likho:")
    return Resolution(choices, "unknown", trace,
                      reply="Exact skill nahi mila — ye sabse paas wale hain (aapke shabdon se):")


def context_from_plan(plan: Any, t: float | None) -> dict[str, Any]:
    """What is on screen at output second t of a saved plan: effects (with their shot's span), graphics, stickers,
    the whole-video colour grade — the evidence for "normal jaisa tha" (sent by the API, so the app need not)."""
    total = round(plan.total_duration(), 3)
    ctx: dict[str, Any] = {"duration": total}
    if t is None:
        # no moment: what covers the WHOLE video ("purple video ko normal kar do" on a styled edit) — without this
        # the chat saw nothing to restore and the words "purple video" sank the clear "normal kar do"
        whole: list[dict[str, Any]] = [{"type": e.type, "label": e.type.replace("_", " "), "start": 0.0, "end": total}
                                       for e in plan.effects if e.target == -1]
        c = plan.color
        if c.preset != "none" or (c.contrast, c.saturation, c.warmth, c.brightness) != (1.0, 1.0, 0.0, 0.0):
            whole.append({"type": "color_preset", "label": f"{c.preset} colour" if c.preset != "none" else "colour grade",
                          "start": 0.0, "end": total})
        if plan.style or plan.overlays:
            whole.append({"type": "style", "label": f"{plan.style or 'graphic'} look", "start": 0.0, "end": total})
        ctx["effects_present_at_time"] = whole
        return ctx
    ctx["marker_time"] = round(float(t), 3)
    tl = plan.timeline()
    shot = next((e for e in tl if e.start - 1e-3 <= t < e.end + 1e-3), None)
    present: list[dict[str, Any]] = []

    def name(e: Any) -> str:  # the words a user would use for it ("black and white", not "grade")
        look = str((e.params or {}).get("look") or "")
        if look in ("grayscale", "bw", "mono", "noir", "film_bw") or e.type in ("mono", "film_bw"):
            return "black and white"
        if e.type == "grade":
            p = e.params or {}
            return ("warm colour" if float(p.get("warmth", 0) or 0) > 0 else "cool colour" if float(p.get("warmth", 0) or 0) < 0
                    else f"{look} look" if look else "colour grade")
        return e.type.replace("_", " ")
    for e in plan.effects:
        if e.target == -1 and shot is not None:
            present.append({"type": e.type, "label": name(e), "start": round(shot.start, 3), "end": round(shot.end, 3)})
        elif shot is not None and e.target == shot.index:
            present.append({"type": e.type, "label": name(e), "start": round(shot.start, 3), "end": round(shot.end, 3)})
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
    _phrase_table()
    from .variants import variant_map

    variant_map()
    resolve("zoom karo", {})
