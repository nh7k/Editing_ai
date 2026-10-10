"""Before the rules read a message: Devanagari → Hinglish, obvious typos of editing words fixed, and a coverage
score that tells the router when the rules only half-understood a clause (then the planner LLM is asked).

All deterministic, no model: "गाना हटा दो" → "gana hata do"; "captins lagao" → "captions lagao";
"blak and wite" → "black and white". Only words that are close to a word of the editor's own vocabulary (the
command catalog, effect names, colours) are changed — Hinglish words the parser knows are never "corrected".
"""

from __future__ import annotations

import difflib
import re
from functools import lru_cache
from pathlib import Path

from .hindi import is_hindi, romanize

ROOT = Path(__file__).resolve().parent
_WORD = re.compile(r"[a-z][a-z']+")
STOP = {"bhai", "yaar", "please", "pls", "plz", "ok", "okay", "ji", "na", "sir", "bro", "aur", "and", "also", "bhi",
        "edit", "video", "kar", "karo", "kardo", "de", "do", "isko", "isme", "mera", "meri", "mere", "this", "the",
        "a", "an", "it", "ko", "ka", "ki", "ke", "hai", "h", "haan", "thoda", "thode", "thodi", "zara", "sa", "si",
        "se", "me", "mein", "main", "my", "to", "of", "for", "with", "is", "are", "be", "make", "bana", "banao",
        "chahiye", "wala", "wali", "wale", "ho", "hona", "jaisa", "jaise", "like", "in", "on", "at", "par", "pe",
        "ye", "yeh", "vo", "wo", "us", "uska", "uski", "iska", "iski", "jo", "kuch", "sab", "bhut", "bahut", "very",
        "just", "only", "sirf", "ab", "abhi", "now", "please", "kr", "ek", "one", "that", "lag", "raha", "rahi",
        "lagao", "laga", "daal", "daalo", "dalo", "add", "dena", "dijiye", "kijiye", "please"}


@lru_cache(maxsize=1)
def editing_words() -> set[str]:
    """The editor's own words (typo targets): the command catalog phrases + allowed values + effect names."""
    import yaml

    from .llm_provider import VALUES, catalog

    words: set[str] = set()
    for c in catalog():
        words |= set(_WORD.findall(c["say"].lower()))
    for v in VALUES.values():
        for e in v.get("enum") or []:
            words |= set(_WORD.findall(str(e).lower()))
    fx = ROOT.parent / "video_editing_knowledge" / "prompt_library.yaml"
    for p in yaml.safe_load(fx.read_text(encoding="utf-8"))["prompts"]:
        words |= set(_WORD.findall(p["prompt"].lower()))
    words |= {"captions", "subtitles", "music", "black", "white", "slow", "motion", "silence", "silences", "filler",
              "transition", "transitions", "zoom", "glitch", "cinematic", "colour", "color", "colours", "colors", "audio", "voice", "remove",
              "gaana", "gana", "gaane", "song", "sec", "second", "seconds", "clip", "clips", "text", "likh", "likho",
              "slow", "fast", "reel", "insta", "instagram", "youtube", "shorts", "captions", "title", "music", "warm",
              "saath", "ending", "end", "start", "shot", "shots", "part", "effect", "effects", "filter", "sticker",
              "stickers", "emoji", "speed", "length", "duration", "minute", "minutes", "pehla", "pehli", "dusra",
              "teesra", "aakhri", "last", "first", "second", "reference", "sample", "uploaded"}
    return {w for w in words if len(w) >= 3} - STOP


# Hinglish words people use for edits that must never be "corrected" into an English look-alike
HINGLISH = {"teer", "tir", "gola", "dabba", "peela", "peele", "peeli", "laal", "lal", "neela", "neele", "hara", "hare", "kala", "kaala", "kaale",
            "safed", "gulabi", "sunehra", "garam", "thanda", "thandi", "dheema", "dheemi", "dheere", "tez", "tezz",
            "jaldi", "bada", "badi", "bade", "chhota", "choti", "chhoti", "lamba", "lambi", "hata", "hatao", "nikal",
            "nikalo", "kaat", "kaato", "lagao", "lagado", "daalo", "dikhao", "awaaz", "awaz", "aawaz", "gaana",
            "gaane", "gana", "rang", "pehle", "baad", "shuru", "shuruat", "aakhri", "akhri", "last", "pehla", "dusra",
            "zyada", "kam", "achha", "accha", "mast", "bekaar", "faltu", "boring", "saaf", "likh", "likho", "naya"}


@lru_cache(maxsize=1)
def known_words() -> set[str]:
    """Every word the rule parser has a pattern for (literal letters inside its regexes) + the editing words."""
    src = ""
    for f in ("intent.py", "fx_catalog.py", "text_styles.py", "phrasebook.py", "memory.py", "moment.py", "stickers.py"):
        p = ROOT / f
        if p.exists():
            # only the raw-string regexes (r"…"), not comments / docstrings (they name typos as examples)
            src += " ".join(re.findall(r"""\br["']([^"'\n]*)["']""", p.read_text(encoding="utf-8"))).lower() + " "
    lang = ROOT.parent / "video_editing_knowledge" / "language.yaml"
    src += lang.read_text(encoding="utf-8").lower()
    return {w for w in _WORD.findall(src) if len(w) >= 3} | editing_words() | STOP | HINGLISH


COMMON_ENGLISH = {"cute", "nice", "good", "cool", "love", "lovely", "great", "best", "worst", "bad", "fine", "funny",
                  "happy", "sad", "beautiful", "awesome", "amazing", "pretty", "sweet", "smart", "bright", "dark",
                  "light", "night", "right", "write", "wrote", "white", "while", "whole", "photo", "photos", "friend",
                  "friends", "family", "trip", "today", "tomorrow", "please", "thanks", "thank", "hello", "weather",
                  # real words the typo fixer turned into editor words ("crop to fill" → "filler")
                  "fill", "fills", "filled", "filter", "filters", "tight", "stack", "shot", "shots", "fit", "slide",
                  "flip", "stop", "top", "pop", "loop", "drop", "mix", "fix", "fade", "made", "make"}


def fix_typos(text: str) -> str:
    """Words that are no known word but very close to an editing word get that word ("captins" → captions)."""
    known, targets = known_words(), sorted(editing_words())

    def one(m: re.Match[str]) -> str:
        w = m.group(0)
        low = w.lower()
        if low in known or len(low) < 4:
            return w
        if low in COMMON_ENGLISH:
            return w
        hit = difflib.get_close_matches(low, targets, n=1, cutoff=0.8)
        # a typo drops or swaps letters ("captins", "blak", "silense"); a SHORTER target means a real word would be
        # cut down ("cute" → "cut" broke "mera kutta cute hai")
        return hit[0] if hit and len(hit[0]) >= len(low) else w

    return re.sub(r"[A-Za-z][A-Za-z']+", one, text)


# English editing words written in Devanagari, as the romaniser spells them ("सेकंड" → sekand → second)
DEVANAGARI_ENGLISH = {
    "sekand": "second", "sekend": "second", "sekind": "second", "kaipshan": "captions", "kepshan": "captions",
    "kaipshans": "captions", "sabtaitil": "subtitles", "slo": "slow", "fast": "fast", "phast": "fast",
    "vidiyo": "video", "vidio": "video", "myujik": "music", "myuzik": "music", "mujik": "music", "jum": "zoom",
    "zum": "zoom", "ephekt": "effect", "efekt": "effect", "kalar": "color", "kalr": "color", "blaik": "black",
    "vait": "white", "vhait": "white", "rīl": "reel", "ril": "reel", "insta": "insta", "tekst": "text",
    "taitil": "title", "trānzishan": "transition", "tranzishan": "transition", "sinematik": "cinematic",
    "vorm": "warm", "varm": "warm", "baiground": "background", "gliich": "glitch", "glich": "glitch",
    "minat": "minute", "minit": "minute", "iphekta": "effect", "iphekt": "effect", "ephekta": "effect", "slomoshan": "slow motion", "moshan": "motion", "shots": "shots",
}


# spelling variants people type for the same word (→ the form the rules know)
VARIANTS = {
    "bohot": "bahut", "boht": "bahut", "bht": "bahut", "bhut": "bahut", "bahot": "bahut", "bhot": "bahut",
    "jldi": "jaldi", "jaldii": "jaldi", "acha": "accha", "achha": "accha", "achaa": "accha", "nhi": "nahi",
    "nai": "nahi", "nahin": "nahi", "kr": "kar", "krdo": "kar do", "kardo": "kar do", "krde": "kar de",
    "kardo.": "kar do", "jyada": "zyada", "jada": "zyada", "zada": "zyada", "jiyada": "zyada", "dhire": "dheere",
    "dhere": "dheere", "tej": "tez", "tezz": "tez", "thora": "thoda", "thodasa": "thoda sa", "vdo": "video",
    "vedio": "video", "vidoe": "video", "vidio": "video", "secs": "sec", "sekand": "second", "sekend": "second",
    "gane": "gaane", "lgao": "lagao", "lga": "laga", "lgado": "laga do", "dalo": "daalo", "hatado": "hata do",
    "htado": "hata do", "hta": "hata", "bnado": "bana do", "bnao": "banao", "bna": "bana", "bnade": "bana de",
}
# number words → digits ("das second" → "10 second", "aadha minute" → "30 second")
NUMBERS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "che": 6, "saat": 7,
    "aath": 8, "nau": 9, "das": 10, "dus": 10, "gyarah": 11, "barah": 12, "baarah": 12, "pandrah": 15, "pandra": 15,
    "bees": 20, "bis": 20, "pachees": 25, "pachchis": 25, "tees": 30, "tis": 30, "chalees": 40, "chalis": 40,
    "pachaas": 50, "pachas": 50, "saath": 60,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60,
}
_UNIT = r"(sec|secs|second|seconds|minute|minutes|min|mins)"


def _numbers(text: str) -> str:
    t = re.sub(r"\b(aadha|aadhe|half a?)\s+(minute|min)\b", "30 second", text, flags=re.I)
    t = re.sub(r"\b(dedh|derh)\s+(minute|min)\b", "90 second", t, flags=re.I)
    t = re.sub(r"\b(dhai|dhaai|dhaayi)\s+(minute|min)\b", "150 second", t, flags=re.I)
    # only a number word right before a time unit ("do" alone is "do it" / "kar do")
    return re.sub(r"\b(" + "|".join(sorted(NUMBERS, key=len, reverse=True)) + r")\s+(?=" + _UNIT + r"\b)",
                  lambda m: f"{NUMBERS[m.group(1).lower()]} ", t, flags=re.I)


def normalize(text: str) -> str:
    text = re.sub(r"[A-Za-z]+\.?", lambda m: VARIANTS.get(m.group(0).lower(), m.group(0)), text)
    text = _numbers(text)
    if is_hindi(text):
        text = romanize(text)
        text = re.sub(r"[a-z]+", lambda m: DEVANAGARI_ENGLISH.get(m.group(0), m.group(0)), text)
        text = re.sub(r"\bblack (end|aind|and|n) white\b", "black and white", text)  # "ब्लैक एंड व्हाइट"
    return fix_typos(text)


# edit verbs / magnitude words that do not name WHAT to change (they are understood together with one that does)
CORE = {"hata", "hatao", "nikal", "nikalo", "kaat", "kaato", "lagao", "lagado", "daalo", "dikhao", "karo", "bada",
        "badi", "bade", "chhota", "choti", "chhoti", "lamba", "lambi", "tez", "kam", "zyada", "remove", "add", "make",
        "more", "less", "bit", "little", "mat", "nahi", "don't", "dont", "no"}


def coverage(clause: str) -> float:
    """Share of the clause's content words that are the editor's OWN words (command phrases, values, effect names).
    Low = the rules may have half-understood it ("gaane ki awaaz dheemi" read as "upbeat music") → ask the model."""
    words = [w for w in _WORD.findall(clause.lower()) if w not in STOP and w not in CORE and len(w) >= 3]
    if not words:
        return 1.0
    vocab = editing_words()
    return sum(1 for w in words if w in vocab) / len(words)
