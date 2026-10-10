"""JSON-from-LLM handling: validation, retries with the error, fence extraction."""

import pytest
from pydantic import BaseModel

from cutmind.llm import LLMError, chat_json
from cutmind.local_llm import LocalLLMClient, schema_hint


class Out(BaseModel):
    color: str
    level: int


class Loose(BaseModel):
    color: str
    level: int = 0


class Scripted:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user, schema=None):
        self.prompts.append(user)
        return self.replies.pop(0)


def test_valid_first_try():
    obj, tries = chat_json(Scripted('{"color": "warm", "level": 2}'), "s", "u", Out)
    assert obj.level == 2 and tries == 1


def test_fenced_and_chatty_json_is_extracted():
    obj, _ = chat_json(Scripted('Here you go:\n```json\n{"color": "cool", "level": 1}\n```'), "s", "u", Out)
    assert obj.color == "cool"


def test_retry_sends_error_back():
    llm = Scripted('{"color": "warm"}', '{"color": "warm", "level": 3}')
    obj, tries = chat_json(llm, "s", "u", Out)
    assert tries == 2 and obj.level == 3
    assert "invalid" in llm.prompts[1] and "level" in llm.prompts[1]


def test_gives_up_after_retries():
    with pytest.raises(LLMError, match="after 3 attempts"):
        chat_json(Scripted("nope", "still nope", "{bad"), "s", "u", Out, retries=2)


def test_missing_local_model_raises_llm_error(tmp_path):
    client = LocalLLMClient(model_dir=str(tmp_path / "no-model"), filename="model.onnx")
    with pytest.raises(LLMError, match="model file not found"):
        client.complete("s", "u")


def test_lenient_mode_keeps_valid_fields():
    obj, _ = chat_json(Scripted('{"color": "warm", "level": "lots"}'), "s", "u", Loose, lenient=True)
    assert obj.color == "warm" and obj.level == 0
    with pytest.raises(LLMError):
        chat_json(Scripted('{"level": "x"}', '{"level": "y"}', '{"level": "z"}'), "s", "u", Loose, lenient=True)


def test_schema_hint_lists_enums():
    hint = schema_hint(Loose.model_json_schema())
    assert '"color": string' in hint and '"level": integer (default 0)' in hint


def test_auto_model_selection_by_free_ram(monkeypatch):
    import cutmind.local_llm as ll

    monkeypatch.setattr(ll, "available_ram_mb", lambda: 8000)
    assert ll.resolve_repo("auto") == ll.MODEL_STANDARD
    monkeypatch.setattr(ll, "available_ram_mb", lambda: 1500)
    assert ll.resolve_repo("auto") == ll.MODEL_LITE
    monkeypatch.setattr(ll, "available_ram_mb", lambda: None)  # unknown → standard
    assert ll.resolve_repo("auto") == ll.MODEL_STANDARD
    assert ll.resolve_repo("org/custom") == "org/custom"
