"""Timeline comments (cutmind/moment.py) and vlog word stickers (cutmind/stickers.py): pure logic, no FFmpeg."""

import pytest

from cutmind import stickers
from cutmind.intent import parse_intent
from cutmind.memory import merge_with_last
from cutmind.intent import Intent
from cutmind.moment import moment_intent, moment_options, read_comment
from cutmind.plan import EditPlan


@pytest.mark.parametrize("text,key,value", [
    ("yaha zoom karo", "effects", ["zoom"]),
    ("black and white", "effects", ["mono"]),
    ("slow motion", "effects", ["speed_ramp"]),
    ("WOW likh do", "text", "WOW"),
    ("ye part hata do", "cut", True),
    ("Goa trip", "text", "Goa trip"),  # a short note that is no edit is written there as it is
])
def test_read_comment(text, key, value):
    assert read_comment(text)[key] == value


def test_read_comment_sticker_and_question():
    if stickers.available():
        assert read_comment("rose")["emoji"] == "\U0001F339"
        assert read_comment("yaha ped ka sticker")["emoji"] == "\U0001F333"
    assert read_comment("kya hai ye?")["understood"] == []


def _plan():
    return EditPlan.model_validate({"clips": [{"source": "a", "in": 0, "out": 4, "order": 0},
                                              {"source": "b", "in": 2, "out": 6, "order": 1}]})


def test_moment_options_maps_cut_to_the_shot_there():
    m = moment_options("ye part hata do", 5.0, _plan())
    assert m["cut_range"] == ["b", 2.0, 6.0]
    with pytest.raises(ValueError):
        moment_options("kya hai ye?", 1.0, _plan())
    with pytest.raises(ValueError):
        moment_options("zoom", 99.0, _plan())


def test_comments_add_up_in_memory():
    defaults = Intent().model_dump()
    last = merge_with_last(moment_intent(moment_options("WOW likh do", 1.0, _plan())), {}, defaults, False)
    now = merge_with_last(moment_intent(moment_options("zoom", 5.0, _plan())), last.model_dump(), defaults, False)
    assert [t.text for t in now.timed_texts] == ["WOW"]
    assert [(t.effect, t.start) for t in now.timed_effects] == [("zoom", 5.0)]


def test_sticker_asks():
    assert parse_intent("vlog me jo bol raha hu uske stickers daal do").word_stickers
    assert parse_intent("jo bhi me bolu jaise rose tree uski animation video me aa jaye").word_stickers
    off = parse_intent("stickers hata do")
    assert not off.word_stickers and "word_stickers" in off.remove
    assert not parse_intent("remove the emojis").word_stickers


def test_music_slower_is_the_level_not_the_cut():
    it = parse_intent("gaana thoda dheere karo")
    assert it.pace_change is None and it.music_volume is not None
    assert parse_intent("thoda dheere karo").pace_change == 1.5


def test_pick_spreads_and_maps_words():
    got = stickers.pick([("rose.", 1.0, 1.4), ("gulab", 1.5, 1.8), ("tree", 3.0, 3.3), ("hello", 4, 4.2)], 10)
    assert [g["emoji"] for g in got] == ["\U0001F339", "\U0001F333"]


@pytest.mark.parametrize("text,start,from_end", [
    ("last shot black and white", 2.5, True), ("aakhri shot black and white kar do", 2.5, True),
    ("pehla shot black and white", 0.0, False),
])
def test_first_or_last_shot_black_and_white(text, start, from_end):
    it = parse_intent(text)
    assert it.color_preset is None and [(t.effect, t.start, t.from_end) for t in it.timed_effects] == [
        ("mono", start, from_end)]


def test_whole_video_black_and_white_stays_whole():
    assert parse_intent("shuru se bana do, black and white").color_preset == "bw"
    assert parse_intent("black and white karo").color_preset == "bw"


def test_lyric_poster_template_prompt():
    it = parse_intent("Use my song, lyrics on screen, poster style text, text behind the person, stickers of the "
                      "words, zoom and shake, last shot black and white, 9:16")
    assert it.lyrics and it.text_style == "poster" and it.text_behind and it.word_stickers
    assert {"zoom", "shake"} <= set(it.effects) and it.timed_effects[0].from_end


def test_add_thing_comment_is_a_sticker_never_the_sentence():
    if stickers.available():
        assert read_comment("add rose in this video")["emoji"] == "\U0001F339"
        assert read_comment("tree dikhao")["emoji"] == "\U0001F333"
    assert read_comment("kuch accha karo")["understood"] == []  # an instruction is not written on screen
    assert read_comment("Happy birthday")["text"] == "Happy birthday"
