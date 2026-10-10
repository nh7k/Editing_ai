"""Prompt → Tier 1 tool calls with parameters. Deterministic (no model): synonyms + extractors + time phrases.

    parse("thoda zoom karo 2 se 5 sec, aur gaana lagao") →
      calls:   [{"id": "zoom_in", "params": {"amount": 0.06}, "time": {"mode": "between_times", "start": 2, "end": 5}},
                {"id": "add_music", "params": {}, "time": None}]
      negated: skills the user said NOT to do ("zoom mat lagao")
      unknown: clauses nothing matched, each with the 3 nearest skills
      assumed: words read as a magnitude / time ("thoda" = half the default amount)

Matching runs on the raw text (Devanagari synonyms) AND the normalized text (Hinglish / typos / number words),
longest synonym first, so "zoom transition" is the transition and not the zoom.
"""

from __future__ import annotations

import difflib
import re
from functools import lru_cache
from typing import Any

from ..prenormalize import normalize
from . import spec

NEG = re.compile(r"(?:^|\s)(?:mat|nahi|nahin|na|mt|nhi|bina|no|not|don'?t|dont|without|never|band karo|"
                 r"rehne do|chahiye nahi|nahi chahiye)(?:\s|$)")
NEG_BEFORE = re.compile(r"(?:\bno|\bwithout|\bbina|\bdon'?t|\bdont|\bnever|\bmat)\s+(?:\w+\s+){0,1}$")
UNIT = r"(?:s|sec|secs|second|seconds|sekand|sekend|सेकंड|se?c)"
NUM = r"(\d+(?:\.\d+)?)"
FRACTIONS = {"aadha": 0.5, "adha": 0.5, "aadhe": 0.5, "dedh": 1.5, "dhai": 2.5, "dhaai": 2.5, "sawa": 1.25,
             "half a": 0.5, "half": 0.5, "one and a half": 1.5}
ORDINALS = {"pehla": 1, "pehle": 1, "pahla": 1, "first": 1, "1st": 1, "dusra": 2, "doosra": 2, "dusre": 2,
            "doosre": 2, "2nd": 2, "teesra": 3, "tisra": 3, "teesre": 3, "third": 3, "3rd": 3, "chautha": 4,
            "chotha": 4, "fourth": 4, "4th": 4, "paanchva": 5, "fifth": 5, "5th": 5}
COLORS = {"white": "#FFFFFF", "safed": "#FFFFFF", "black": "#000000", "kala": "#000000", "kaala": "#000000",
          "red": "#FF3B30", "laal": "#FF3B30", "lal": "#FF3B30", "yellow": "#FFD60A", "peela": "#FFD60A",
          "pila": "#FFD60A", "green": "#34C759", "hara": "#34C759", "blue": "#0A84FF", "neela": "#0A84FF",
          "nila": "#0A84FF", "pink": "#FF2D92", "gulabi": "#FF2D92", "orange": "#FF9500", "narangi": "#FF9500",
          "purple": "#AF52DE", "baingani": "#AF52DE", "gold": "#FFC300", "sunehra": "#FFC300", "golden": "#FFC300",
          "cyan": "#32ADE6", "aasmani": "#32ADE6"}
DIRECTIONS = {"left": "left", "baaye": "left", "baayen": "left", "bayen": "left", "right": "right", "daaye": "right",
              "daayen": "right", "dayen": "right", "up": "up", "upar": "up", "oopar": "up", "down": "down",
              "neeche": "down", "niche": "down"}
PLATFORMS = {"youtube shorts": "youtube_shorts", "yt shorts": "youtube_shorts", "instagram": "instagram_reels", "insta": "instagram_reels", "reel": "instagram_reels",
             "reels": "instagram_reels", "shorts": "youtube_shorts", "youtube short": "youtube_shorts",
             "whatsapp": "whatsapp_status", "status": "whatsapp_status", "youtube": "youtube",
             "linkedin": "linkedin", "tiktok": "instagram_reels"}
SMALL = r"(?:thoda|thodi|thode|halka|halki|halke|slightly|a bit|a little|little|zara|kam se kam|subtle|light)"
BIG = r"(?:bahut|bohot|bht|zyada|jyada|very|a lot|full|strong|extreme|heavy|tagda|ekdum|zabardast|max)"


def _num(s: str) -> float:
    return float(s)


def _fractions(t: str) -> str:
    """aadha / dedh / dhai + a unit → digits (prenormalize does whole numbers only)."""
    for w, v in sorted(FRACTIONS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{w}\s+(?={UNIT}\b|minute|min\b)", f"{v:g} ", t)
    return t


# ---- extractors: (clause text, skill spec) → value or None ---------------------------------------------------
def x_time_range(t: str) -> tuple[float, float] | None:
    m = re.search(rf"(?:from\s+)?{NUM}\s*{UNIT}?\s*(?:se|to|-|–|till|until|and|aur)\s*{NUM}\s*{UNIT}", t) or \
        re.search(rf"(?:from\s+)?{NUM}\s*{UNIT}\s*(?:se|to|-|–|till|until)\s*{NUM}\b", t) or \
        re.search(rf"\b{NUM}\s*(?:se|to|-|–)\s*{NUM}\s*(?:tak|ke beech|ke bich)", t)
    if m:
        a, b = _num(m.group(1)), _num(m.group(2))
        return (a, b) if b > a else None
    m = re.search(rf"(?:first|starting|pehle|shuru ke|shuru ka|shuruaat ke|start ke)\s+{NUM}\s*{UNIT}", t)
    if m:
        return 0.0, _num(m.group(1))
    return None


def x_time_point(t: str) -> float | None:
    m = re.search(rf"(?:\bat|\bon|\bfrom)\s+{NUM}\s*{UNIT}", t) or re.search(rf"\b{NUM}\s*{UNIT}\s*(?:pe|par|pr|per)\b", t) \
        or re.search(rf"\b{NUM}\s*{UNIT}\s*(?:ke baad|after)", t)
    return _num(m.group(1)) if m else None


def x_seconds(t: str) -> float | None:
    if x_time_range(t):
        rest = re.sub(rf"(?:from\s+)?{NUM}\s*{UNIT}?\s*(?:se|to|-|–|till|until)\s*{NUM}\s*{UNIT}?", " ", t)
    else:
        rest = t
    rest = re.sub(rf"(?:\bat|\bon)\s+{NUM}\s*{UNIT}|\b{NUM}\s*{UNIT}\s*(?:pe|par|pr|per)\b", " ", rest)
    m = re.search(rf"\b{NUM}\s*{UNIT}\b", rest)
    return _num(m.group(1)) if m else None


def x_duration(t: str) -> float | None:
    m = re.search(rf"\b{NUM}\s*(?:minute|minutes|min|mins|minit)\b", t)
    if m:
        return _num(m.group(1)) * 60
    if x_time_range(t):
        return None
    # "10 sec ka" / "15 seconds long" is the total; "2 second ke shots" is not
    m = re.search(rf"\b{NUM}\s*{UNIT}\s*(?:ka|ki|long|video|reel|clip|total|tak ka|me fit|mein fit|me|mein)\b", t)
    if m:
        return _num(m.group(1))
    nums = re.findall(rf"\b{NUM}\s*{UNIT}\b", t)
    if len(nums) == 1 and not re.search(rf"\b{NUM}\s*{UNIT}\s*(?:ke|pe|par|ka shot)", t):
        return _num(nums[0])
    m = re.search(rf"\b(?:to|under|within)\s+{NUM}\s*{UNIT}", t)
    return _num(m.group(1)) if m else None


def x_count(t: str) -> int | None:
    m = re.search(r"\b(\d+)\s*(?:best|achhe|achche|top|moments?|highlights?|parts?|hisse|clips?|words?|shabd|times|baar|bar)\b", t) or \
        re.search(r"\btop\s+(\d+)", t)
    return int(m.group(1)) if m else None


def x_shot_number(t: str) -> int | None:
    m = re.search(r"\b(?:shot|clip|video|scene|part)\s*(?:no\.?|number|#)?\s*(\d+)\b", t) or \
        re.search(r"\b(\d+)(?:st|nd|rd|th)?\s*(?:wala\s+)?(?:shot|clip|video|scene)\b", t)
    if m:
        return int(m.group(1))
    for w, n in ORDINALS.items():
        if re.search(rf"\b{w}\s+(?:wala\s+)?(?:shot|clip|video|scene|part|hissa)", t):
            return n
    if re.search(r"\b(?:second)\s+(?:shot|clip|video|scene)\b", t):
        return 2
    if re.search(r"\b(?:last|aakhri|akhri|aakhiri)\s+(?:wala\s+)?(?:shot|clip|video|scene)\b", t):
        return -1
    return None


def x_order_list(t: str) -> list[int] | None:
    sep = r"\s*(?:,|phir|then|fir|aur|uske baad)?\s*"
    m = re.search(rf"\b(\d+){sep}(\d+)\b(?:{sep}(\d+)\b)?(?:{sep}(\d+)\b)?", t)
    if not m:
        return None
    nums = [int(g) for g in m.groups() if g]
    if len(nums) >= 2 and len(set(nums)) == len(nums) and max(nums) <= 50 and not re.search(UNIT, t[m.end():m.end() + 8]):
        return nums
    return None


def x_move(t: str) -> tuple[int, int] | None:
    n = x_shot_number(t)
    if n is None:
        m = re.search(r"\b(\d+)\s*wala\b", t)
        n = int(m.group(1)) if m else None
    if n is None:
        return None
    if re.search(r"\b(?:first|pehle|pahle|shuru me|start me|aage)\b", t.split(str(n))[-1] if str(n) in t else t):
        return n, 1
    if re.search(r"\b(?:last me|end me|aakhir me|peeche|at the end)\b", t):
        return n, 999
    return None


def x_db(t: str) -> float | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*db\b", t)
    return float(m.group(1)) if m else None


def x_multiplier(t: str) -> float | None:
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*x\b", t) or re.search(r"\bx\s*(\d+(?:\.\d+)?)\b", t)
    if m:
        return float(m.group(1))
    if re.search(r"\b(?:double|do guna|dugna|2 guna|twice)\b", t):
        return 2.0
    if re.search(r"\b(?:triple|teen guna|3 guna)\b", t):
        return 3.0
    if re.search(r"\b(?:half|aadhi|aadha|adhi)\s*(?:speed|raftaar|tez)?\b", t):
        return 0.5
    if re.search(r"\bquarter\b|\bchauthai\b", t):
        return 0.25
    return None


def x_percent(t: str) -> float | None:
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:%|percent|pratishat)", t)
    return float(m.group(1)) / 100 if m else None


def x_direction(t: str) -> str | None:
    for w, d in DIRECTIONS.items():
        if re.search(rf"\b{w}\b", t):
            return d
    return None


def x_color(t: str) -> str | None:
    m = re.search(r"#[0-9a-fA-F]{6}\b", t)
    if m:
        return m.group(0).upper()
    t = re.sub(r"\b(?:black|kala|kaala)\s*(?:and|&|aur|n)?\s*(?:white|safed)\b", " ", t)
    found = [(mm.start(), c) for c, hx in COLORS.items() for mm in re.finditer(rf"\b{c}\b", t)]
    if not found:
        return None
    # "black se white" / "black to white": the LAST colour named is the new one
    return COLORS[sorted(found)[-1][1]]


def x_quoted(t: str) -> str | None:
    m = re.search(r"['\"‘“]([^'\"’”]{1,120})['\"’”]", t)
    return m.group(1).strip() if m else None


def x_platform(t: str) -> str | None:
    for w, p in sorted(PLATFORMS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{w}\b", t):
            return p
    return None


def x_languages(t: str) -> list[str] | None:
    out = [code for code, pat in (("hi", r"hindi|हिंदी"), ("en", r"english|angrezi")) if re.search(pat, t)]
    return out or None


def x_intro_outro(t: str) -> str | None:
    intro = re.search(r"\b(?:intro|shuru|shuruat|shuruaat|start|opening|beginning)\b", t)
    outro = re.search(r"\b(?:outro|end|ant|last|aakhir|closing|ending)\b", t)
    if intro and outro:
        return "both"
    return "intro" if intro else "outro" if outro else None


def x_position(t: str) -> str | None:
    for pat, pos in ((r"top right|upar daaye|upar right", "top_right"), (r"top left|upar baaye|upar left", "top_left"),
                     (r"bottom right|neeche daaye|niche right|neeche right", "bottom_right"),
                     (r"bottom left|neeche baaye|niche left|neeche left", "bottom_left"),
                     (r"\btop\b|\bupar\b", "top"), (r"\bbottom\b|\bneeche\b|\bniche\b", "bottom"),
                     (r"\bcenter\b|\bcentre\b|\bbeech\b|\bmiddle\b", "center"), (r"\bcorner\b|\bkone\b", "bottom_right")):
        if re.search(pat, t):
            return pos
    return None


DOWN = re.compile(r"\b(?:dark\w*|andhera|andhere|darker|kam\b|ghata\w*|reduce|lower|less|decrease|dim\w*|halka kar|"
                  r"faded?|fade kar|dull|feeka|pheeka|desaturat\w*|soft|nikal)\b")
UP = re.compile(r"\b(?:bright\w*|ujala|roshni|badha\w*|zyada|more|increase|boost|higher|tez|gehra|gehre|"
                r"vivid|colou?rful|punchy|pop)\b")


def x_magnitude(t: str) -> str | None:
    if re.search(rf"\b{BIG}\b", t):
        return "big"
    if re.search(rf"\b{SMALL}\b", t):
        return "small"
    return None


def x_angle(t: str) -> int | None:
    m = re.search(r"\b(90|180|270)\b", t)
    if m:
        return int(m.group(1))
    if re.search(r"upside down|ulta(?! chalao| order)|sir ke bal|180", t):
        return 180
    if re.search(r"\b(?:sideways|left|baaye|anticlockwise|ulti disha)\b", t):
        return 270
    if re.search(r"\b(?:right|daaye|clockwise|seedha|tedha|tircha)\b", t):
        return 90
    return None


def x_flip_axis(t: str) -> str | None:
    if re.search(r"(?:upar neeche|upar niche|vertical(?:ly)?)\s*(?:flip|palat|mirror)|flip vertical", t):
        return "v"
    if re.search(r"\b(?:mirror|flip|aaina|aina|palat|ulta seedha)\b", t):
        return "h"
    return None


def x_fade_where(t: str) -> str | None:
    """Fade between shots, or at the start / end of the video."""
    t = re.sub(r"\b(?:phed|fed|faid|faed)\b", "fade", t)
    t = re.sub(r"\bfade aut\b", "fade out", t)  # "आउट" romanised
    fin = re.search(r"fade\s*in\b|shuru\w* (?:me|mein)\s*(?:\w+\s+)?fade|start (?:me|mein)? ?fade|from black", t)
    fout = re.search(r"fade\s*out\b|(?:end|ant|aakhir|last) (?:me|mein)\s*(?:\w+\s+)?fade|at the end|to black at the end", t)
    if re.search(r"fade in (?:and|aur|&|n)?\s*(?:fade )?out|fade in fade out|in and out", t) or (fin and fout):
        return "start_end"
    if re.search(r"between|beech|shots|clips|cuts|har cut|scene", t):
        return "cuts"
    return "start" if fin else "end" if fout else None


def x_db_signed(t: str) -> float | None:
    """A level change in dB: "+6 dB" / "-3 db", else louder / quieter words (thoda = 3, normal = 6, bahut = 10)."""
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*db\b", t)
    if m:
        v = float(m.group(1))
        down = DOWN.search(t) or re.search(r"\b(?:down|quieter|softer|neeche)\b", t)
        if not m.group(1).startswith(("+", "-")) and down and not UP.search(t):
            v = -v
        return v
    mag = x_magnitude(t)
    size = 3.0 if mag == "small" else 10.0 if mag == "big" else 6.0
    if re.search(r"\b(?:quieter|softer|kam|dheem\w*|halk\w*|lower|down|ghata\w*|reduce|neeche)\b", t):
        return -size
    if re.search(r"\b(?:louder|loud|tez|badha\w*|up|increase|boost|zyada|upar|high)\b", t):
        return size
    return None


def x_what_sound(t: str) -> str | None:
    if re.search(r"\b(?:music|gaan[ae]\w*|song|bgm|background)\b", t):
        return "music"
    if re.search(r"\b(?:voice|bolne|baat|dialogue|speech|meri awaaz|apni awaaz)\b", t):
        return "voice"
    return None


def x_fade_side(t: str) -> str | None:
    t = re.sub(r"\b(?:phed|fed|faed)\b", "fade", t)
    if re.search(r"\bin (?:and|aur|&)? ?(?:fade )?out\b|\bdono\b|\bboth\b|in aur out", t):
        return "both"
    if re.search(r"\bout\b|\bend\b|\bant\b|khatam|last|aakhir|ending", t):
        return "out"
    if re.search(r"\bin\b|\bstart\b|shuru|aaye\b|begin", t):
        return "in"
    return None


def x_nth(t: str) -> int | None:
    """"every 2nd beat" / "har doosre beat" → 2."""
    m = re.search(r"(?:every|har)\s+(\d+)(?:st|nd|rd|th)?\s+(?:beat|cut|shot)", t)
    if m:
        return int(m.group(1))
    for w, n in ORDINALS.items():
        if re.search(rf"\b(?:every|har)\s+{w}\s+(?:beat|cut|shot)", t):
            return n
    return None


def x_text_size(t: str) -> int | None:
    m = re.search(r"\b(\d{2,3})\s*(?:px|pt|size)\b", t)
    if m:
        return int(m.group(1))
    if re.search(r"\b(?:bad[ae]|bigger|larger|large|big|mota|moti)\b", t):
        return 72 if not re.search(r"\bbahut\b|very|huge", t) else 96
    if re.search(r"\b(?:chhot[ae]|smaller|small|patla|tiny)\b", t):
        return 36
    return None


def x_region(t: str) -> str | None:
    if re.search(r"\b(?:face|chehr[ae]|chehra|muh|mooh)\b", t):
        return "face"
    return x_position(t)


def x_mirror_axis(t: str) -> str | None:
    if re.search(r"kaleido|chaar taraf|char taraf|four.?way|sab taraf", t):
        return "both"
    if re.search(r"upar neeche|upar niche|vertical|top.{0,5}bottom", t):
        return "v"
    return None


EMOJI_WORDS = {"🔥": r"\b(?:fire|aag|lit)\b", "❤️": r"\b(?:heart|dil|love|pyaar)\b", "😂": r"\b(?:laugh\w*|hasi|haso|lol|funny)\b",
               "🌹": r"\b(?:rose|gulab)\b", "🎉": r"\b(?:party|celebrat\w*|jashn)\b", "⭐": r"\b(?:star|tara)\b",
               "👍": r"\b(?:thumbs?|like)\b", "😍": r"\b(?:wow|crush)\b"}


def x_emoji(t: str) -> str | None:
    m = re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?", t)
    if m:
        return m.group(0)
    for e, pat in EMOJI_WORDS.items():
        if re.search(pat, t):
            return e
    return None


def x_count_from(t: str) -> int | None:
    m = re.search(r"\b(?:from|se)\s+(\d+)\b|\b(\d+)\s+se\b", t) or re.search(r"\b(\d+)\s+\d+\s+1\b", t)
    if m:
        v = int(next(g for g in m.groups() if g))
        return v if 2 <= v <= 10 else None
    return None


def x_lufs(t: str) -> float | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*lufs", t)
    if m:
        v = float(m.group(1))
        return -abs(v)
    if re.search(r"youtube|instagram|insta|reels?|shorts|spotify", t):
        return -14.0
    if re.search(r"podcast|apple", t):
        return -16.0
    return None


def x_ratio_number(t: str) -> float | None:
    m = re.search(r"\b([12]\.\d{1,2})\b", t)
    return float(m.group(1)) if m else None


EXTRACTORS = {
    "angle": x_angle, "flip_axis": x_flip_axis, "ratio_number": x_ratio_number, "fade_where": x_fade_where,
    "db_signed": x_db_signed, "what_sound": x_what_sound, "fade_side": x_fade_side, "lufs": x_lufs, "nth": x_nth, "text_size": x_text_size, "region": x_region, "mirror_axis": x_mirror_axis,
    "emoji": x_emoji, "count_from": x_count_from,
    "time_range_start": lambda t: (x_time_range(t) or (None, None))[0],
    "time_range_end": lambda t: (x_time_range(t) or (None, None))[1],
    "time_point": x_time_point, "seconds": x_seconds, "duration": x_duration, "count": x_count,
    "shot_number": x_shot_number, "order_list": x_order_list,
    "move_from": lambda t: (x_move(t) or (None, None))[0], "move_to": lambda t: (x_move(t) or (None, None))[1],
    "cut_number": lambda t: (int(m.group(1)) if (m := re.search(r"\bcut\s*(\d+)", t)) else None),
    "db": x_db, "multiplier": x_multiplier, "percent": x_percent, "direction": x_direction, "color": x_color,
    "quoted_text": x_quoted, "platform": x_platform, "languages": x_languages, "intro_outro": x_intro_outro,
    "position": x_position, "clip_ref": lambda t: (f"#{n}" if (n := x_shot_number(t)) and n > 0 else None),
}


# ---- time phrases → time mode -----------------------------------------------------------------------------
def x_time(t: str, allowed: list[str], consumed_range: bool) -> tuple[dict[str, Any] | None, list[str]]:
    """The time expression of a clause (if the skill can use it). Returns (time, assumed)."""
    if "intermittent" in allowed and re.search(
            r"beech beech (?:me|mein|main)|bich bich|beech-beech|kabhi kabhi|thodi thodi der|every few seconds|"
            r"from time to time|now and then|bar bar|baar baar|intermittent", t):
        m = re.search(rf"(?:har|every)\s+{NUM}\s*{UNIT}", t)
        return ({"mode": "intermittent", **({"every": _num(m.group(1))} if m else {})}, [])
    if "at_beats" in allowed and re.search(r"\bbeat|\bbeet|\bthap\b|\bdhun pe|on the rhythm|music ke saath", t):
        return {"mode": "at_beats"}, []
    if "on_scene_change" in allowed and re.search(r"(?:har|every|each)\s+(?:cut|scene|transition)|scene change|"
                                                  r"cut pe|cuts pe|on (?:the )?cuts", t):
        return {"mode": "on_scene_change"}, []
    if "on_words" in allowed and re.search(r"jab (?:bole|bolta|bolti|bol raha|bol rahi)|when (?:he|she|i|they) "
                                           r"(?:say|says|said|talk)|on (?:the )?words|har word|har shabd", t):
        q = x_quoted(t)
        return {"mode": "on_words", **({"words": q.lower().split()} if q else {})}, []
    if not consumed_range and "between_times" in allowed:
        r = x_time_range(t)
        if r:
            return {"mode": "between_times", "start": r[0], "end": r[1]}, []
        if re.search(r"\b(?:shuru me|shuru mein|start me|starting me|beginning|at the start|in the start|intro me|"
                     r"shuruat me|shuruaat me|pehle kuch second)\b", t):
            return {"mode": "between_times", "start": 0.0, "end": 3.0}, ["'shuru me' = the first 3 s"]
        if re.search(r"\b(?:end me|ant me|last me|aakhir me|akhir me|at the end|in the end|ending me|khatam hote)\b", t):
            return {"mode": "between_times", "start": -3.0, "end": 0.0}, ["'end me' = the last 3 s"]
    if "segment" in allowed:
        n = x_shot_number(t)
        if n:
            return {"mode": "segment", "index": n - 1 if n > 0 else -1}, []
    if "at_time" in allowed:
        p = x_time_point(t)
        if p is not None:
            return {"mode": "at_time", "at": p}, []
    return None, []


# ---- matching (token level) ----------------------------------------------------------------------------------
def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:&'#%.,\-ऀ-ॿ]", " ", t.lower())).strip()


# one form per word: Hindi verb forms → their stem, spelling variants, English plurals (matching only; the
# extractors read the clause as written)
_VERBS = {
    "hata": "hata|hatao|hatado|hatana|hatayein|hatayen|hatade|hataiye|hatna",
    "nikal": "nikal|nikalo|nikaldo|nikalna|nikaalo|nikaal|nikalde|nikalke",
    "kaat": "kaat|kaato|kaatdo|kaatna|kat|kato|katdo|kaatke|katke",
    "kar": "kar|karo|kardo|karna|kijiye|kariye|karde|karein|karen|kro|krdo|kr|bana|banao|banado|banana|banaiye|banade",
    "laga": "laga|lagao|lagado|lagana|lagaiye|lagade|lga|lgao|lagaa",
    "daal": "daal|daalo|daaldo|daalna|dal|dalo|daldo|daaliye|daalde",
    "jod": "jod|jodo|joddo|jodna|jodiye|jodde|jodh",
    "rakh": "rakh|rakho|rakhdo|rakhna|rakhiye|rakhhe|rakhho",
    "dikha": "dikha|dikhao|dikhado|dikhana|dikhaiye|dikhade",
    "badal": "badal|badlo|badaldo|badalna|badliye|badalde",
    "tod": "tod|todo|toddo|todna|todiye",
    "chala": "chala|chalao|chalado|chalana|chalaiye",
    "ghuma": "ghuma|ghumao|ghumado|ghumana",
    "likh": "likh|likho|likhdo|likhna|likhiye|likhde",
    "badha": "badha|badhao|badhado|badhana|badhaiye",
    "ghata": "ghata|ghatao|ghatado|ghatana",
    "mila": "mila|milao|milado|milana",
    "uda": "uda|udao|udado|udana",
}
_VERB_OF = {form: stem for stem, forms in _VERBS.items() for form in forms.split("|")}
_VARIANTS = {
    "klip": "clip", "clips": "clip", "vdo": "video", "vid": "video", "vids": "video", "videos": "video",
    "pahle": "pehle", "phele": "pehle", "pehele": "pehle", "achchhe": "achha", "achhe": "achha", "acche": "achha",
    "achche": "achha", "accha": "achha", "hisse": "hissa", "hissey": "hissa",
    "awaz": "awaaz", "aawaz": "awaaz", "awaaj": "awaaz", "avaaz": "awaaz", "aavaz": "awaaz", "awaazen": "awaaz",
    "awaaze": "awaaz", "avaz": "awaaz", "avazen": "awaaz", "awazen": "awaaz", "aawaaz": "awaaz",
    "phaltu": "faltu", "fhaltu": "faltu", "sirfa": "sirf", "sirph": "sirf", "srf": "sirf",
    "second": "sec", "seconds": "sec", "secs": "sec", "sekand": "sec", "sekend": "sec", "secnd": "sec",
    "minute": "min", "minutes": "min", "mins": "min", "minit": "min", "mein": "me", "main": "me", "mai": "me",
    "doosra": "dusra", "dusre": "dusra", "doosre": "dusra", "tisra": "teesra",
    "shuruat": "shuruaat", "shuruwat": "shuruaat", "hok": "hook", "hookk": "hook",
    "colour": "color", "colours": "color", "colors": "color", "zoomm": "zoom", "zooom": "zoom",
}
_DROP = {"the", "a", "an", "do", "de", "dena", "please", "pls", "plz", "bhai", "yaar", "ji", "zara", "na",
         "ye", "yeh", "wo", "woh", "vo", "is", "us", "jo", "wala", "wali", "wale", "waala", "waali", "this", "that",
         "it", "my", "mera", "meri", "mere", "",  ","}


def _tok(word: str) -> str:
    w = _VARIANTS.get(word, word)
    w = _VERB_OF.get(w, w)
    if re.fullmatch(r"[a-z]{4,}s", w) and not w.endswith("ss") and w not in ("status", "focus", "bonus"):
        w = w[:-1]  # silences → silence, pauses → pause, umms → umm
    return w


def tokens(text: str) -> list[str]:
    return [_tok(w) for w in re.findall(r"[\wऀ-ॿ#%.:&'-]+", text.lower()) if w not in _DROP]


def _syn_tokens(text: str) -> tuple[str, ...]:
    """A synonym's tokens without numbers ("make it 30 seconds" matches any length; the number is a parameter)."""
    all_t = tokens(text)
    words = [t for t in all_t if not re.fullmatch(r"[\d.]+", t)]
    # "4 by 5" without its numbers is just "by": keep the numbers when the words alone say nothing
    if not words or all(len(t) <= 2 or t in GENERIC for t in words):
        return tuple(all_t)
    return tuple(words)


GENERIC = {"hata", "nikal", "kaat", "kar", "laga", "daal", "rakh", "uda", "remove", "delete", "cut", "add", "make",
           "set", "change", "badal", "ye", "wo", "part", "hissa", "sab", "it", "this"}
MAX_GAP = 3


@lru_cache(maxsize=1)
def _index() -> list[tuple[tuple[str, ...], str, bool]]:
    """(synonym tokens, skill, weak) — longer first. A synonym made only of generic words is weak: it is used
    only when nothing else in the clause matched ("umm hata do" is remove_fillers, not delete_segment)."""
    seen: set[tuple[tuple[str, ...], str]] = set()
    for sid, sp in spec.load().items():
        for gname, group in sp["synonyms"].items():
            for syn in group:
                # a typo is matched as written; normalizing it would "fix" it into some other word
                forms = {_norm(syn)} if gname == "typos" else {_norm(syn), _norm(normalize(syn))}
                for form in forms:
                    tk = _syn_tokens(form)
                    if tk:
                        seen.add((tk, sid))
    out = [(tk, sid, all(t in GENERIC for t in tk)) for tk, sid in seen]
    return sorted(out, key=lambda x: (-len(x[0]), -sum(map(len, x[0]))))


def _find(toks: list[str]) -> list[tuple[int, int, str, bool]]:
    """(first token, last token, skill, weak) for every synonym found in order with ≤ MAX_GAP words between its
    words. Candidates are taken best first — more words, then fewer gaps ("jump cut" beats "cut … gaps"), then
    longer — and may not share a token."""
    cands: list[tuple[int, int, int, list[int], str, bool]] = []
    for syn, sid, weak in _index():
        for i, t in enumerate(toks):
            if t != syn[0]:
                continue
            pos, j = [i], i
            for want in syn[1:]:
                nxt = next((k for k in range(j + 1, min(len(toks), j + 2 + MAX_GAP)) if toks[k] == want), None)
                if nxt is None:
                    break
                pos.append(nxt)
                j = nxt
            if len(pos) == len(syn):
                gaps = pos[-1] - pos[0] + 1 - len(pos)
                cands.append((len(syn), gaps, sum(map(len, syn)), pos, sid, weak))
                break
    cands.sort(key=lambda c: (-c[0], c[1], -c[2]))
    taken = [False] * len(toks)
    found: list[tuple[int, int, str, bool]] = []
    for _n, _g, _l, pos, sid, weak in cands:
        if any(taken[k] for k in pos) or any(f[2] == sid for f in found):
            continue
        for k in pos:
            taken[k] = True
        found.append((pos[0], pos[-1], sid, weak))
    strong = [f for f in found if not f[3]]
    return sorted(strong if strong else found)


NEG_WORDS = {"mat", "nahi", "nahin", "nhi", "mt", "no", "not", "dont", "don't", "without", "never", "bina"}


def _negated(toks: list[str], first: int, last: int, clause: str, s: dict[str, Any]) -> bool:
    joined = " ".join(toks)
    for neg in s.get("negations", []):
        nt = list(_syn_tokens(_norm(normalize(neg))))
        if len(nt) >= 2 and " ".join(nt) in joined:
            return True
    before = toks[max(0, first - 5):first]  # "don't add any transitions, crossfade" — the "don't" is 4 words back
    after = toks[last + 1:last + 4]
    if any(t in ("no", "not", "without", "bina", "dont", "don't", "never") for t in before):
        return True
    # "zoom mat lagao", "music nahi chahiye" — "awaaz nahi aa rahi" is a complaint, not a negation
    return any(t in NEG_WORDS for t in after) and not re.search(r"\b(?:nahi aa|nahi sun|na ruke)", clause)


CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\.\s|(?<!kuch )\baur\b(?!_k)(?! kuch)|\band\b(?!_k)|\bphir\b(?! se)|\bthen\b|\bplus\b|"
                          r"\balso\b|\bsath me\b|\bsaath me\b|\bsaath hi\b|&)\s*")


KEEP_TOGETHER = re.compile(r"\b(black|kala|kaala|top|upar|left|baaye|in|before|teal|salt|fade in|zoom in|"
                           r"slow|aage|black|tez|fast|dheema|dheere)\s+(and|aur|&|n|then|phir|fir)\s+(white|safed|bottom|"
                           r"neeche|niche|right|daaye|out|after|orange|pepper|fade out|zoom out|fast|peeche|slow|tez|"
                           r"dheema|dheere)\b")


def clauses(text: str) -> list[str]:
    text = KEEP_TOGETHER.sub(lambda m: f"{m.group(1)} {m.group(2)}_k {m.group(3)}", text)
    parts = [p.strip(" .").replace("_k ", " ").replace("_k", "")
             for p in CLAUSE_SPLIT.split(text) if p and p.strip(" .")]
    # "from 5 to 10" / "pehle 2 phir 1 phir 3": a split between numbers is undone
    out: list[str] = []
    for p in parts:
        if out and re.match(r"^\d", p) and re.search(r"\d\s*\w{0,3}$", out[-1]):
            out[-1] = f"{out[-1]} aur {p}"
        else:
            out.append(p)
    return out


QUOTED_ANIM = [  # (pattern with a quoted text token, the text skill, the skill it replaces in that clause)
    (re.compile(r"qtk\d+.{0,25}\b(?:slide|sarak|side se|from the (?:left|right))|\bslid\w* (?:in )?(?:text )?qtk"), "text_slide", "slide"),
    (re.compile(r"qtk\d+.{0,25}\bpop|\bpop\w* (?:in )?(?:text )?qtk"), "text_pop_in", None),
    (re.compile(r"qtk\d+.{0,25}\b(?:type|typing|typewriter|taip)|\b(?:typewriter|type hota)\w* .{0,10}qtk"), "text_typewriter", "text_overlay"),
    (re.compile(r"qtk\d+.{0,25}\b(?:neon|glow\w*|chamak\w*)|\b(?:neon|glow\w*)\s+(?:\w+\s+)?qtk"), "text_glow_neon", "title_card"),
]
TRIGGERS = [  # skills said only with numbers (no synonym can say "pehle 2 phir 1")
    (re.compile(r"\b(?:captions?|subtitles?)\b.{0,25}\b(?:yellow|peel\w*|white|safed|red|laal|green|hara|blue|neela|pink|"
                r"bad[ae]|bigger|chhot[ae]|smaller|font|style|hormozi|neon|minimal|comic|desi|news|cinema|boring|design)\b|"
                r"\b(?:hormozi|neon|minimal|comic|desi|news)\s+(?:style\s+)?(?:captions?|subtitles?)\b"), "caption_style"),
    (re.compile(rf"\b\d+(?:\.\d+)?\s*{UNIT}?\s*(?:se|to|-)\s*\d+(?:\.\d+)?\s*{UNIT}?\s*(?:tak\s+)?(?:ka\s+|wala\s+|ke\s+)?"
                r"(?:hissa\s+|part\s+)?(?:hata|hatao|nikal|nikalo|kaat|kaato|delete|remove|uda)"), "delete_segment"),
    (re.compile(r"\b(?:keep|rakho|rakh|sirf|only)\s+(?:only\s+|the\s+|sirf\s+)*(?:red|laal|lal|yellow|peela|blue|neela|"
                r"green|hara|pink|gulabi|orange|narangi)\b"), "color_pop"),
    (re.compile(r"(?:^|\s)(?:[1-3](?:\.\d+)?|4)\s*x\b(?!\s*(?:slow|dheem))"), "speed_up"),
    (re.compile(r"(?:^|\s)0?\.\d+\s*x\b"), "slow_motion"),
    (re.compile(r"\bpehle\s+\d+\s+(?:aur|phir|then|fir)\s+\d+|\border\s*(?:me|karo|kar|banao)?\s*\d+\s+\d+|"
                r"^\s*\d+\s+\d+(?:\s+\d+)*\s*(?:order|karo|kar)"), "reorder_clips"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:s|sec|secs|second|seconds)\s*(?:ka|ki|ke)\s+(?:karo|kar|bana\w*|video|reel|clip|vdo)\b|"
                r"\b\d+\s*(?:min|minute)\w*\s*(?:ka|ki)\b"), "fit_to_duration"),
]


def _params(s: dict[str, Any], clause: str, raw_clause: str,
            quotes: list[str] | None = None) -> tuple[dict[str, Any], list[str], bool]:
    params: dict[str, Any] = {}
    assumed: list[str] = []
    consumed_range = False
    n_numbers = len(re.findall(r"\d+(?:\.\d+)?", re.sub(r"qtk\d+", "", clause)))
    used: list[float] = []
    for k, p in s["params"].items():
        ex = p.get("extract")
        if not ex or ex not in EXTRACTORS:
            continue
        if ex == "quoted_text":
            m = re.search(r"qtk(\d+)", clause) or re.search(r"qtk(\d+)", raw_clause)
            v = (quotes or [])[int(m.group(1))] if m and quotes and int(m.group(1)) < len(quotes) else None
        else:
            v = EXTRACTORS[ex](re.sub(r"\s*qtk\d+\s*", " ", clause))
        if v is None:
            continue
        if ex.startswith("time_range"):
            consumed_range = True
        if ex == "move_to" and v == 999:
            v = None
        if isinstance(v, int | float) and not isinstance(v, bool) and ex not in ("time_range_start", "time_range_end",
                                                                               "move_from", "move_to"):
            said = sum(1 for x in re.findall(r"\d+(?:\.\d+)?", clause) if float(x) == float(v)) or 1
            if used.count(v) >= said:
                continue  # this number already filled another setting ("half second shots" is not the total)
            used.append(v)
        if v is not None:
            params[k] = v
    for k, p in s["params"].items():
        if p["type"] != "choice" or k in params or p.get("extract"):
            continue
        v = choice_in(clause, p["choices"])
        if v is not None:
            params[k] = v
    # direction + magnitude for amounts: "thoda dark karo" = brightness −0.06, "contrast kam" = contrast 0.88
    mag = x_magnitude(clause)
    f = 0.5 if mag == "small" else 1.6 if mag == "big" else 1.0
    complaint_dark = re.search(r"\b(?:dark|andhera|kala)\s+(?:hai|he|h|lag)|too dark|kuch dikh nahi", clause)
    down = bool(DOWN.search(clause)) and not UP.search(clause) and not complaint_dark
    for k, p in s["params"].items():
        ex = p.get("extract")
        if ex not in ("signed_amount", "level") or k in params or p.get("default") is None:
            continue
        lo, hi = p.get("min", -1e9), p.get("max", 1e9)
        if ex == "signed_amount":
            v = p["default"] * f * (-1 if down else 1)
        else:
            v = 1 + (p["default"] - 1) * f * (-1 if down else 1)
        params[k] = round(min(hi, max(lo, v)), 3)
        if mag or down:
            assumed.append(f"'{'kam' if down else ''}{' thoda' if mag == 'small' else ' bahut' if mag == 'big' else ''}'"
                           f" = {k} {params[k]}".replace("' ", "'"))
    # magnitude words scale the main amount-like parameter
    if mag:
        for k, p in s["params"].items():
            if p.get("extract") == "magnitude" and k not in params and p.get("default") is not None:
                lo, hi = p.get("min", 0), p.get("max", 1e9)
                f = 0.5 if mag == "small" else 1.6
                v = min(hi, max(lo, p["default"] * f))
                params[k] = round(v, 3) if p["type"] == "number" else int(round(v))
                assumed.append(f"'{'thoda' if mag == 'small' else 'bahut'}' = {k} {params[k]}")
                break
    return params, assumed, consumed_range


CHOICE_WORDS = {  # words for choice values that are not the value's own name
    "blur": r"blur\w*|dhundh\w*", "fit": r"\bfit\b|poora dikhe|bars?\b|kali patti|black bars", "crop": r"\bcrop\w*|fill\b",
    "top_bottom": r"top (?:and|&)? ?bottom|upar (?:aur )?neeche|upar niche|stack\w*|vertical(?:ly)? stack",
    "left_right": r"left (?:and|&)? ?right|side by side|baaye daaye|aamne saamne",
    "outro": r"\boutro|\bend\b|\bant\b|last me|aakhir", "both": r"\bdono\b|\bboth\b",
    "close": r"\bclose\w*|\bband\b|\bbund\b|\bsimat", "open": r"\bopen\w*|\bkhul\w*",
    "arrow": r"\barrow\w*|\bteer\b|\btir\b", "ring": r"\bcircle|\bring\b|\bgol\w*|\bghera", "box": r"\bbox\b|\bdabba\b|rectangle",
}


def choice_in(clause: str, choices: list[Any]) -> Any:
    """The choice a clause names (its own word, or a CHOICE_WORDS phrase); the longest name wins."""
    best = None
    for c in sorted(choices, key=lambda c: -len(str(c))):
        name = str(c)
        pat = CHOICE_WORDS.get(name) or rf"\b{re.escape(name.replace('_', ' '))}\b"
        if re.search(pat, clause):
            best = c
            break
    return best


def nearest(text: str, n: int = 3) -> list[dict[str, str]]:
    """The closest Tier 1 skills to words nobody matched (fuzzy over synonyms) — never empty."""
    words = [w for w in re.findall(r"[\wऀ-ॿ]+", _norm(normalize(text))) if len(w) > 2]
    scores: dict[str, float] = {}
    for syn, sid, _weak in _index():
        for part in syn:
            for w in words or [text]:
                r = difflib.SequenceMatcher(None, w, part).ratio()
                if r > scores.get(sid, 0.0):
                    scores[sid] = r
    specs = spec.load()
    top = sorted(scores, key=lambda k: -scores[k])[:n]
    return [{"id": k, "name": specs[k]["name"], "try": specs[k]["examples"][0]["prompt"]} for k in top]


QUOTE = re.compile(r"['\"‘“]([^'\"’”]{1,120})['\"’”]")


def parse(prompt: str) -> dict[str, Any]:
    specs = spec.load()
    # quoted text keeps its case and punctuation: it is swapped for a token before normalizing / splitting
    quotes = [q.strip() for q in QUOTE.findall(prompt)]
    typed_emoji = x_emoji(prompt) if re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", prompt) else None
    for i, _q in enumerate(quotes):
        prompt = QUOTE.sub(f" qtk{i} ", prompt, count=1)
    raw = _norm(prompt)
    norm = _norm(_fractions(normalize(prompt)))
    calls: list[dict[str, Any]] = []
    negated: list[str] = []
    unknown: list[dict[str, Any]] = []
    assumed: list[str] = []
    raw_parts = clauses(raw)
    norm_parts = clauses(norm)
    if len(raw_parts) != len(norm_parts):
        raw_parts = [raw] * len(norm_parts)
    merged_n: list[str] = []
    merged_r: list[str] = []
    for c, rc in zip(norm_parts, raw_parts, strict=False):
        if merged_n and (re.search(r"\d", c) or x_color(c)) and not _find(tokens(c)) \
                and not any(rx.search(c) for rx, _ in TRIGGERS):
            merged_n[-1] += " " + c
            merged_r[-1] += " " + rc
        else:
            merged_n.append(c)
            merged_r.append(rc)
    for c, rc in zip(merged_n, merged_r, strict=False):
        toks = tokens(c)
        hits = [(f, l_, sid, w, toks) for f, l_, sid, w in _find(toks)]
        if rc != c:
            rtoks = tokens(rc)
            hits += [(f, l_, sid, w, rtoks) for f, l_, sid, w in _find(rtoks) if sid not in {h[2] for h in hits}]
        for rx, sid in TRIGGERS:
            if rx.search(c) and sid not in {h[2] for h in hits}:
                hits.append((0, 0, sid, False, toks))
        for rx, sid, displaced in QUOTED_ANIM:
            if rx.search(c):
                hits = [h for h in hits if h[2] not in (displaced, "text_overlay")]
                if sid not in {h[2] for h in hits}:
                    hits.append((0, 0, sid, False, toks))
        if any(not h[3] for h in hits):
            hits = [h for h in hits if not h[3]]
        if not hits:
            if re.search(r"[a-zऀ-ॿ]{3,}", c.replace("qtk", "")):
                unknown.append({"text": c, "nearest": nearest(c)})
            continue
        for first, last, sid, _weak, tk in hits:
            s = specs[sid]
            if _negated(tk, first, last, c, s):
                if sid not in negated:
                    negated.append(sid)
                continue
            params, a1, consumed = _params(s, c, rc, quotes)
            if typed_emoji and "emoji" in s["params"]:
                params["emoji"] = typed_emoji
            prev = next((x for x in calls if x["id"] == sid), None)
            if prev is not None:  # "color pop, keep the red": the second mention adds what the first one lacked
                for k, v in params.items():
                    if k == "where" and {prev["params"].get(k), v} == {"start", "end"}:
                        prev["params"][k] = "start_end"  # "fade in at the start and fade out at the end"
                    prev["params"].setdefault(k, v)
                continue
            time, a2 = x_time(c, s["time_modes"], consumed)
            assumed += a1 + a2
            calls.append({"id": sid, "params": params, "time": time, "_clause": len(merged_n) and c})
    by_clause: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        by_clause.setdefault(call["_clause"], []).append(call)
    keep = []
    for call in calls:
        missing = [k for k, p in specs[call["id"]]["params"].items() if p.get("required") and k not in call["params"]]
        if missing and len(by_clause[call["_clause"]]) > 1:
            continue  # "keep only yellow" is a colour pop, not a trim without times
        keep.append(call)
    # a word that set a setting of a framing skill is not its own skill ("vertical, blur sides" = blurred fill)
    aspects = [c for c in keep if c["id"].startswith("aspect_") and c["params"].get("fit_mode") == "blur"]
    if aspects:
        keep = [c for c in keep if not (c["id"] in ("blur", "blur_background_fill")
                                        and any(a["_clause"] == c["_clause"] for a in aspects))]
    calls = [{k: v for k, v in c.items() if k != "_clause"} for c in keep]
    return {"calls": calls, "negated": negated, "unknown": unknown, "assumed": assumed, "normalized": norm}
