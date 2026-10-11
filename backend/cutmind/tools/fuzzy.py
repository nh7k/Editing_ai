"""Forgiving word matching for Hinglish prompts (own code, no library).

A noob writes "yhn whight krdo nomal jasia tha". Three layers make those words meet the skills' synonyms:
1. VARIANTS: known spellings of the same word → one canonical form (yhn → yaha, krdo → kar do, nomal → normal).
2. Devanagari → Roman (a small own table), so "यहाँ सफ़ेद" meets "yaha safed".
3. sim(): equal / same phonetic key (vowels dropped, aspirates merged) / close edit distance.

Low-information words ("kar", "do", "tha", "ka") get weight 0 in the scorer (FILLER), so they can never decide a
ranking — that was the bug of docs/INTENT_FAILURE_REVIEW.md.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# spelling variant → canonical (multi-word canonicals are fine: "krdo" → "kar do")
VARIANTS: dict[str, str] = {
    # here / this place (deictic: bound to the marker / playhead)
    "yahan": "yaha", "yhn": "yaha", "yha": "yaha", "yahaan": "yaha", "yahaa": "yaha", "idhar": "yaha", "idhr": "yaha",
    "yahi": "yaha", "yahin": "yaha", "yhi": "yaha", "here": "yaha", "ithe": "yaha", "is jagah": "yaha",
    "isi jagah": "yaha", "is jgh": "yaha", "is moment": "yaha", "is point": "yaha", "is waqt": "yaha",
    # common Hinglish spellings of English words
    "foto": "photo", "fotu": "photo", "photu": "photo", "fotos": "photos",
    # do it
    "krdo": "kar do", "kardo": "kar do", "karde": "kar do", "krde": "kar do", "kar de": "kar do", "kardena": "kar do",
    "krna": "karo", "karna": "karo", "kro": "karo", "krdena": "kar do", "kariye": "karo", "kijiye": "karo", "kr": "kar",
    # like / as it was
    "jasia": "jaisa", "jaise": "jaisa", "jaisi": "jaisa", "jese": "jaisa", "jesa": "jaisa", "jasa": "jaisa",
    "jaysa": "jaisa", "jaissa": "jaisa", "jeisa": "jaisa", "jaisaa": "jaisa", "jsa": "jaisa", "jaise hi": "jaisa",
    "tha": "tha", "thaa": "tha", "thi": "tha", "the": "tha",
    # normal / original / before
    "nomal": "normal", "normel": "normal", "norml": "normal", "nrml": "normal", "normaal": "normal", "normall": "normal",
    "noraml": "normal", "nornal": "normal", "orignal": "original", "orginal": "original", "origional": "original",
    "asli": "original", "asal": "original", "real": "original", "phle": "pehle", "pahle": "pehle", "pehele": "pehle",
    "pehla": "pehle", "pehli": "pehle", "vapas": "wapas", "wapis": "wapas", "vapis": "wapas", "waps": "wapas",
    "wps": "wapas", "back": "wapas",
    # colours
    "wite": "white", "whight": "white", "whit": "white", "wht": "white", "whyte": "white", "whte": "white",
    "safed": "white", "safaid": "white", "safeed": "white", "sufaid": "white", "safedi": "white", "sfed": "white",
    "dhawal": "white", "shwet": "white", "kala": "black", "kaala": "black", "blak": "black", "blck": "black",
    "kaali": "black", "kali": "black",
    # brightness
    "brite": "bright", "brigt": "bright", "bryt": "bright", "ujala": "bright", "ujaala": "bright", "roshni": "bright",
    "chamkila": "bright",
    # screen
    "scren": "screen", "skreen": "screen", "screan": "screen", "scrin": "screen", "parda": "screen",
    # remove / undo
    "hatado": "hata do", "htao": "hatao", "hatado ": "hata do", "hata de": "hata do", "nikalo": "hatao",
    "undo": "wapas", "revert": "wapas", "reset": "wapas",
    # same thing, other word (both sides are unified, so a synonym written one way meets the other)
    "nikal": "hatao", "nikaal": "hatao", "nikaalo": "hatao", "uda": "hatao", "udao": "hatao", "hata": "hatao",
    "part": "hissa", "hisse": "hissa", "portion": "hissa", "tukda": "hissa", "tukde": "hissa",
    # spelling only — merging different words that share a meaning ("colour" = "rang", "dheere" = "slow") made one
    # skill swallow its neighbours on the eval ("thanda colour" → colour pop), so concepts stay separate words
    "colours": "colour", "colors": "color", "rangon": "rang",
    "awaz": "awaaz", "aawaz": "awaaz", "avaaz": "awaaz", "aawaaz": "awaaz",
    "gana": "gaana", "musik": "music", "dhire": "dheere",
}

# words that carry no meaning for picking a skill (weight 0)
FILLER = frozenset("""
kar karo do de dena ho hai hain tha the thi ka ki ke ko me mein main mai se pe par aur or ek sa si
na naa to toh bhi bas ab abhi please plz pls bhai yaar ji haan han ye yeh wo woh vo is us iska uska isko
usko a an the it this that is are was be make do please just very ekdum bilkul thoda zara wala wali wale
mera meri mere apna apni kuch sab sabko ise use ne hi ha hn yaha jagah
""".split())

# Devanagari → Roman (own table; enough for editing words: vowels, consonants, matras, nukta forms)
_DV_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "w", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f",
}
_DV_VOWEL = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
             "ऋ": "ri"}
_DV_MATRA = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri"}
_VIRAMA, _NUKTA = "्", "़"
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def translit(text: str) -> str:
    """Devanagari → plain Roman (schwa kept inside a word, dropped at its end: सफ़ेद → safed, कर → kar)."""
    if not _DEVANAGARI.search(text):
        return text
    s = unicodedata.normalize("NFC", text)
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if i + 1 < len(s) and s[i + 1] == _NUKTA and ch + _NUKTA in _DV_CONS:
            ch, i = ch + _NUKTA, i + 1
        if ch in _DV_CONS:
            out.append(_DV_CONS[ch])
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt in _DV_MATRA:
                out.append(_DV_MATRA[nxt])
                i += 1
            elif nxt == _VIRAMA:
                i += 1
            elif nxt and (nxt in _DV_CONS or _DEVANAGARI.match(nxt)) and nxt not in "ंँः":
                out.append("a")  # inherent vowel inside the word
            elif nxt and nxt in "ंँ":
                out.append("a")
        elif ch in _DV_VOWEL:
            out.append(_DV_VOWEL[ch])
        elif ch in "ंँ":
            out.append("n")
        elif ch in _DV_MATRA or ch in (_VIRAMA, _NUKTA, "ः"):
            pass
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _collapse(w: str) -> str:
    return re.sub(r"(.)\1{2,}", r"\1\1", w)  # "whiteee" → "whitee", "pleeeease" → "pleease"


def canonical_words(text: str) -> list[str]:
    """Lower-case Roman words with every known variant unified (multi-word variants first)."""
    t = translit(text).lower()
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # "1.5x" stays one word; other dots split words
    t = re.sub(r"[^\w\s.]", " ", t)
    words = [_collapse(w) for w in t.split()]
    out: list[str] = []
    i = 0
    while i < len(words):
        two = f"{words[i]} {words[i + 1]}" if i + 1 < len(words) else ""
        if two in VARIANTS:
            out += VARIANTS[two].split()
            i += 2
            continue
        w = words[i]
        w = VARIANTS.get(w, VARIANTS.get(re.sub(r"(.)\1+", r"\1", w), w))
        if w == words[i] and len(w) >= 4 and w.isalpha():  # not a known variant: a generated misspelling?
            from .variants import variant_map

            g = variant_map().get(w)
            if g:
                w = VARIANTS.get(g, g)
        out += w.split()
        i += 1
    return out


@lru_cache(maxsize=20000)
def phonetic(w: str) -> str:
    """A key that survives Hinglish spelling: aspirates merged (kh→k, sh→s, ph→f), w/v and z/j unified, vowels
    and doubled letters dropped (keep the first letter). jaisa / jasia / jesa → 'js'; normal / nomal → 'nml'."""
    w = w.lower()
    w = w.replace("ght", "t").replace("ph", "f").replace("ck", "k").replace("q", "k").replace("x", "ks")
    w = re.sub(r"([bcdgjklmnprstwy])h", r"\1", w)  # bh dh gh kh ph sh th → b d g k p s t
    w = w.replace("v", "w").replace("z", "j").replace("c", "k")
    head, rest = w[:1], w[1:]
    rest = re.sub(r"[aeiouy]", "", rest)
    rest = rest.replace("r", "") if len(rest) > 2 else rest  # nrml / nml ("normal" said without the r)
    return re.sub(r"(.)\1+", r"\1", head + rest)


def _edit(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@lru_cache(maxsize=200000)
def sim(a: str, b: str) -> float:
    """How alike two canonical words are: 1 equal, 0.9 same phonetic key, else edit-distance based (0 below 0.75)."""
    if a == b:
        return 1.0
    if len(a) < 3 or len(b) < 3:
        return 0.0  # short words must match exactly ("do" is not "de")
    d = _edit(a, b)
    key = phonetic(a)
    # a 2-letter key is too loose on its own ("white" / "wait" are both "wt"): then the spelling must be close too
    # the same key is not enough when the spellings are far apart ("fillers" / "flash" are both "fls")
    if key == phonetic(b) and (len(key) >= 3 or d <= 1) and d <= max(2, max(len(a), len(b)) // 3):
        return 0.9
    r = 1.0 - d / max(len(a), len(b))
    return r if r >= 0.8 and d <= 2 else 0.0
