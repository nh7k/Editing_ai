"""The provider-agnostic LLM layer: catalog ↔ rule parser, schema, router safety and fallbacks (MockProvider —
no model needed)."""

import pytest

from cutmind import llm_router
from cutmind.intent import parse_intent
from cutmind.llm_provider import (VALUES, MockProvider, ProviderError, RulesOnlyProvider, catalog, command_schema,
                                  commands_to_text, parse_json, set_provider_for_tests, system_prompt)


@pytest.fixture(autouse=True)
def _reset():
    yield
    set_provider_for_tests(RulesOnlyProvider())


def test_every_command_and_every_allowed_value_is_understood_by_the_rules():
    for c in catalog():
        vals = VALUES[c.get("value", "none")].get("enum") or [str(c.get("example", "x"))]
        for v in vals:
            text = commands_to_text([{"id": c["id"], "value": v}])
            assert text and not parse_intent(text).is_empty(), (c["id"], v, text)


def test_schema_only_allows_catalog_ids_and_typed_values():
    items = command_schema(strict=True)["properties"]["commands"]["items"]["anyOf"]
    assert len(items) == len(catalog())
    colour = next(i for i in items if i["properties"]["id"]["enum"] == ["text_color"])
    assert "white" in colour["properties"]["value"]["enum"]
    assert "text_color" in system_prompt() and "mat" in system_prompt()


def test_commands_to_text_drops_unknown_ids_and_missing_values():
    assert commands_to_text([{"id": "nope", "value": ""}, {"id": "duration", "value": ""}]) == ""
    assert commands_to_text([{"id": "duration", "value": "15"}]) == "15 second ka video"


def test_parse_json_strips_think_and_rejects_garbage():
    assert parse_json('<think>x</think>{"commands": [], "confidence": 0.1}')["confidence"] == 0.1
    with pytest.raises(ProviderError):
        parse_json("{not json")


def _router_with(answers=None, mode="ok"):
    p = MockProvider(answers, mode)
    set_provider_for_tests(p)
    return p


def test_router_uses_a_good_answer():
    _router_with({"isko mrbeast jaisa bana do": {"commands": [{"id": "fast_cuts", "value": ""},
                                                             {"id": "captions", "value": ""}], "confidence": 0.8}})
    text = llm_router.understand_phrase("isko MrBeast jaisa bana do")
    assert text and parse_intent(text).captions and parse_intent(text).fast_cuts


def test_router_rejects_doing_the_opposite_of_a_negation():
    _router_with({"glitch effect mat daalna": {"commands": [{"id": "effect", "value": "glitch"}], "confidence": 0.9}})
    assert llm_router.understand_phrase("glitch effect mat daalna") is None
    assert "rejected" in llm_router.last_trace[-1]["result"]


def test_router_rejects_removing_what_nobody_asked_to_remove():
    _router_with({"subtitles yellow mein": {"commands": [{"id": "no_captions", "value": ""}], "confidence": 0.9}})
    assert llm_router.understand_phrase("subtitles yellow mein") is None


def test_router_ignores_low_confidence_and_survives_garbage_timeout_busy():
    _router_with({"kuch bhi": {"commands": [{"id": "auto_edit", "value": ""}], "confidence": 0.2}})
    assert llm_router.understand_phrase("kuch bhi") is None
    for mode in ("garbage", "timeout", "busy"):
        _router_with(mode=mode)
        assert llm_router.understand_phrase("isko mast bana do") is None  # never raises


def test_rules_provider_means_no_model_call():
    set_provider_for_tests(RulesOnlyProvider())
    assert llm_router.understand_phrase("anything") is None


def test_values_are_checked_after_the_model_answers():
    from cutmind.llm_provider import clean_value
    assert clean_value("color", "Peela") == "yellow" and clean_value("color", "sky") is None
    assert clean_value("seconds", "30 sec") == "30" and clean_value("platform", "shorts") == "youtube shorts"
    assert commands_to_text([{"id": "text_color", "value": "sky"}]) == ""  # not a colour: dropped
    assert commands_to_text([{"id": "text_color", "value": "blacktowhite"}]) == "text white karo"  # the last one named
    assert commands_to_text([{"id": "drop_clip", "value": "aakhri"}]) == "last clip hata do"
    flat = command_schema()["properties"]["commands"]["items"]
    assert "text_color" in flat["properties"]["id"]["enum"]


def test_router_never_rebuilds_the_edit_for_a_small_ask():
    # live with Qwen3-0.6B: "gaane ki awaaz thodi dheemi kar do" → style_podcast rebuilt the user's whole edit
    _router_with({"gaane ki awaaz thodi dheemi kar do": {"commands": [{"id": "style_podcast", "value": ""}],
                                                         "confidence": 0.9}})
    assert llm_router.understand_phrase("gaane ki awaaz thodi dheemi kar do") is None
    assert "style" in llm_router.last_trace[-1]["result"]


def test_router_rejects_answers_about_a_topic_the_user_never_mentioned():
    _router_with({"gaane ki awaaz thodi dheemi kar do": {"commands": [{"id": "captions", "value": ""}],
                                                         "confidence": 0.9}})
    assert llm_router.understand_phrase("gaane ki awaaz thodi dheemi kar do") is None
    _router_with({"isko mrbeast jaisa bana do": {"commands": [{"id": "style_fan_edit", "value": ""}], "confidence": 0.9}})
    assert llm_router.understand_phrase("isko MrBeast jaisa bana do")  # a style word is there: allowed
