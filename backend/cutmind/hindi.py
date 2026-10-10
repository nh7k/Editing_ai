"""Devanagari Hindi → Hinglish (roman letters, the way people type Hindi on a phone: "mere paas studio mein bhi
hai"). Rule-based, no model: captions read like Indian reels and the sticker words ("gulab", "ped") match.

Long vowels are written short ("gulab", not "gulaab") except a few common words, and the inherent "a" at the end
of a word is dropped (राम → ram), which is how Hinglish is usually written."""

from __future__ import annotations

import re

VIRAMA, NUKTA = "्", "़"
CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f",
}
NUKTA_OF = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f"}
VOWELS = {"अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o",
          "औ": "au", "ऑ": "o"}
SIGNS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e",
         "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o"}
NASAL = {"ं": "n", "ँ": "n"}  # anusvara / chandrabindu
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
# the way these are usually typed (the rules alone give "pas", "hain"→"hain" is fine, "mein"…)
COMMON = {"पास": "paas", "में": "mein", "मैं": "main", "हैं": "hain", "है": "hai", "नहीं": "nahi", "यहाँ": "yahan",
          "यहां": "yahan", "वहाँ": "wahan", "क्या": "kya", "आप": "aap", "आपको": "aapko", "बात": "baat", "चाय": "chai",
          "और": "aur", "भी": "bhi", "तो": "to", "हाँ": "haan", "हां": "haan", "ठीक": "theek", "दोस्तों": "doston"}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def is_hindi(text: str) -> bool:
    return bool(DEVANAGARI.search(text))


def romanize_word(w: str) -> str:
    if w in COMMON:
        return COMMON[w]
    # syllables: [consonant letters, vowel, inherent?]  (inherent = the unwritten "a" after a consonant)
    syl: list[list] = []
    i, n = 0, len(w)
    while i < n:
        c = w[i]
        if c in CONS or c in NUKTA_OF:
            nukta = i + 1 < n and w[i + 1] == NUKTA
            base = NUKTA_OF[c] if nukta else CONS.get(c, "")
            i += 2 if nukta else 1
            if i < n and w[i] == VIRAMA:  # half letter: joins the next consonant
                syl.append([base, "", False])
                i += 1
            elif i < n and w[i] in SIGNS:
                syl.append([base, SIGNS[w[i]], False])
                i += 1
            else:
                syl.append([base, "a", True])
        elif c in VOWELS:
            syl.append(["", VOWELS[c], False])
            i += 1
        elif c in NASAL or c == "ः":
            if syl:
                syl[-1][1] += "n" if c in NASAL else "h"
            i += 1
        elif c in DIGITS:
            syl.append([DIGITS[c], "", False])
            i += 1
        else:
            i += 1
    # schwa deletion: the final inherent "a" goes (ram), unless it follows a half letter (samudra)
    if syl and syl[-1][2] and syl[-1][1] == "a" and not (len(syl) > 1 and syl[-2][1] == ""):
        syl[-1][1] = ""
    # ... and a middle one between two sounded syllables goes too (rahata → rahta, kitana → kitna)
    k = len(syl) - 2
    while k >= 1:
        if syl[k][2] and syl[k][1] == "a" and syl[k - 1][1] and syl[k + 1][1]:
            syl[k][1] = ""
            k -= 2
        else:
            k -= 1
    return "".join(c + v for c, v, _ in syl) or w


def romanize(text: str) -> str:
    """A whole line: Devanagari words become Hinglish, everything else stays."""
    return re.sub(r"[ऀ-ॿ]+", lambda m: romanize_word(m.group(0)), text)
