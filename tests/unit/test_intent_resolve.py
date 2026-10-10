"""The "yaha screen white kar do nomal jasia tha" failure (docs/INTENT_FAILURE_REVIEW.md) and the resolver that
replaces dead-ends with ranked, tap-able interpretations."""

from __future__ import annotations

import pytest

from cutmind.tools.resolve import resolve

BUG = "yaha screen white kar do nomal jasia tha"
MONO_AT_MARKER = {"marker_time": 4.3, "effects_present_at_time": [{"type": "mono", "start": 3.0, "end": 5.5}]}


def ids(r) -> list[str]:  # noqa: ANN001
    return [c["id"] for c in r.choices]


def test_the_bug_prompt_with_a_colour_effect_there_ranks_restore_first_and_white_flash_in_the_top3():
    r = resolve(BUG, MONO_AT_MARKER)
    assert ids(r)[0] == "restore_normal", r.trace
    assert "flash" in ids(r)[:3], r.trace
    assert r.decision in ("choose", "apply")  # never a dead end
    top = r.choices[0]
    assert top["time"]["mode"] == "between_times" and top["time"]["start"] <= 4.3 <= top["time"]["end"]


def test_the_bug_prompt_without_any_effect_there_ranks_white_flash_first_at_the_marker():
    r = resolve(BUG, {"marker_time": 4.3})
    assert ids(r)[0] == "flash", r.trace
    assert r.choices[0]["time"] == {"mode": "at_time", "at": 4.3}


@pytest.mark.parametrize("prompt", ["yahan safed kardo", "yhn whight krdo", "isko wite kar de", "यहाँ सफ़ेद कर दो"])
def test_spelling_variants_and_devanagari_reach_the_white_skills(prompt):
    r = resolve(prompt, {"marker_time": 2.0})
    assert set(ids(r)[:3]) & {"flash", "fade_white", "brighten_to_white", "white_screen_card"}, r.trace


def test_every_choice_has_a_plain_hinglish_label_and_never_more_than_three():
    r = resolve(BUG, MONO_AT_MARKER)
    assert 1 <= len(r.choices) <= 3
    assert all(c["label"] and len(c["label"]) < 70 for c in r.choices)


def test_suggestions_come_from_the_users_words_not_a_fixed_list():
    r = resolve("screen ko ekdum safed sa chamka do", {})
    assert set(ids(r)) & {"flash", "fade_white", "brighten_to_white"}, r.trace


def test_filler_words_never_decide_the_ranking():
    """'kar', 'tha', 'yaha' used to tie with the meaning word and pull in unrelated skills."""
    r = resolve(BUG, {})
    assert not set(ids(r)) & {"replace_audio", "stabilize", "hook_first", "duck_music", "thumbnail"}, r.trace


def test_a_clear_request_is_applied_directly():
    r = resolve("is jagah flash lagao", {"marker_time": 3.0})
    assert r.decision == "apply" and ids(r)[0] == "flash"


@pytest.mark.parametrize("prompt", ["yaha whitish kar do", "qwerty asdf", "kuch accha sa kar do"])
def test_never_an_empty_answer(prompt):
    """Found on the held-out set: 'yaha whitish kar do' returned no choice at all."""
    r = resolve(prompt, {"marker_time": 1.0})
    assert len(r.choices) == 3 and all(c["label"] for c in r.choices)
