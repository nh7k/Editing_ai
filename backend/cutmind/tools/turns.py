"""Turns that are not a new skill request (docs/UNDERSTANDING_REVIEW.md, Phase 4).

non_edit()   greetings, thanks, questions about the app, emoji-only → an answer, never an edit
relative()   "aur thoda", "kam karo", "dobara", "isko hata do" right after an edit → the last edit again,
             with its strength moved in the asked direction (inside the skill's own min / max), or undone
"""

from __future__ import annotations

import re
from typing import Any

from . import spec
from .fuzzy import canonical_words

GREETINGS = {"hi", "hello", "hey", "namaste", "namaskar", "good", "morning", "evening", "night", "bye", "thanks",
             "thank", "you", "shukriya", "dhanyavad", "dhanyawad", "ok", "okay", "accha", "acha", "achha", "theek",
             "thik", "hai", "nice", "wow", "badhiya", "mast", "super", "great", "cool", "haan", "han", "hmm", "bhai",
             "yaar", "ji", "sir", "bro", "bas", "itna", "kya", "hua", "sahi", "perfect", "done", "gn", "gm",
             "please", "plz"}
QUESTION = {"kaise", "how", "what", "kitna", "kitne", "samjhao", "batao", "help", "madad", "kaun", "why", "kyun",
            "kyu", "explain", "guide", "sikhao", "maddad"}
DO = re.compile(r"\b(karo|kar do|kardo|krdo|kar de|lagao|laga do|daalo|dalo|daal do|hatao|hata do|banao|bana do|"
                r"add|make|remove|apply|put|chahiye|chaiye|set|change|badlo|badal do|ghumao|kaato|kaat do)\b")

UP = {"aur", "more", "zyada", "jyada", "increase", "badhao", "full", "double", "bit", "zor", "tez", "strong"}
DOWN = {"kam", "halka", "halki", "less", "reduce", "aadha", "down", "dheema", "dheere", "light", "weak"}
SAME = {"dobara", "again", "phir", "wahi", "same", "repeat"}
REMOVE = {"hatao", "hata", "undo", "remove", "nikal", "nikalo", "wapas"}
POINTERS = {"isko", "ise", "ye", "yeh", "wala", "pichla", "last", "effect", "one", "it", "this", "abhi"}
PARAM_ORDER = ("amount", "intensity", "strength", "factor", "radius", "gain_db", "scale", "opacity", "duration")
HELP_TEXT = ("Main aapki video edit karta hoon — jo chahiye seedha likho, jaise \"music lagao\", \"30 sec ka karo\", "
             "\"yaha zoom\". Timeline pe kisi second pe click karke us pal ke liye bhi likh sakte ho.")


def non_edit(prompt: str, exact_calls: list[dict[str, Any]]) -> str | None:
    """An answer when the message is not an edit (None when it is, or might be, one)."""
    text = prompt.strip()
    if not text:
        return "Kya karna hai likho — jaise \"music lagao\" ya \"black and white karo\"."
    if not re.search(r"[A-Za-zऀ-ॿ0-9]", text):  # emoji / symbols only
        return "😊 Kya badalna hai? Likho, jaise \"yaha flash lagao\"."
    words = canonical_words(text)
    imperative = bool(DO.search(" ".join(words)))
    if not exact_calls and words and all(w in GREETINGS for w in words):
        return "🙏 " + HELP_TEXT
    if (QUESTION & set(words) or text.rstrip().endswith("?")) and not imperative:
        topic = f" ({', '.join(c['id'].replace('_', ' ') for c in exact_calls[:2])})" if exact_calls else ""
        return f"Sawaal samjha{topic}. " + HELP_TEXT + " Kuch badalna ho to seedha likho, main kar dunga."
    return None


def _param(sid: str) -> tuple[str, dict[str, Any]] | None:
    params = spec.load()[sid].get("params", {})
    num = {k: v for k, v in params.items() if v.get("type") in ("number", "integer")}
    for k in PARAM_ORDER:
        if k in num:
            return k, num[k]
    return next(iter(num.items()), None)


def relative(prompt: str, recent: list[dict[str, Any]] | None, exact_ids: list[str]) -> dict[str, Any] | None:
    """{"kind": up|down|same|remove, "call": the adjusted call, "said": words for the user} or None."""
    if not recent:
        return None
    words = canonical_words(prompt)
    meaning = [w for w in words if w not in {"karo", "kar", "do", "de", "please", "plz", "na", "yaar", "sa", "si", "thoda",
                                             "ab", "bhai", "ek", "baar", "ho", "gaya", "itna", "nahi", "bilkul", "a"}]
    last = recent[-1]
    pointing = bool(REMOVE & set(words)) and bool(POINTERS & set(words)) and not re.search(r"\d", prompt)
    if pointing and exact_ids == ["delete_segment"]:
        exact_ids = []  # "isko hata do" with no times: the last edit, not "cut a part" (which needs a when)
    if meaning and all(w in UP | DOWN | SAME | REMOVE | POINTERS for w in meaning):
        exact_ids = []  # only "how much" words ("thoda kam"): about the last edit, even if "kam" matched a skill
    if exact_ids and exact_ids != [last["id"]]:
        return None  # a new skill was named: not about the last edit
    if len(meaning) > 5:
        return None
    s = set(words)
    joined = " ".join(words)
    if REMOVE & s and (POINTERS & s or len(meaning) <= 2):
        return {"kind": "remove", "call": {**last, "remove": True}, "said": f"pichla edit ({last['id']}) hataya"}
    if SAME & s or "ek baar aur" in joined:
        return {"kind": "same", "call": dict(last), "said": f"{last['id']} dobara"}
    down = bool(DOWN & s) or "itna nahi" in joined or "zyada ho gaya" in joined or "tone it down" in prompt.lower()
    up = not down and bool(UP & s)
    if not (up or down):
        return None
    p = _param(last["id"])
    if p is None:
        return None
    key, meta = p
    lo, hi = float(meta.get("min", 0.0)), float(meta.get("max", 1.0))
    cur = (last.get("params") or {}).get(key, meta.get("default"))
    if cur is None:
        return None
    cur = float(cur)
    if key == "gain_db":
        new = cur + (6.0 if "double" in s else 3.0) if up else cur - 3.0
    elif "full" in s:
        new = hi
    elif "double" in s:
        new = cur * 2
    elif "aadha" in s:
        new = cur * 0.5
    elif up:
        new = cur * 1.5 if cur > 0 else cur + (hi - lo) * 0.2
    elif "bilkul" in s:
        new = lo + (cur - lo) * 0.25
    else:
        new = cur * 0.6 if cur > 0 else cur - (hi - lo) * 0.2
    new = max(lo, min(hi, new))
    if meta.get("type") == "integer":
        new = int(round(new))
    else:
        new = round(new, 3)
    if new == cur:
        edge = "sabse zyada" if up else "sabse kam"
        return {"kind": "same", "call": dict(last), "said": f"{last['id']} pehle se {edge} pe hai ({key} {cur:g})"}
    call = {**last, "params": {**(last.get("params") or {}), key: new}}
    return {"kind": "up" if up else "down", "call": call,
            "said": f"{last['id']} {key} {cur:g} → {new:g} ({'zyada' if up else 'kam'})"}
