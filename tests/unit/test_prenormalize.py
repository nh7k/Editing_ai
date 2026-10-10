"""Before the rules: Devanagari → Hinglish, typo fixes, coverage → the half-understood route to the planner model."""

import pytest

from cutmind.db import Database
from cutmind.intent import parse_intent
from cutmind.llm_provider import MockProvider, RulesOnlyProvider, set_provider_for_tests
from cutmind.phrasebook import PhraseBook
from cutmind.prenormalize import coverage, normalize


@pytest.fixture(autouse=True)
def _reset():
    yield
    set_provider_for_tests(RulesOnlyProvider())


@pytest.mark.parametrize("raw,fixed", [
    ("captins lagao", "captions lagao"), ("blak and wite", "black and white"), ("remov silense", "remove silence"),
    ("subtitles peele rang mein", "subtitles peele rang mein"),  # Hinglish colour word: never "corrected"
    ("thoda slow karo", "thoda slow karo"),
])
def test_typos(raw, fixed):
    assert normalize(raw) == fixed


def test_devanagari_becomes_hinglish_the_rules_read():
    assert parse_intent(normalize("गाना हटा दो")).no_music


def test_coverage_flags_half_understood_clauses():
    assert coverage("gaane ki awaaz thodi dheemi kar do") < 0.6
    assert coverage("30 sec ka video bana do warm color ke saath") >= 0.6
    assert coverage("silence hata aur captions laga") == 1.0


def test_half_understood_clause_is_replaced_by_the_models_reading(tmp_path):
    set_provider_for_tests(MockProvider({"gaane ki awaaz thodi dheemi kar do": {
        "commands": [{"id": "music_softer", "value": ""}], "confidence": 0.9}}))
    out, _ = PhraseBook(Database(tmp_path / "d.sqlite3")).expand("gaane ki awaaz thodi dheemi kar do", ask=False)
    it = parse_intent(out)
    assert it.music_volume is not None and it.music_volume <= 0.2 and it.music_mood != "upbeat", out


def test_fully_understood_message_never_calls_the_model(tmp_path):
    mock = MockProvider()
    set_provider_for_tests(mock)
    out, _ = PhraseBook(Database(tmp_path / "d.sqlite3")).expand("silence hata aur captions laga", ask=False)
    assert mock.calls == 0 and out == "silence hata aur captions laga"


def test_model_down_keeps_the_rules_reading(tmp_path):
    set_provider_for_tests(MockProvider(mode="timeout"))
    out, _ = PhraseBook(Database(tmp_path / "d.sqlite3")).expand("gaane ki awaaz thodi dheemi kar do", ask=False)
    assert out == "gaane ki awaaz thodi dheemi kar do"
