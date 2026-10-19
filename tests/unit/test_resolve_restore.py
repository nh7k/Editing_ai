"""Removing ONE named thing takes off only that thing (docs/test_mcp/BUG_LOG.md, BUG-1..3, BUG-7) and the resolver
keeps the settings the parser read (the 'original quality' export)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cutmind.editorial import classify, concepts_in, kinetic_words_from
from cutmind.intent import parse_intent
from cutmind.plan import EditPlan
from cutmind.tools import b_cutting, b_restore
from cutmind.tools.engine import ToolCtx, first_plan
from cutmind.tools.resolve import context_from_plan, resolve
from cutmind.tools.timeline import ToolError
from cutmind.tools.timewin import When
from cutmind.versions import _effects, diff


def _plan(effects: list[dict], preset: str = "none", fade: float | None = None) -> EditPlan:
    base = first_plan(["c1"], {"c1": 12.0})
    data = base.to_json()
    data["clips"] = [{"source": "c1", "in": i * 2.0, "out": i * 2.0 + 2.0, "order": i} for i in range(6)]
    data["effects"] = effects
    data["color"]["preset"] = preset
    if fade:
        data["transitions"] = [{"type": "fade", "after": -2, "duration": fade}]
    return EditPlan.model_validate(data)


WARM_BW = [{"type": "grade", "target": -1, "params": {"warmth": 0.25}},
           {"type": "grade", "target": 1, "params": {"look": "grayscale", "look_strength": 1.0}},
           {"type": "zoom", "target": -1}]
SHAKE = [{"type": "beat_shake", "target": 3}, {"type": "flash", "target": 2}, {"type": "pulse", "target": 4},
         {"type": "film_bw", "target": 1}]


def _apply(plan: EditPlan, prompt: str) -> EditPlan:
    r = resolve(prompt, context_from_plan(plan, None))
    assert r.apply, (prompt, r.decision, r.trace)
    call = r.apply[0]
    assert call["id"] == "restore_normal", (prompt, call)
    params = {"what": "all", "only": "", **call["params"]}
    return b_restore.restore_normal(plan, params, When("whole"), ToolCtx(sources={}, gen_dir=Path(".")))


def test_black_and_white_off_keeps_the_warm_colour():
    new = _apply(_plan(WARM_BW), "black and white hata do")
    assert _effects(new) == ["warm colour", "zoom"]


def test_warm_off_takes_the_warm_preset_too_and_keeps_black_and_white():
    new = _apply(_plan(WARM_BW, preset="warm"), "warm colour hata do")
    assert "black and white" in _effects(new) and "warm colour" not in _effects(new)
    assert new.color.preset == "none"


def test_colour_off_keeps_zoom():
    assert _effects(_apply(_plan(WARM_BW), "colour hata do")) == ["zoom"]


@pytest.mark.parametrize("prompt", ["shake hatao lekin colour rehne do", "shake hata do colour mat chhedo"])
def test_shake_off_with_a_keep_clause_takes_only_the_shake(prompt):
    new = _apply(_plan(SHAKE), prompt)
    assert "beat_shake" not in _effects(new) and {"flash", "pulse", "film_bw"} <= set(_effects(new))


def test_flash_off_never_adds_a_flash():
    new = _apply(_plan(SHAKE), "flash hata do")
    assert not any(e.type == "flash" for e in new.effects)


def test_a_named_effect_that_is_not_there_is_said_and_nothing_else_goes():
    plan = _plan([{"type": "keyframes", "target": -1, "params": {}}])
    with pytest.raises(ToolError, match="no glitch"):
        b_restore.restore_normal(plan, {"what": "style", "only": "glitch"}, When("whole"),
                                 ToolCtx(sources={}, gen_dir=Path(".")))


def test_shake_off_with_no_shake_on_the_video_stabilizes():
    r = resolve("shake hatao", context_from_plan(_plan([{"type": "keyframes", "target": -1, "params": {}}]), None))
    assert r.apply and r.apply[0]["id"] == "stabilize", r.trace


def test_time_read_on_the_named_skill_reaches_the_restore():
    r = resolve("2 se 4 sec black and white hata do", context_from_plan(_plan(WARM_BW), None))
    assert r.apply[0]["time"] == {"mode": "between_times", "start": 2.0, "end": 4.0}


def test_fit_to_length_after_an_end_fade():  # BUG-1
    plan = _plan([], fade=1.5)
    new = b_cutting.fit_to_duration(plan, {"target_sec": 5}, None, ToolCtx(sources={}, gen_dir=Path(".")))
    assert new.total_duration() <= 5.1 and new.transitions[0].duration <= min(e.duration for e in new.timeline()[-1:])


def test_tuned_effect_is_reported():  # BUG-4
    a = _plan([{"type": "grade", "target": -1, "params": {"look": "vintage"}}])
    b = _plan([{"type": "grade", "target": -1, "params": {"look": "vintage", "brightness": 0.12}}])
    assert any("brightness 0 → 0.12" in c for c in diff(a, b)["changed"])


def test_cinematic_colour_is_not_the_cinematic_genre():  # BUG-5
    p = "colour ko cinematic teal orange karo aur vignette lagao"
    assert classify(p) == [] and concepts_in(p) == []
    assert [g["id"] for g in classify("isko cinematic bana do")] == ["cinematic"]


def test_kind_of_edit_words_are_never_on_screen_text():  # BUG-7
    p = "make it look like a pro football edit with flash on beats"
    assert kinetic_words_from(p, parse_intent(p)) == []
    assert kinetic_words_from("make a ronaldo edit", parse_intent("make a ronaldo edit")) == ["RONALDO"]


@pytest.mark.parametrize("prompt", ["original quality me export karo", "best quality me nikalo",
                                    "quality kam na ho export karo"])
def test_ranked_readings_keep_the_parsed_settings(prompt):
    r = resolve(prompt, {})
    assert r.apply == [{"id": "export_preset", "params": {"platform": "original"}, "time": None}], r.trace


def test_original_quality_on_an_edited_video_is_an_export_not_a_restore():
    # found by the manual MCP test: the word "original" took every effect off a warm + bright edit
    ctx = context_from_plan(_plan(WARM_BW, preset="warm"), None)
    r = resolve("original quality me export karo", ctx)
    assert r.apply == [{"id": "export_preset", "params": {"platform": "original"}, "time": None}], r.trace
    assert resolve("original jaisa kar do", ctx).apply[0]["id"] == "restore_normal"


def test_nothing_to_take_off_never_runs_a_restore():
    r = resolve("isko normal edit kar do", {"effects_present_at_time": []})  # a new project: nothing on it
    assert not r.apply or r.apply[0]["id"] != "restore_normal", r.trace
