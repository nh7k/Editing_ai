"""Long-term agent memory + the FX catalogue."""

import numpy as np
import pytest

from cutmind.agents.base import AgentContext
from cutmind.agents.director import DirectorAgent
from cutmind.db import Database
from cutmind.fx_catalog import EFFECT_IDS, EFFECTS_BY_ID, TRANSITION_IDS, TRANSITIONS_BY_ID, catalog
from cutmind.intent import Intent, parse_intent
from cutmind.luts import LOOKS, apply_look, ensure_luts
from cutmind.memory import Memory, wants_my_style, wants_repeat
from cutmind.plan import EditPlan


def test_catalogue_is_big_and_consistent():
    cat = catalog()
    counts = {k: len(v) for k, v in cat.items()}
    assert counts["transition"] >= 58 and counts["video_effect"] >= 25 and counts["motion"] >= 10
    assert counts["color"] == len(LOOKS) and counts["text_animation"] >= 6
    for fid in EFFECT_IDS:  # every effect id is accepted by the Edit Plan
        EditPlan.model_validate({"clips": [{"source": "s", "in": 0, "out": 3, "order": 0}], "effects": [{"type": fid}]})
    for tid in TRANSITION_IDS:
        EditPlan.model_validate({"clips": [{"source": "s", "in": 0, "out": 3, "order": 0},
                                           {"source": "s", "in": 3, "out": 6, "order": 1}],
                                 "transitions": [{"type": tid, "after": 0, "duration": 0.4}]})
    with pytest.raises(ValueError, match="unknown effect"):
        EditPlan.model_validate({"clips": [{"source": "s", "in": 0, "out": 3, "order": 0}], "effects": [{"type": "lasers"}]})
    assert TRANSITIONS_BY_ID["fade"].xfade == "fadeblack"
    assert EFFECTS_BY_ID["zoom"].build is not None  # regression: the "zoom" transition used to shadow the zoom effect


@pytest.mark.parametrize("prompt,check", [
    ("glitch effect with rgb split and slide transitions", lambda i: i.effects == ["glitch", "rgb_split"] and i.transition == "slideleft"),
    ("vhs look, film grain, teal and orange", lambda i: {"vhs", "film_grain"} <= set(i.effects) and i.color_preset == "teal_orange"),
    ("karaoke captions, pop text", lambda i: i.text_animation == "karaoke" and i.captions),
    ("old film, pan left, circle transitions", lambda i: i.color_preset is None and i.transition == "circleopen"),
    ("thoda glitch aur vhs daal do", lambda i: i.effects == ["glitch", "vhs"]),
    ("mirror effect", lambda i: i.effects == ["mirror"] and i.flip == "none"),
    ("mirror it", lambda i: i.flip == "h" and i.effects == []),
])
def test_prompt_finds_catalogue_items(prompt, check):
    assert check(parse_intent(prompt))


def test_generated_luts_match_their_maths(tmp_path):
    paths = ensure_luts(tmp_path)
    assert set(paths) == set(LOOKS)
    lines = paths["teal_orange"].read_text().splitlines()
    assert "LUT_3D_SIZE 33" in lines and len([ln for ln in lines if ln[:1].isdigit()]) == 33 ** 3
    grey = np.array([[0.5, 0.5, 0.5]])
    assert 0.45 < apply_look(grey, "noir")[0, 0] < 0.55
    dark = apply_look(np.array([[0.1, 0.1, 0.1]]), "teal_orange")[0]
    assert dark[2] > dark[0]  # teal shadows


def make_memory(tmp_path):
    return Memory(Database(tmp_path / "m.sqlite3"))


def test_memory_preferences(tmp_path):
    mem = make_memory(tmp_path)
    for i, (style, chosen, rating) in enumerate([("cyan_kinetic", None, None), ("violet_authority", "violet_authority", "up"),
                                                 ("violet_authority", "violet_authority", None), ("midnight_drift", None, "down")]):
        mem.remember_edit("p1", f"j{i}", f"prompt {i}", {"captions": True}, {"style": style, "aspect_ratio": "9:16"})
        if chosen:
            mem.remember_choice(f"j{i}", chosen)
        if rating:
            mem.remember_rating(f"j{i}", rating)
    prefs = mem.preferences()
    assert prefs["favourite_style"] == "violet_authority" and prefs["disliked_styles"] == ["midnight_drift"]
    assert prefs["usual_aspect_ratio"] == "9:16" and prefs["captions_share"] == 1.0
    assert "favourite look: violet_authority" in mem.summary("p1") and 'last prompt here: "prompt 3"' in mem.summary("p1")


@pytest.mark.parametrize("prompt,repeat,mine", [
    ("same as before but add glitch", True, False), ("pichli baar jaisa karo", True, False), ("do it again", True, False),
    ("mera style lagao", False, True), ("use my usual look", False, True), ("trim to 10 seconds", False, False),
])
def test_memory_phrases(prompt, repeat, mine):
    assert wants_repeat(prompt) is repeat and wants_my_style(prompt) is mine


def test_director_repeats_last_edit_and_uses_favourite(tmp_path, settings):
    mem = make_memory(tmp_path)
    mem.remember_edit("p1", "j0", "warm 9:16 reel with captions",
                      {"color_preset": "warm", "aspect_ratio": "9:16", "captions": True, "recognized": ["x"]},
                      {"style": "cyan_kinetic"})
    mem.remember_choice("j0", "cyan_kinetic")
    ctx = AgentContext(job_id="j1", prompt="same as before but add glitch", clips=[], settings=settings,
                       project_id="p1", memory=mem)
    intent, rules = DirectorAgent._use_memory(ctx, parse_intent(ctx.prompt), parse_intent(ctx.prompt))
    assert intent.color_preset == "warm" and intent.aspect_ratio == "9:16" and intent.captions and "glitch" in intent.effects
    assert rules.captions  # the Reviewer's reference also knows about the remembered instructions
    ctx2 = AgentContext(job_id="j2", prompt="trim to 10 seconds in my style", clips=[], settings=settings,
                        project_id="p1", memory=mem)
    intent2, _ = DirectorAgent._use_memory(ctx2, parse_intent(ctx2.prompt), parse_intent(ctx2.prompt))
    assert intent2.style == "cyan_kinetic" and intent2.target_duration == 10
    assert Intent().style is None


def test_agents_only_get_lessons_relevant_to_the_request(tmp_path, settings):
    from cutmind.agents.base import AgentContext
    from cutmind.agents.cutter import CutterAgent
    from cutmind.db import Database
    from cutmind.intent import parse_intent

    db = Database(tmp_path / "l.sqlite3")
    db.add_lesson("cutter", "duration", "duration: hit the requested length", "j1")
    db.add_lesson("cutter", "silence_removed", "silence_removed: remove every pause", "j2")
    db.add_lesson("cutter", "file_plays", "file_plays: always applies", "j3")
    ctx = AgentContext(job_id="x", prompt="trim to 15 seconds", clips=[], settings=settings, db=db)
    ctx.intent = parse_intent("trim to 15 seconds")
    got = CutterAgent().lessons(ctx)
    assert any("requested length" in x for x in got) and any("always applies" in x for x in got)
    assert not any("pause" in x for x in got)  # silence lesson is noise for a plain trim
