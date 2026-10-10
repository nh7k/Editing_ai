"""Evidence gate for LLM-proposed intent fields.

Small local models sometimes "decorate" a request (e.g. add 1080p, black & white or transitions nobody asked
for). A field the keyword parser did not find is accepted from the LLM only if the prompt contains at least
one word that could plausibly ask for it. The vocabularies are deliberately broad (English + Hinglish) so the
LLM can still help with paraphrases like "jahan koi bol nahi raha woh hissa hata do".
"""

from __future__ import annotations

import re
from typing import Any

EVIDENCE: dict[str, tuple[str, ...]] = {
    # a number with a time unit — NOT any digit ("9:16" or "1:1" are aspect ratios, seen live with the 0.5B model)
    "target_duration": (r"\d+(\.\d+)?\s*-?\s*(s|sec|secs|second|seconds|min|mins|minute|minutes)\b", r"\bseconds?\b", r"\bminutes?\b",
                        r"\bsec\b", r"\blength\b", r"\blong\b", r"\bshorter\b", r"\bchhot", r"\blamb"),
    "aspect_ratio": (r"\d+\s*:\s*\d+", r"vertical", r"square", r"landscape", r"horizontal", r"portrait", r"\breels?\b",
                     r"\bshorts?\b", r"story", r"tiktok", r"instagram", r"youtube", r"widescreen", r"\bkhada\b", r"\bleta\b",
                     r"phone", r"mobile"),
    "resolution": (r"\d{3,4}\s*p\b", r"\bhd\b", r"\b4k\b", r"resolution", r"quality", r"sharp"),
    "color_preset": (r"colou?r", r"\brang", r"\blook\b", r"\btone", r"grade", r"grading", r"filter", r"warm", r"cool", r"cold",
                     r"cinematic", r"film", r"vintage", r"retro", r"old", r"black", r"white", r"\bbw\b", r"mono", r"gray", r"grey",
                     r"vivid", r"vibrant", r"bright", r"saturat", r"gara?m", r"thand", r"puran", r"golden", r"sunset", r"moody"),
    "transition": (r"transition", r"\bfade", r"dissolve", r"\bwipe", r"\bblend", r"between (clips|shots|scenes)", r"smooth"),
    "music_mood": (r"music", r"song", r"gaa?n", r"tune", r"bgm", r"beat", r"sangeet", r"track", r"calm", r"chill", r"upbeat",
                   r"energetic", r"lofi", r"lo-fi", r"soft"),
    "title": (r"\btitle\b", r"heading", r"\bnaam\b"),
    # boolean flags
    "captions": (r"caption", r"subtitle", r"\bsubs?\b", r"text", r"likh", r"transcri", r"words"),
    "remove_silence": (r"silen", r"pause", r"quiet", r"dead", r"gap", r"khamosh", r"\bchup", r"bol nahi", r"awaa?z nahi",
                       r"empty", r"boring"),
    "remove_fillers": (r"filler", r"\bums?\b", r"\buhs?\b", r"\berm", r"hesitat"),
    "fast_cuts": (r"fast", r"quick", r"snappy", r"rapid", r"energetic", r"hype", r"pace", r"\btez", r"jaldi", r"dynamic", r"\bcuts?\b",
                  r"punchy", r"pop"),
    "slow_motion": (r"slow", r"dheer"),
    "music": (r"music", r"song", r"gaa?n", r"tune", r"bgm", r"beat", r"sangeet", r"soundtrack", r"track", r"audio"),
    "beat_sync": (r"beat", r"rhythm", r"sync", r"\btaal"),
    "voice_cleanup": (r"clean", r"noise", r"voice", r"awaa?z", r"denois", r"clear", r"audio", r"sound", r"echo", r"hum"),
    "order": (r"reverse", r"backward", r"ult[aie]", r"\bbest\b", r"highlight", r"order", r"sequence"),
    "effects": (r"zoom", r"shake", r"handheld", r"blur", r"ramp", r"speed", r"ken burns", r"punch", r"motion", r"effect",
                r"vignette", r"sharp", r"crisp", r"soft"),
    # extra FFmpeg operations
    "rotate": (r"rotat", r"ghuma", r"clockwise", r"upside", r"\b(90|180|270)\b", r"turn (it|the video)", r"sideways"),
    "flip": (r"flip", r"mirror", r"ulta side"),
    "reverse_playback": (r"revers", r"backward", r"rewind", r"peeche", r"ulta chal"),
    "fps": (r"fps", r"frame ?rate", r"frames? per second", r"smooth"),
    "gamma": (r"gamma", r"midtone", r"shadow"),
    "mute": (r"mute", r"no (sound|audio)", r"remove (the )?(audio|sound)", r"silent video", r"without (audio|sound)",
             r"awaa?z (hata|band)"),
    "loudness": (r"loud", r"quiet", r"volume", r"awaa?z (badha|kam|tez)"),
    "audio_fade": (r"fade",),
    "watermark": (r"watermark", r"logo", r"handle", r"@\w"),
    "remove_idle": (r"idle", r"frozen", r"freeze", r"static", r"still", r"nothing (is )?happen", r"boring"),
    "export_gif": (r"\bgif",),
    "export_mp3": (r"mp3", r"audio file", r"extract", r"\baudio only"),
    "text_animation": (r"animat", r"\bpop", r"typewriter", r"typing", r"karaoke", r"bounc", r"slide", r"word by word",
                       r"fade(d)? (text|captions)"),
    "style": (r"style", r"\blook", r"premium", r"minimal", r"violet", r"purple", r"cyan", r"glow", r"neon", r"kinetic",
              r"gradient", r"\bpro\b"),
    "timed_effects": (r"\d+\s*-?\s*(s|sec|secs|second|seconds)\b",),
    "bass_boost": (r"\bbass\b", r"\bbase\b", r"dhamak", r"thump", r"beat drop"),
    "variations": (r"version", r"variation", r"option", r"\bpro\b", r"looks"),
}

_EFFECT_EVIDENCE = {
    "zoom": (r"zoom", r"ken burns", r"punch.?in", r"push.?in"),
    "shake": (r"shake", r"handheld", r"jhatk", r"hil"),
    "blur_background": (r"blur", r"background", r"bg\b"),
    "speed_ramp": (r"ramp", r"speed"),
    "vignette": (r"vignette", r"dark (edges|corners)", r"edges"),
    "sharpen": (r"sharp", r"crisp", r"detail"),
    "blur": (r"blur", r"soft", r"dhundh", r"dreamy"),
}


def has_evidence(field: str, value: Any, prompt: str) -> bool:
    p = prompt.lower()
    if field == "title":
        if not isinstance(value, str) or not value.strip():
            return False  # an empty title is not a title
        return value.strip().lower() in p or any(re.search(x, p) for x in EVIDENCE["title"])
    if field == "effects":
        from .fx_catalog import EFFECTS_BY_ID

        def pats(e: str) -> tuple[str, ...]:
            fx = EFFECTS_BY_ID.get(e)
            return _EFFECT_EVIDENCE.get(e, ()) + (fx.keywords if fx else ()) + (e.replace("_", " "),)
        return all(any(re.search(x, p) for x in pats(e)) for e in value)
    if field == "transition":
        from .fx_catalog import TRANSITIONS_BY_ID

        fx = TRANSITIONS_BY_ID.get(str(value))
        return any(re.search(x, p) for x in EVIDENCE["transition"] + (fx.keywords if fx else ()))
    if field in ("auto", "order"):
        from .intent import AUTO_EDIT, GENERIC_EDIT, SMART_ORDER

        extra = AUTO_EDIT + GENERIC_EDIT if field == "auto" else SMART_ORDER + AUTO_EDIT + EVIDENCE["order"]
        return any(re.search(x, p) for x in extra)
    pats = EVIDENCE.get(field)
    if pats is None:
        return True
    return any(re.search(x, p) for x in pats)
