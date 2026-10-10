"""The agent asks about words it doesn't understand, and learns the user's own phrases."""

from __future__ import annotations

import pytest

from cutmind.db import Database
from cutmind.intent import parse_intent
from cutmind.phrasebook import COMMANDS, PhraseBook, normalize, unclear


def test_every_command_is_understood_by_the_parser():
    for cmd in COMMANDS:
        assert parse_intent(cmd).recognized, cmd


@pytest.mark.parametrize("prompt,parts", [
    ("bhai isko 9:16 bana do aur kone kale kar do", ["kone kale kar do"]),  # used to be silently "auto edit"
    ("video ko piche ki taraf chalao", ["video ko piche ki taraf chalao"]),
    ("mast sa edit kar do", []),                 # a real "you decide" request
    ("make it 30 seconds, warm color", []),
    ("bhai please", []),                         # only filler words
])
def test_unclear_parts_are_found(prompt, parts):
    assert unclear(prompt) == parts


def test_teaching_a_phrase(tmp_path):
    pb = PhraseBook(Database(tmp_path / "db.sqlite3"))
    assert pb.resolve("rang thode feeke kar do") is None
    pb.teach("Rang thode feeke kar do", "Faded film look.")
    for variant in ("rang thode feeke kar do", "rang thoda feeka karo", "rang thodi feeki kar do"):
        assert pb.resolve(variant) == "Faded film look.", variant
    assert pb.resolve("rang tez kar do") is None          # the opposite is not matched
    expanded, still = pb.expand("9:16 bana do, rang thoda feeka karo")
    assert still == [] and parse_intent(expanded).color_preset is not None
    with pytest.raises(ValueError):
        pb.teach("x y", "Make it purple.")
    assert normalize("rang thode feeke kar do") == normalize("rang thoda feeka karo")
    # Hinglish spellings of one word: aawaz / awaaz, gungunati / gungunata
    pb.teach("aawaz thodi gungunati si hai saaf karo", "Clean up the audio.")
    assert pb.resolve("awaaz thoda gungunata sa hai saaf karo") == "Clean up the audio."


def test_misses_are_logged_with_suggestions(tmp_path):
    pb = PhraseBook(Database(tmp_path / "db.sqlite3"))
    _, still = pb.expand("mera kutta cute hai, 9:16")
    assert [s["text"] for s in still] == ["mera kutta cute hai"]
    assert all(s["command"] in COMMANDS for x in still for s in x["suggestions"])
    pb.expand("mera kutta cute hai")
    assert pb.misses()[0] == {**pb.misses()[0], "phrase": "mera kutta cute hai", "count": 2}
    _, quiet = pb.expand("mera kutta cute hai", ask=False)  # an edit request: applies what is known, doesn't ask
    assert quiet == [] and pb.misses()[0]["count"] == 2


def test_the_trained_translator_fills_gaps_but_cannot_invent_edits(tmp_path, monkeypatch):
    from cutmind import translator

    answers = {"kone kale kar do": "Vignette effect.", "mera kutta cute hai": "-", "aasmaan me udta hua hathi": "Make it purple and fly."}
    monkeypatch.setattr(translator, "trained_available", lambda: True)
    monkeypatch.setattr(translator.Translator, "translate", lambda self, text: answers.get(text, "-"))
    pb = PhraseBook(Database(tmp_path / "db.sqlite3"))
    expanded, still = pb.expand("9:16 bana do, kone kale kar do, mera kutta cute hai, aasmaan me udta hua hathi")
    assert "vignette" in parse_intent(expanded).effects            # understood through the model
    assert pb.translated == {"kone kale kar do": "Vignette effect."}  # shown to the user
    # "-" (not an editing request) and English the rules don't understand are asked about, never applied
    assert [s["text"] for s in still] == ["mera kutta cute hai", "aasmaan me udta hua hathi"]


def test_every_answer_the_model_was_taught_passes_the_gate():
    import json
    from pathlib import Path

    from cutmind.translator import is_known

    data = Path(__file__).resolve().parents[2] / "training" / "data" / "train.jsonl"
    if not data.exists():
        pytest.skip("training data not generated")
    outs = {json.loads(line)["output"] for line in data.read_text(encoding="utf-8").splitlines()}
    bad = sorted(o for o in outs if o != "-" and not is_known(o))
    assert not bad, bad[:10]


def test_black_and_white_is_one_clause_and_added_commands_never_merge(tmp_path, monkeypatch):
    """Found by a noob-prompt test: "black and white mat karna, starting me zoom" lost its zoom."""
    from cutmind import translator

    assert unclear("15 sec ka short bana, black and white mat karna, starting me zoom") == []
    monkeypatch.setattr(translator, "trained_available", lambda: True)
    monkeypatch.setattr(translator.Translator, "translate", lambda self, text: "No black and white.")
    expanded, _ = PhraseBook(Database(tmp_path / "db.sqlite3")).expand("starting me zoom, kone kale")
    it = parse_intent(expanded)
    assert any(t.effect == "zoom" for t in it.timed_effects) and "zoom" not in it.avoid


def test_translator_may_only_talk_about_what_the_user_mentioned():
    """Seen in the app: "boat wala part zyada dikhao" came back from the model as "Boost the voice"."""
    from cutmind.phrasebook import _topic_supported

    assert not _topic_supported("Boost the voice.", "boat wala part zyada dikhao")
    assert _topic_supported("Boost the voice.", "meri awaaz zyada karo")
    assert _topic_supported("Brighter.", "video bahut andhera hai, thoda ujla karo")
    assert not _topic_supported("Add upbeat music.", "boat wala part zyada dikhao")
