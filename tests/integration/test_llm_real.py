"""The REAL planner model (llama.cpp, GGUF) — skipped when the model file is not downloaded
(python backend/scripts/download_models.py). Checks the production guarantees, not exact answers."""

from __future__ import annotations

import os

import pytest

from cutmind.llm_provider import (LlamaCppProvider, ProviderBusy, ProviderTimeout, command_schema, commands_to_text,
                                  default_model, model_path, system_prompt)

pytestmark = pytest.mark.integration
MODEL = os.environ.get("LLM_TEST_MODEL", "qwen3-0.6b")


@pytest.fixture(scope="module")
def provider():
    if not model_path(MODEL).exists():
        pytest.skip(f"{MODEL} not downloaded")
    p = LlamaCppProvider(model_path(MODEL), max_queue=1)
    p.warm_up()
    return p


def test_answers_are_valid_catalog_json(provider):
    d = provider.generate_json(command_schema(), "awaaz saaf karo", timeout=60, max_tokens=120, system=system_prompt())
    assert isinstance(d["commands"], list) and isinstance(d["confidence"], (int, float))
    commands_to_text(d["commands"])  # never raises, unknown ids are dropped


def test_deadline_stops_generation(provider):
    with pytest.raises(ProviderTimeout):
        provider.generate_json(command_schema(), "isko MrBeast jaisa edit karo aur bahut saare effects", timeout=0.3,
                               max_tokens=160, system=system_prompt())


def test_queue_limit_answers_busy_instantly(provider):
    import threading

    errors: list[Exception] = []

    def call() -> None:
        try:
            provider.generate_json(command_schema(), "thoda energy daal do", timeout=60, max_tokens=60,
                                   system=system_prompt())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    th = [threading.Thread(target=call) for _ in range(3)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    assert any(isinstance(e, ProviderBusy) for e in errors)  # max_queue=1: the extra ones are refused at once
    assert default_model()
