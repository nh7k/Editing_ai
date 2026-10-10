"""Desi → Pro: a casual prompt (Hindi, Hinglish, English, slang, typos) becomes a precise, professional edit brief.

    enhance("ek filmy reel bana de") →
      normalized   : "ek filmy reel bana de"
      skills       : registry skills the message names (synonyms + the rule parser's reading)
      brief        : {goal, platform, duration, aspect, pacing, hook, look, captions, music, transitions}
      assumptions  : every brief field the user did NOT say, filled from the style recipe — shown to the user
      pro_prompt   : the brief as one professional instruction (what the editor will do)
      needs_model  : True when a clause was only half understood (the planner LLM is asked, if it is on)
      not_available: skills the message names that are planned / blocked (said plainly, never faked)
      suggestions  : when nothing was understood, the 3 closest skills with an example each

Rules first; no model is needed for any of this. Everything is deterministic and works with the LLM off.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from . import recipes, skill_registry
from .intent import parse_intent
from .phrasebook import clauses
from .prenormalize import coverage, normalize

MOOD_BY_BPM = [(0, 90, "calm"), (90, 115, "chill"), (115, 999, "upbeat")]
PLATFORM_ASPECT = {"9:16": "Instagram Reels / YouTube Shorts", "16:9": "YouTube", "1:1": "Instagram feed"}


def _mood(bpm: list[float]) -> str:
    mid = sum(bpm) / 2
    return next(m for lo, hi, m in MOOD_BY_BPM if lo <= mid < hi)


def suggestions(text: str, n: int = 3) -> list[dict[str, str]]:
    """The closest built skills to words nobody understood (fuzzy on synonyms) — never empty."""
    words = [w for w in re.findall(r"[\wऀ-ॿ]+", normalize(text).lower()) if len(w) > 2]
    scored: dict[str, float] = {}
    for sid, s in skill_registry.load().items():
        if s["status"] in ("planned", "blocked") or s["tier"] == 3:
            continue
        syns = [x.lower() for g in s["synonyms"].values() for x in g]
        best = 0.0
        for w in words:
            for syn in syns:
                for part in syn.split():
                    best = max(best, difflib.SequenceMatcher(None, w, part).ratio())
        scored[sid] = best
    top = sorted(scored, key=lambda k: -scored[k])[:n]
    reg = skill_registry.load()
    return [{"id": k, "name": reg[k]["name"], "try": reg[k]["examples"][0]} for k in top]


def enhance(text: str, genres: list[str] | None = None) -> dict[str, Any]:
    norm = normalize(text)
    it = parse_intent(norm)
    reading = skill_registry.understand(text)
    recipe = recipes.pick(norm, genres, it.platform)
    said: dict[str, Any] = {}
    if it.target_duration:
        said["duration"] = f"{it.target_duration:g} s"
    if it.aspect_ratio:
        said["aspect"] = it.aspect_ratio
    if it.platform:
        said["platform"] = it.platform
    if it.fast_cuts or it.pace_change:
        said["pacing"] = "fast cuts" if (it.fast_cuts or (it.pace_change or 1) < 1) else "slower, longer shots"
    if it.hook_first:
        said["hook"] = "open on the best moment"
    if it.color_preset:
        said["look"] = it.color_preset
    if it.captions:
        said["captions"] = "word-timed captions" + (f", {it.text_style} style" if it.text_style else "")
    if it.music or it.no_music:
        said["music"] = "no music" if it.no_music else f"{it.music_mood or 'matching'} music"
    if it.transition:
        said["transitions"] = it.transition
    brief, assumptions = dict(said), []
    if recipe:
        lo, hi = recipe["shot_len"]
        defaults = {
            "goal": recipe["name"],
            "platform": PLATFORM_ASPECT.get(said.get("aspect") or recipe["aspect"], "social"),
            "duration": f"{recipe['duration']:g} s",
            "aspect": recipe["aspect"],
            "pacing": f"{lo:g}-{hi:g} s shots, cuts on {recipe['cut_on']}",
            "hook": recipe["hook"],
            "look": recipe["look"],
            "captions": recipe["captions"],
            "music": f"{_mood(recipe['bpm'])} music ({recipe['bpm'][0]:g}-{recipe['bpm'][1]:g} bpm), "
                     + (f"ducked {recipe['duck_db']:g} dB under the voice" if recipe["duck_db"] else "full level"),
            "transitions": " / ".join(recipe["transitions"]),
        }
        for k, v in defaults.items():
            if k not in brief:
                brief[k] = v
                assumptions.append(f"{k}: {v} (from the {recipe['name']} recipe)")
    half = [c for c in clauses(norm) if coverage(c) < 0.6 and not skill_registry.covers(c)]
    reg = skill_registry.load()
    later = [s for s in skill_registry.named_later(norm) if s not in reading["skills"]]  # asked, not built yet
    can = reading["skills"]
    # "4k upscale kar do" must not quietly become a 1080p auto edit: an ask we cannot do, with nothing we can,
    # is reported as not available (+ the closest things we can do)
    understood = bool(can) or ((not it.is_empty() or recipe is not None) and not later)
    pro = "; ".join(f"{k}: {v}" for k, v in brief.items()) if brief else ""
    return {
        "normalized": norm,
        "skills": can, "not_available": [{"id": s, "name": reg[s]["name"], "why": reg[s]["impl"].get("reason", "")}
                                          for s in later], "negated": reading["negated"],
        "brief": brief, "assumptions": assumptions, "recipe": recipe["id"] if recipe else None,
        "pro_prompt": pro, "needs_model": bool(half), "half_understood": half,
        "understood": understood,
        "suggestions": [] if understood else suggestions(text),
    }
