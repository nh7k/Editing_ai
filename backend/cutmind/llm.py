"""LLM plumbing: client protocol + strict JSON with Pydantic validation and retries."""

from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model could not produce valid JSON for the requested schema."""


class LLMClient(Protocol):
    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        """Return the raw model text."""
        ...


def _extract_json(text: str) -> str:
    """Models sometimes wrap JSON in prose or ``` fences — pull out the first object."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def _drop_invalid_fields(model_cls: type[T], data: dict, exc: ValidationError) -> T | None:
    """Keep the valid part of an answer: remove the top-level keys that failed validation (defaults apply)."""
    bad = {str(e["loc"][0]) for e in exc.errors() if e.get("loc")}
    cleaned = {k: v for k, v in data.items() if k not in bad}
    if not cleaned:
        return None
    try:
        return model_cls.model_validate(cleaned)
    except ValidationError:
        return None


def chat_json(client: LLMClient, system: str, user: str, model_cls: type[T], retries: int = 2,
              lenient: bool = False) -> tuple[T, int]:
    """Ask for JSON matching `model_cls`. On invalid output, re-ask with the error (max `retries`).

    `lenient=True` (used for small local models): a well-formed object with some invalid fields is accepted
    with those fields dropped instead of being retried. Returns (validated object, attempts used).
    Raises LLMError when every attempt fails.
    """
    schema = model_cls.model_json_schema()
    prompt = user
    last_error = ""
    for attempt in range(1, retries + 2):
        raw = client.complete(system, prompt, schema)
        data = None
        try:
            data = json.loads(_extract_json(raw))
            if not isinstance(data, dict):
                raise ValueError("answer is not a JSON object")
            return model_cls.model_validate(data), attempt
        except ValidationError as exc:
            if lenient and isinstance(data, dict):
                partial = _drop_invalid_fields(model_cls, data, exc)
                if partial is not None:
                    return partial, attempt
            last_error = str(exc)[:600]
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)[:600]
        prompt = (
            f"{user}\n\nYour previous answer was invalid:\n{raw[:500]}\n\nError: {last_error}\n"
            "Reply again with ONLY one valid JSON object that matches the schema."
        )
    raise LLMError(f"invalid JSON from model after {retries + 1} attempts: {last_error}")
