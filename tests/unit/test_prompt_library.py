"""Every ready-made brief must be fully understood, round-trip through the coach, and pick its genre."""

import pytest
import yaml

from cutmind.coach import solid_prompt
from cutmind.editorial import KNOWLEDGE_DIR, classify, compile_spec
from cutmind.intent import parse_intent

LIB = yaml.safe_load((KNOWLEDGE_DIR / "prompt_library.yaml").read_text(encoding="utf-8"))["prompts"]


def test_library_has_at_least_20_briefs():
    assert len(LIB) >= 20 and len({p["id"] for p in LIB}) == len(LIB)


@pytest.mark.parametrize("item", LIB, ids=lambda p: p["id"])
def test_brief_is_understood(item):
    it = parse_intent(item["prompt"])
    # understood by the parser, or (fan edits) by the content type the editorial brain recognises
    assert len(it.recognized) >= 2 or it.auto or classify(item["prompt"]), it.recognized
    if item["genre"] != "auto":
        assert item["genre"] in [g["id"] for g in classify(item["prompt"])], (item["genre"], classify(item["prompt"]))
    spec = compile_spec(item["prompt"], it)
    assert spec.skills, "no editing skill retrieved"
    again = parse_intent(solid_prompt(it, item["prompt"]))
    for f in ("target_duration", "aspect_ratio", "color_preset", "captions", "remove_silence", "fast_cuts", "beat_sync",
              "music", "transition", "text_style", "effects"):
        assert getattr(again, f) == getattr(it, f), (f, getattr(it, f), getattr(again, f))
