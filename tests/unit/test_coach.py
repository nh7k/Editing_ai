"""Prompt coach: desi wording → clean English prompt that means exactly the same edit."""

import pytest

from cutmind.coach import solid_prompt, understand
from cutmind.fx_catalog import ALL_FX, LUT_LOOKS
from cutmind.intent import Intent, parse_intent

USER_PROMPT = ("in my style, starting ki 3s me zoom ho or phir baad me zoom out ho , thoda base ki tarah effect ho "
               "sound be beat kare or sound music add kar view up s")

PROMPTS = [
    USER_PROMPT,
    "mast sa edit kar do",
    "ulti sidhi footage hai, arrange kar do",
    "30 sec ki reel banao, fast cuts, thoda garam rang, captions daal do, khamoshi hata do",
    "9:16 reel with warm color and upbeat music, beat sync cuts",
    "square 1:1 black and white video with zoom effect and title \"Goa Trip\"",
    "cinematic look, crossfade transitions, 1080p",
    "glitch effect, vhs look, teal and orange, pixelize transitions, karaoke captions",
    "old film, pan left, circle transitions",
    "rotate 90 and mirror it, play the video backwards, 24 fps",
    "mute the sound and add calm music, export gif and mp3",
    "remove idle parts, make it louder and sharpen, watermark @goa",
    "last 5 sec glitch, 2s se 6s tak vhs",
    "first 4 seconds slow zoom then pan left",
    "edit like a pro, 15 seconds",
    "same as before but add film grain",
    "moody look with typewriter captions, darker",
    "clean up the audio, remove ums, landscape",
    "reverse order, vintage, wipe transitions",
    "highlights only, speed ramp, blur background",
    "midnight premium look, 3 versions",
    "bass wala effect daal do, 20 seconds",
]


def _fields(it):
    d = it.model_dump(exclude={"recognized"})
    d["effects"] = sorted(d["effects"])
    return d


@pytest.mark.parametrize("prompt", PROMPTS)
def test_solid_prompt_means_the_same_edit(prompt):
    it = parse_intent(prompt)
    solid = solid_prompt(it, prompt)
    assert solid.isascii(), solid
    assert _fields(parse_intent(solid)) == _fields(it), solid


@pytest.mark.parametrize("fx", [f for f in ALL_FX if f.category in ("motion", "video_effect")], ids=lambda f: f.id)
def test_every_catalogue_effect_survives_the_round_trip(fx):
    if not fx.keywords:
        pytest.skip("not prompt-addressable")
    it = parse_intent(f"{fx.name.lower()} effect")
    if fx.id not in it.effects:
        pytest.skip(f"its own name doesn't select it: {fx.name}")
    assert fx.id in parse_intent(solid_prompt(it)).effects


@pytest.mark.parametrize("look", list(LUT_LOOKS))
def test_every_look_survives_the_round_trip(look):
    it = parse_intent(f"{LUT_LOOKS[look][0].lower()} look")
    assert it.color_preset == look
    assert parse_intent(solid_prompt(it)).color_preset == look


def test_users_own_prompt_is_explained_in_plain_english():
    out = understand(USER_PROMPT)
    s = out["solid_prompt"]
    assert out["changed"]
    assert "Zoom in for the first 3 seconds." in s and "Zoom out after 3 seconds." in s
    assert "Bass boost" in s and "In my style." in s
    assert "seconds long" not in s  # the "3s" is when the zoom happens, not the length of the video


def test_nothing_understood_keeps_the_original_text():
    out = understand("asdf qwerty")
    assert out["solid_prompt"] == "asdf qwerty" and not out["changed"]


def test_zoom_out_alone_does_not_add_zoom_in():
    # regression: "zoom out" also switched on the zoom-IN effect (found through the MCP stdio check)
    it = parse_intent("pehle 2 sec glitch phir zoom out, bass daal")
    assert "zoom" not in it.effects and [t.effect for t in it.timed_effects] == ["glitch", "zoom_out"]
    assert parse_intent("zoom out effect").effects == ["zoom_out"]


# ---- text look + person tracking (every new phrase must round-trip AND must not touch the video) ------------------
from cutmind.coach import _ANIM  # noqa: E402
from cutmind.intent import ANIM_ORDER  # noqa: E402
from cutmind.text_styles import COLOR_WORDS, TEXT_PRESETS  # noqa: E402

TEXT_PHRASES = ([_ANIM[a] for a in ANIM_ORDER] + [f"{p.name.lower()} text style" for p in TEXT_PRESETS.values()]
                + [f"{w} text" for w in COLOR_WORDS])
VIDEO_FIELDS = ("effects", "timed_effects", "color_preset", "style", "flip", "transition", "music", "beat_sync")


@pytest.mark.parametrize("phrase", TEXT_PHRASES)
def test_text_phrases_round_trip_and_leave_the_video_alone(phrase):
    it = parse_intent(phrase)
    assert it.text_animation != "none" or it.text_style or it.text_color, phrase
    for f in VIDEO_FIELDS:
        assert getattr(it, f) == Intent.model_fields[f].get_default(call_default_factory=True), (phrase, f, getattr(it, f))
    assert _fields(parse_intent(solid_prompt(it, phrase))) == _fields(it)


@pytest.mark.parametrize("prompt", [
    'track the person, spotlight, name tag "Riya" follows her',
    "zoom on the face",
    "pehle 3 sec black and white phir colour",
    'ladki ko track karo aur uske upar "Riya" likha aaye, neon text',
    "last 5 sec black and white, follow cam",
])
def test_tracking_prompts_round_trip(prompt):
    it = parse_intent(prompt)
    assert _fields(parse_intent(solid_prompt(it, prompt))) == _fields(it)
