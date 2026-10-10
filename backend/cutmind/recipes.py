"""Style recipes (video_editing_knowledge/recipes.yaml): editing craft as numbers, schema-validated.

`pick(intent, genres)` chooses the recipe for a request: an explicit style word wins, then the detected genre, then
the platform; the Director reports the choice ("Style: Podcast clip — 3-8 s shots, cuts on speech, premium captions")
and agents read numbers from it instead of guessing."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

KNOW = Path(__file__).resolve().parent.parent / "video_editing_knowledge"

# words that name a recipe directly (checked on the prompt, lower-case)
WORDS: dict[str, str] = {
    r"podcast": "podcast_clip", r"interview": "interview", r"\bgym\b|workout|fitness": "gym_motivation",
    r"product|\bad\b|advert": "product_ad", r"\bvlog\b|day in (my|the) life": "daily_vlog", r"wedding|shaa?di|vivah|byah": "wedding_highlight",
    r"\bnews\b": "news_update", r"tutorial|how to": "tutorial", r"comedy|skit|funny": "comedy_skit",
    r"cinematic short|short film|filmy|cinematic|movie (jaisa|like)": "cinematic_short", r"aesthetic": "aesthetic_slow", r"hype|fast.?cut": "fast_hype",
    r"real.?estate|property tour|house tour": "real_estate_tour", r"\bfood\b|recipe|khana": "food_reel",
    r"explainer|educational": "explainer", r"fan ?edit|velocity": "fan_velocity", r"lyric poster|poster style": "lyric_poster",
    r"party|birthday": "party_reel", r"sports|match|goal": "sports_highlight", r"gaming|gameplay": "gaming_clip",
    r"fashion|lookbook|outfit": "fashion_lookbook", r"drone|scenic": "drone_scenic", r"event|conference": "event_recap",
    r"\bmeme\b": "meme_edit", r"travel|\btrip\b|safar|ghum\w*": "travel_reel", r"youtube video|long.?form": "youtube_long",
    r"\b(reel|reels|insta\w*|shorts?|tiktok)\b": "daily_vlog",  # a short-video ask with no other style
}


@lru_cache(maxsize=1)
def recipes() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load((KNOW / "recipes.yaml").read_text(encoding="utf-8"))["recipes"]
    return {r["id"]: r for r in data}


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    return json.loads((KNOW / "recipes.schema.json").read_text(encoding="utf-8"))


def validate_all() -> list[str]:
    """Schema problems in recipes.yaml (empty = all good)."""
    import jsonschema

    errors = []
    for rid, r in recipes().items():
        for e in jsonschema.Draft202012Validator(schema()).iter_errors(r):
            errors.append(f"{rid}: {e.message}")
        if r["shot_len"][0] > r["shot_len"][1] or r["bpm"][0] > r["bpm"][1]:
            errors.append(f"{rid}: range is upside down")
    return errors


def pick(prompt: str, genres: list[str] | None = None, platform: str | None = None) -> dict[str, Any] | None:
    p = (prompt or "").lower()
    for rx, rid in WORDS.items():
        if re.search(rx, p):
            return recipes()[rid]
    for g in genres or []:
        for r in recipes().values():
            if r["genre"] == g:
                return r
    if platform in ("instagram", "reels", "tiktok", "shorts"):
        return recipes()["daily_vlog"]
    return None


def describe(r: dict[str, Any]) -> str:
    lo, hi = r["shot_len"]
    return (f"{r['name']} — {lo:g}-{hi:g} s shots, cuts on {r['cut_on']}, {r['captions']} captions, look {r['look']}, "
            f"{r['aspect']}, ~{r['duration']:g} s, {r['lufs']} LUFS")
