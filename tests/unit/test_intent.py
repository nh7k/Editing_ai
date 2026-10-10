"""Deterministic prompt parser (mock planner)."""

import pytest

from cutmind.intent import PromptError, parse_intent, validate_prompt


def test_full_reel_prompt():
    it = parse_intent("make a 30 sec travel reel, fast cuts, warm color, add captions, remove silence")
    assert it.target_duration == 30
    assert it.aspect_ratio == "9:16"
    assert it.color_preset == "warm"
    assert it.captions and it.remove_silence and it.fast_cuts
    assert not it.music
    assert "travel/vlog style" in it.recognized


@pytest.mark.parametrize("prompt,field,value", [
    ("Trim to 15s", "target_duration", 15),
    ("make it 1 minute long", "target_duration", 60),
    ("30 second video with 1s crossfades", "target_duration", 30),
    ("square video for instagram", "aspect_ratio", "1:1"),
    ("landscape youtube cut", "aspect_ratio", "16:9"),
    ("black and white please", "color_preset", "bw"),
    ("cinematic teal look", "color_preset", "cinematic"),
    ("vibrant colours", "color_preset", "vivid"),
    ("add a dissolve between shots", "transition", "crossfade"),
    ("wipe transitions", "transition", "wipe"),
    ("fade in and out", "transition", "fade"),
    ("reverse order of clips", "order", "reverse"),
    ("show the highlights", "order", "best"),
    ("export in 1080p", "resolution", 1080),
])
def test_single_fields(prompt, field, value):
    assert getattr(parse_intent(prompt), field) == value


def test_music_effects_title():
    it = parse_intent('Fast cuts on the beat with chill music, zoom in, shake and title "Goa Trip"')
    assert it.music and it.beat_sync and it.music_mood == "calm"
    assert set(it.effects) == {"zoom", "shake"}
    assert it.title == "Goa Trip"


def test_unrecognised_prompt_is_empty_not_error():
    it = parse_intent("asdf qwerty zxcv")
    assert it.is_empty()


@pytest.mark.parametrize("bad", ["", "   ", "a", "x" * 1001])
def test_bad_prompts_raise(bad):
    with pytest.raises(PromptError):
        validate_prompt(bad)


def test_beat_sync_cuts_imply_fast_cuts():
    it = parse_intent("Vertical short, beat sync cuts, chill music")
    assert it.beat_sync and it.fast_cuts and it.music_mood == "calm"


@pytest.mark.parametrize("prompt,expected", [
    ("isko 20 second ka bana do aur gaana daal do", {"target_duration": 20, "music": True}),
    ("video ko vertical karo aur subtitles lagao", {"aspect_ratio": "9:16", "captions": True}),
    ("jahan koi bol nahi raha woh hissa hata do", {"remove_silence": True}),
    ("thoda garam rang do aur dheere dheere zoom karo", {"color_preset": "warm", "effects": ["zoom"]}),
    ("purane zamane wala look do, square banao", {"color_preset": "vintage", "aspect_ratio": "1:1"}),
    ("make it pop with some tunes, quick snappy edit", {"music": True, "fast_cuts": True}),
    ("black white kar do, clips ulta chalao", {"color_preset": "bw", "order": "reverse"}),
])
def test_hinglish_and_paraphrases(prompt, expected):
    it = parse_intent(prompt)
    assert {k: getattr(it, k) for k in expected} == expected


def test_film_grain_is_not_a_colour_look():
    """Regression (memory e2e): 'film grain' used to switch the grade to cinematic."""
    it = parse_intent("same as before but add film grain")
    assert it.color_preset is None and it.effects == ["film_grain"]
