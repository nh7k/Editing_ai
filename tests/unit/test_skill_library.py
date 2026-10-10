"""The skill library: registry consistency, matching (synonyms + the rule parser), the effect stack resolver, the
motion engine (Python easing == FFmpeg expression), structured skill calls, and the Desi → Pro enhancer."""

import math
import subprocess

import pytest

from cutmind import skill_registry as R
from cutmind.engines import motion
from cutmind.engines.stack import resolve, stage
from cutmind.ffmpeg_utils import ffmpeg_bin
from cutmind.plan import EditPlan
from cutmind.prompt_enhancer import enhance
from cutmind.skill_apply import SkillError, apply


def test_registry_is_consistent_and_big_enough():
    assert R.problems() == []
    skills = R.load()
    assert len(skills) >= 150
    tiers = [s["tier"] for s in skills.values()]
    assert tiers.count(1) == 40 and tiers.count(2) >= 50
    for s in skills.values():
        assert len(s["examples"]) >= 5


def test_every_tier1_skill_has_desi_words():
    for s in R.load().values():
        if s["tier"] == 1:
            syn = s["synonyms"]
            assert syn.get("hinglish") or syn.get("hi"), s["id"]


@pytest.mark.parametrize("text,want,not_want", [
    ("zoom transition between clips", "zoom_transition", "zoom_in"),
    ("zoom mat lagao", None, "zoom_in"),
    ("कैप्शन लगा दो", "captions", None),
    ("captins lagao aur gaana hata do", "no_music", "music"),
    ("das second ki reel", "target_duration", None),
])
def test_understand(text, want, not_want):
    u = R.understand(text)
    if want:
        assert want in u["skills"], u
    if not_want:
        assert not_want not in u["skills"], u


def test_zoom_negation_is_reported():
    assert "zoom_in" in R.understand("zoom mat lagao")["negated"]


def _plan(effects):
    return EditPlan.model_validate({"clips": [{"source": "a", "in": 0, "out": 3, "order": 0},
                                              {"source": "b", "in": 0, "out": 3, "order": 1}], "effects": effects})


def test_stack_orders_merges_and_resolves_conflicts():
    p, notes = resolve(_plan([{"type": "vignette", "target": 0}, {"type": "zoom", "target": 0},
                              {"type": "zoom", "target": 0, "strength": 2.0}, {"type": "mono", "target": 1},
                              {"type": "color_pop", "target": 1}, {"type": "flash", "target": 0, "times": [0.5]}]))
    types = [(e.type, e.target) for e in p.effects]
    assert types.index(("zoom", 0)) < types.index(("vignette", 0)) < types.index(("flash", 0))  # move, texture, flash
    assert [e for e in p.effects if e.type == "zoom"][0].strength == 2.0 and types.count(("zoom", 0)) == 1
    assert ("mono", 1) not in types and ("color_pop", 1) in types  # the later ask wins
    assert any("cancel" in n for n in notes) and any("twice" in n for n in notes)
    assert stage("zoom") < stage("mono") < stage("film_grain") < stage("flash")


@pytest.mark.parametrize("name", list(motion.EASINGS))
def test_easing_starts_and_ends_on_its_keys(name):
    keys = [(0.0, 1.0), (1.0, 2.0), (2.0, 1.5)]
    for t in (0.0, 0.25, 0.5, 0.75, 1.0, 1.4, 2.0, 2.5):
        assert math.isfinite(motion.value_at(keys, t, name))
    assert abs(motion.value_at(keys, 0.0, name) - 1.0) < 1e-9 and abs(motion.value_at(keys, 2.0, name) - 1.5) < 1e-9
    assert abs(motion.value_at(keys, 1.0, name) - 2.0) < 1e-6


def test_ffmpeg_evaluates_the_eased_expression_like_python():
    """Render the eased value as a solid grey level frame by frame and compare with the Python curve."""
    import numpy as np

    keys = [(0.0, 0.0), (1.0, 200.0)]
    for name in ("ease_in_out", "back", "bounce", "spring"):
        e = motion.expr(keys, "T", name)
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                              "color=c=black:s=16x16:r=10:d=1", "-vf", f"format=gray,geq=lum='clip({e},0,255)'",
                              "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
        assert out.returncode == 0, out.stderr[-300:]
        frames = np.frombuffer(out.stdout, dtype=np.uint8).reshape(-1, 16, 16)[:, 8, 8].astype(float)
        want = [min(255, max(0, motion.value_at(keys, i / 10, name))) for i in range(len(frames))]
        assert max(abs(a - b) for a, b in zip(frames, want)) <= 2.5, (name, list(frames), want)


def test_motion_presets_are_keyframes_inside_the_window():
    for name in motion.PRESETS:
        pts, easing = motion.preset(name, 2.0)
        assert pts[0][0] == 0 and pts[-1][0] <= 2.0 and easing in motion.EASINGS


def test_skill_calls_become_a_patch_and_bad_calls_are_refused():
    it, notes = apply([{"id": "zoom_in", "time": {"mode": "between_times", "start": 1, "end": 3}},
                       {"id": "look_bw", "time": {"mode": "intermittent", "every": 4, "length": 1}},
                       {"id": "captions"}, {"id": "look_warm"},
                       {"id": "motion_preset", "params": {"preset": "spring_zoom", "easing": "spring"},
                        "time": {"mode": "at_moment", "at": 5}}], total=12)
    assert it.from_comment and it.captions and it.color_preset == "warm"
    assert [(t.effect, t.start) for t in it.timed_effects][:1] == [("zoom", 1.0)]
    assert sum(t.effect == "mono" for t in it.timed_effects) == 3
    assert any(t.effect == "keyframes" and t.preset == "spring_zoom" for t in it.timed_effects)
    for bad, why in [({"id": "upscale"}, "not available"), ({"id": "nope"}, "unknown"),
                     ({"id": "look_warm", "time": {"mode": "at_moment", "at": 1}}, "cannot be used"),
                     ({"id": "zoom_in", "params": {"strength": 9}}, "between"),
                     ({"id": "zoom_in", "time": {"mode": "between_times", "start": 9, "end": 40}}, "outside")]:
        with pytest.raises(SkillError, match=why):
            apply([bad], total=12)


@pytest.mark.parametrize("text,recipe,field", [
    ("ek filmy reel bana de", "cinematic_short", "aspect"),
    ("gym ka pandrah second ka reel, bohot fast, captions", "gym_motivation", "duration"),
    ("शादी का वीडियो", "wedding_highlight", "goal"),
    ("podcast clip banao", "podcast_clip", "captions"),
])
def test_enhancer_builds_a_pro_brief_with_assumptions(text, recipe, field):
    r = enhance(text)
    assert r["recipe"] == recipe and r["understood"] and field in r["brief"]
    assert r["assumptions"] and r["pro_prompt"]


def test_enhancer_numbers_and_unsupported():
    assert enhance("gym ka pandrah second ka reel")["brief"]["duration"] == "15 s"
    r = enhance("asdf qwerty zxcv")
    assert not r["understood"] and len(r["suggestions"]) == 3


@pytest.mark.parametrize("text,later", [("4k upscale kar do", "upscale"),
                                        ("remove the background and put me on the moon", "background_removal")])
def test_asks_we_cannot_do_are_named_not_faked(text, later):
    """"4k upscale" once became a silent 1080p auto edit: an ask for a planned skill is reported as not available."""
    r = enhance(text)
    assert not r["understood"] and later in [x["id"] for x in r["not_available"]]
    assert len(r["suggestions"]) == 3 and r["not_available"][0]["why"]


def test_registry_phrases_do_not_need_the_model():
    """A clause a registry synonym names is understood without the planner LLM (the old rule sent 55 % of the
    held-out prompts to it); words nobody knows still go to it."""
    assert R.covers("gaane ki awaaz dheemi kar do") and R.covers("bolte waqt gaana dheema")
    assert not enhance("gaane ki awaaz dheemi kar do")["needs_model"]
    assert not R.covers("upscale kar do")  # planned: never counts as understood
    assert enhance("thoda sa jhakaas wala funda daal do yaar")["needs_model"]


def test_speed_ramp_default_actually_ramps():
    """strength 1.0 (the old default) is a no-op in the renderer."""
    assert R.load()["speed_ramp"]["params"]["strength"]["default"] > 1.0
