"""The understanding router: rules first, a small model when the rules understood nothing, a bigger model only when
the small one is unsure, a deterministic fallback last. Never raises.

    rules (intent.parse_intent / phrasebook)          — every clause, instant
      └─ unclear clause → LLM_MODEL (e.g. qwen3-1.7b)  — grammar-constrained commands (llm_provider.py)
           └─ low confidence / rejected → LLM_MODEL_BIG (e.g. qwen3-4b), when its file is present
                └─ nothing usable → the fine-tuned translator, then "samajh nahi aaya" with suggestions

A model answer is only used when (1) every command phrase is understood by the rule parser, (2) it does not do
the opposite of a negation in the user's words ("glitch mat daalna" must never ADD glitch), (3) it takes nothing
away unless the user's words take something away.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from .intent import parse_intent
from .llm_provider import (ProviderError, command_schema, commands_to_text, get_provider, model_path,
                           system_prompt)

NEGATION = re.compile(r"\b(mat|nahi|nahin|nhi|na|don'?t|do not|no|without|bina|never|band)\b", re.I)
TAKES_AWAY = re.compile(r"\b(mute|hata\w*|band|nikal\w*|remove|off|bina|mat|nahi chahiye|no|without|delete|kaat\w*|"
                        r"chhota|kam|rid|drop|lose|kill|cut out|take out|strip)\b", re.I)
ADDS = {"effect", "music", "captions", "title", "end_text", "stickers", "transition", "slow_motion", "fast_cuts",
        "my_song", "text_behind", "bass"}
REMOVES = {"no_music", "no_captions", "no_text", "no_effects", "no_transitions", "no_stickers", "mute", "drop_clip",
           "remove_boring", "remove_silence", "remove_fillers", "start_over", "shorter"}
MIN_CONFIDENCE = float(os.environ.get("LLM_MIN_CONFIDENCE", "0.5"))
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "25"))
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "160"))

last_trace: list[dict[str, Any]] = []  # what the router did for the latest phrase (shown in /llm/health, tests)


# commands that change the WHOLE edit's style or start it again: only when the user's words talk about a style / a
# new edit (live, Qwen3-0.6B read "gaane ki awaaz thodi dheemi kar do" as "podcast clip" and rebuilt the user's edit)
WHOLE_EDIT = {"auto_edit", "start_over", "style_cinematic", "style_fan_edit", "style_travel", "style_podcast",
              "style_wedding", "style_gym", "style_lyrics", "style_lyric_poster", "use_reference", "platform", "aspect"}
STYLE_WORDS = re.compile(r"\b(podcast|interview|wedding|shaadi|travel|trip|safar|gym|workout|fan|lyric\w*|poster|"
                         r"cinematic|filmy|film|movie|reel|insta\w*|youtube|shorts?|tiktok|mast|accha|achha|badhiya|"
                         r"jhakaa?s|zabardast|naya|nayi|shuru|reset|start over|jaisa|jaise|like|style|vibe|look|"
                         r"edit|bana\w*|viral|mrbeast|reference|sample|vertical|square|horizontal|\d+:\d+)\b", re.I)


def _acceptable(phrase: str, commands: list[dict[str, Any]]) -> str | None:
    """Why a model answer must not be used (None = fine)."""
    from .phrasebook import _topic_supported

    ids = {str(c.get("id")) for c in commands}
    if ids & WHOLE_EDIT and not STYLE_WORDS.search(phrase):
        return "changes the whole edit's style although the user's words do not talk about a style"
    text = commands_to_text(commands)
    # a style ask ("MrBeast jaisa") implies many things (captions, cuts, music); a small ask may only touch its topic
    if text and not STYLE_WORDS.search(phrase) and not _topic_supported(text, phrase):
        return "is about something the user's words do not mention"
    neg = NEGATION.search(phrase)
    if neg and ids & ADDS:
        # "glitch mat daalna": adding the very thing the user said no to
        said_no = phrase.lower()[max(0, neg.start() - 30):neg.end() + 5]
        for c in commands:
            if c.get("id") in ADDS and (str(c.get("value") or "").lower() in said_no
                                        or str(c.get("id")).split("_")[0] in said_no):
                return f"adds '{c.get('value') or c.get('id')}' although the user said no"
    if ids & REMOVES and not TAKES_AWAY.search(phrase):
        return "takes something away the user did not ask to remove"
    return None


def understand_phrase(phrase: str, deadline: float | None = None) -> str | None:
    """An unclear clause → command phrases the rule parser understands, or None."""
    global last_trace
    last_trace = []
    tiers = [os.environ.get("LLM_MODEL") or None]
    big = os.environ.get("LLM_MODEL_BIG")
    if big and model_path(big).exists():
        tiers.append(big)
    for model in tiers:
        provider = get_provider(model=model)
        if provider.name == "rules":
            last_trace.append({"provider": "rules", "result": "no model configured"})
            return None
        left = TIMEOUT if deadline is None else deadline - time.monotonic()
        if left < 2:
            last_trace.append({"provider": provider.name, "model": model, "result": "no time left"})
            return None
        t0 = time.monotonic()
        try:
            data = provider.generate_json(command_schema(), phrase, timeout=min(TIMEOUT, left), max_tokens=MAX_TOKENS,
                                          system=system_prompt())
        except ProviderError as exc:
            last_trace.append({"provider": provider.name, "model": model, "result": f"failed: {exc}"})
            continue
        cmds = [c for c in data.get("commands") or [] if isinstance(c, dict)]
        try:
            conf = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        text = commands_to_text(cmds)
        why = _acceptable(phrase, cmds) if cmds else None
        step = {"provider": provider.name, "model": model, "seconds": round(time.monotonic() - t0, 2),
                "commands": cmds, "confidence": conf, "text": text}
        if why:
            last_trace.append({**step, "result": f"rejected: {why}"})
            continue
        if not cmds or conf < MIN_CONFIDENCE:
            last_trace.append({**step, "result": "nothing / low confidence"})
            continue
        if not parse_intent(text).recognized:
            last_trace.append({**step, "result": "rejected: rules did not understand the commands"})
            continue
        last_trace.append({**step, "result": "used"})
        return text
    return None
