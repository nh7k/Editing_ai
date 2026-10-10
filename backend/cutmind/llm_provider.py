"""Provider-agnostic planner LLM (100 % free / open source; no Ollama, no paid API).

The model never edits video and never invents styles. It turns ONE unclear part of the user's message into
commands from the command catalog (video_editing_knowledge/commands.yaml) — grammar-constrained, so it can only
answer with known command ids. The deterministic rule parser then reads those commands' phrases. Rendering stays in
the FFmpeg worker; the LLM only ever returns JSON.

Providers (LLM_PROVIDER):
  llamacpp   — llama.cpp in-process (llama-cpp-python), GGUF model kept loaded, JSON-schema → grammar
  llamaserver— llama.cpp's llama-server over its OpenAI-compatible HTTP API (LLM_SERVER_URL), same schema
  rules      — no model: always "nothing to add" (the rule parser alone decides)
  mock       — deterministic stand-in for tests (and failure injection: garbage / timeout / busy)
  auto       — llamacpp when the model file is on disk, else rules
A future on-device provider only needs `generate_json` + `health`.

Production concerns handled here: one model in memory, a bounded queue (busy → rules), a per-request deadline that
stops generation (streaming), a max-token cap, latency / failure counters for /llm/health.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "video_editing_knowledge" / "commands.yaml"
MANIFEST = ROOT / "models.json"


class ProviderError(RuntimeError):
    """The model could not answer usefully (timeout, busy, down, invalid JSON). Callers fall back to rules."""


class ProviderBusy(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    pass


class LLMProvider(Protocol):
    name: str

    def generate_json(self, schema: dict[str, Any], prompt: str, timeout: float, max_tokens: int,
                      system: str = "") -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


# ---- the command catalog and its schema ---------------------------------------------------------------------
@lru_cache(maxsize=1)
def catalog() -> list[dict[str, Any]]:
    return list(yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["commands"])


# allowed values per value type (each one is understood by the rule parser — tests/unit/test_llm_provider.py)
VALUES: dict[str, dict[str, Any]] = {
    "none": {"type": "string", "enum": [""]},
    "seconds": {"type": "string", "enum": [str(n) for n in (5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 45, 60, 90, 120)]},
    "number": {"type": "string", "enum": [str(n) for n in range(1, 11)]},
    "color": {"type": "string", "enum": ["white", "black", "yellow", "red", "blue", "green", "pink", "orange",
                                         "purple", "cyan", "gold"]},
    "mood": {"type": "string", "enum": ["upbeat", "calm", "sad", "romantic", "party", "emotional", "chill"]},
    "aspect": {"type": "string", "enum": ["9:16", "16:9", "1:1"]},
    "platform": {"type": "string", "enum": ["instagram reel", "youtube shorts", "youtube"]},
    "effect": {"type": "string", "enum": ["zoom", "zoom out", "shake", "glitch", "film grain", "vhs", "rgb split",
                                          "flash", "vignette", "blur background", "ghost trail", "old film", "sharpen"]},
    "text": {"type": "string", "maxLength": 30},
    "time": {"type": "string", "maxLength": 10},
}

# worked examples (they teach a small model negation, magnitude and "less/more" — its common mistakes)
EXAMPLES: list[tuple[str, list[tuple[str, str]]]] = [
    ("gaane ki awaaz thodi kam karo", [("music_softer", "")]),
    ("music thoda tez", [("music_louder", "")]),
    ("zoom mat lagao par captions chahiye", [("no_effect", "zoom"), ("captions", "")]),
    ("isko MrBeast jaisa bana do", [("fast_cuts", ""), ("captions", ""), ("effect", "zoom"), ("music", "upbeat"),
                                   ("best_first", "")]),
    ("change the text colour black to white", [("text_color", "white")]),
    ("15 sec ki insta reel", [("duration", "15"), ("platform", "instagram reel")]),
    ("thoda energy daal do", [("faster", ""), ("music", "upbeat")]),
    ("bahut lamba hai", [("shorter", "")]),
    ("purane zamane jaisa", [("color_vintage", "")]),
    ("sirf baat wale hisse rakho, chup wale hata do", [("remove_silence", "")]),
    ("video bahut dheema lag raha hai", [("faster", "")]),
    ("ye to bahut fast hai", [("slower", "")]),
    ("youtube short ke liye", [("platform", "youtube shorts")]),
    ("is sample video jaisa bana do", [("use_reference", "")]),
    ("kuch bhi", []),
    ("hello bhai kaise ho", []),
]


def _example_json(cmds: list[tuple[str, str]]) -> str:
    return json.dumps({"commands": [{"id": i, "value": v} for i, v in cmds], "confidence": 0.9 if cmds else 0.2})


def command_schema(strict: bool = False) -> dict[str, Any]:
    """The answer's shape. Default: ids from the catalog + a short value (checked against the allowed values after
    the model answers — 2x faster to generate than the strict per-command grammar on CPU: 8 s vs 16 s measured).
    `strict=True`: every command with its own allowed values in the grammar (anyOf)."""
    if strict:
        items: dict[str, Any] = {"anyOf": [{"type": "object", "properties": {
            "id": {"type": "string", "enum": [c["id"]]}, "value": VALUES[c.get("value", "none")]},
            "required": ["id", "value"]} for c in catalog()]}
    else:
        items = {"type": "object", "properties": {"id": {"type": "string", "enum": [c["id"] for c in catalog()]},
                                                  "value": {"type": "string", "maxLength": 30}},
                 "required": ["id", "value"]}
    return {
        "type": "object",
        "properties": {"commands": {"type": "array", "maxItems": 6, "items": items}, "confidence": {"type": "number"}},
        "required": ["commands", "confidence"],
    }


def system_prompt() -> str:
    lines = [f"{c['id']}: {c['desc']}" for c in catalog()]
    nl = "\n"
    shots = nl.join(f"{q} => {_example_json(c)}" for q, c in EXAMPLES)
    return (
        "Turn a video editing request (English/Hindi/Hinglish, slang, typos) into editor commands. "
        "Use ONLY these ids:" + nl + nl.join(lines) + nl
        + "Rules: as few commands as needed; never add what was not asked; 'mat', 'nahi', 'don't', 'no' = the "
        "user does NOT want it (use no_effect / no_music / no_captions ...); 'kam', 'less', 'dheere' = less, 'tez', "
        "'zyada', 'more' = more; a request with nothing about editing => no commands, low confidence." + nl
        + "Examples:" + nl + shots
    )


ALIASES = {"last": "last", "aakhri": "last", "akhri": "last", "first": "pehla", "pehla": "pehla", "second": "dusra",
           "dusra": "dusra", "third": "teesra", "teesra": "teesra", "garam": "warm", "safed": "white", "kaala": "black",
           "peela": "yellow", "laal": "red", "lal": "red", "instagram": "instagram reel", "reel": "instagram reel",
           "shorts": "youtube shorts", "youtube short": "youtube shorts", "vertical": "9:16", "square": "1:1",
           "horizontal": "16:9"}


def clean_value(kind: str, value: str) -> str | None:
    """The model's value, checked against what that command allows (None = unusable)."""
    v = re.sub(r"[^\w :'&.-]", "", value or "").strip()[:40]
    if kind == "none":
        return ""
    if kind in ("text", "time"):
        return v or None
    allowed = VALUES[kind].get("enum") or []
    low = ALIASES.get(v.lower(), v.lower())
    if low in allowed:
        return low
    if kind in ("seconds", "number"):
        m = re.search(r"\d+", v)
        return m.group(0) if m and 1 <= int(m.group(0)) <= 600 else None
    found = [(low.rfind(a), a) for a in allowed if a and a in low]
    return max(found)[1] if found else None  # "blacktowhite" → white: the last one named is the one wanted


def commands_to_text(commands: list[dict[str, Any]]) -> str:
    """Commands → the phrases the rule parser understands (unknown ids / values a command does not allow are dropped)."""
    by_id = {c["id"]: c for c in catalog()}
    out = []
    for cmd in commands:
        c = by_id.get(str(cmd.get("id", "")))
        if c is None:
            continue
        kind = c.get("value", "none")
        value = clean_value(kind, str(cmd.get("value") or ""))
        if "{v}" in c["say"]:
            if not value:
                continue
            if c["id"] == "drop_clip":
                value = ALIASES.get(value.lower(), value)
            out.append(c["say"].replace("{v}", value))
        else:
            out.append(c["say"])
    return ". ".join(dict.fromkeys(out))


# ---- providers ---------------------------------------------------------------------------------------------------
class _Stats:
    def __init__(self) -> None:
        self.lat: deque[float] = deque(maxlen=200)
        self.ok = self.failed = self.timeouts = self.busy = 0

    def summary(self) -> dict[str, Any]:
        lat = sorted(self.lat)
        pick = (lambda q: round(lat[min(len(lat) - 1, int(q * len(lat)))], 2)) if lat else (lambda q: None)
        return {"answered": self.ok, "failed": self.failed, "timeouts": self.timeouts, "busy": self.busy,
                "p50_s": pick(0.5), "p95_s": pick(0.95)}


class RulesOnlyProvider:
    """No model: the rule parser alone decides (never fails, never slow)."""

    name = "rules"

    def generate_json(self, schema: dict[str, Any], prompt: str, timeout: float = 0, max_tokens: int = 0,
                      system: str = "") -> dict[str, Any]:
        return {"commands": [], "confidence": 0.0}

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": True, "model": None}


class MockProvider:
    """Deterministic test double. `answers` maps a phrase (lower-case) to the JSON to return; `mode` injects
    failures: "garbage" (invalid JSON), "timeout", "busy"."""

    name = "mock"

    def __init__(self, answers: dict[str, dict[str, Any]] | None = None, mode: str = "ok") -> None:
        self.answers, self.mode, self.calls = answers or {}, mode, 0

    def generate_json(self, schema: dict[str, Any], prompt: str, timeout: float = 5, max_tokens: int = 200,
                      system: str = "") -> dict[str, Any]:
        self.calls += 1
        if self.mode == "timeout":
            raise ProviderTimeout("mock timeout")
        if self.mode == "busy":
            raise ProviderBusy("mock busy")
        if self.mode == "garbage":
            return parse_json("{not json")
        return self.answers.get(prompt.strip().lower(), {"commands": [], "confidence": 0.0})

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": self.mode == "ok", "model": "mock"}


def parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^<think>.*?</think>", "", text, flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1] if start != -1 and end > start else text)
    except (ValueError, TypeError) as exc:
        raise ProviderError(f"invalid JSON from the model: {text[:80]!r}") from exc
    if not isinstance(data, dict):
        raise ProviderError("the model's JSON is not an object")
    return data


class LlamaCppProvider:
    """llama.cpp in-process: one Llama object kept loaded; one generation at a time (a llama context is not
    thread-safe), at most `max_queue` requests waiting — the rest get ProviderBusy (→ rules) instantly."""

    name = "llamacpp"

    def __init__(self, model_path: Path, n_ctx: int = 4096, threads: int | None = None, max_queue: int = 8) -> None:
        self.model_path, self.n_ctx = model_path, n_ctx
        self.threads = threads or max(2, (os.cpu_count() or 4) // 2)
        self.max_queue = max_queue
        self._llm: Any = None
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._waiting = 0
        self._waiting_lock = threading.Lock()
        self.stats = _Stats()
        self.load_error: str | None = None

    def load(self) -> Any:
        with self._load_lock:
            if self._llm is None:
                from llama_cpp import Llama

                t = time.monotonic()
                self._llm = Llama(model_path=str(self.model_path), n_ctx=self.n_ctx, n_threads=self.threads,
                                  n_batch=256, verbose=False)
                self.load_seconds = round(time.monotonic() - t, 2)
            return self._llm

    def warm_up(self) -> float:
        """Load the model and put the (fixed) system prompt into its KV cache, so the first user request does not
        pay ~1300 tokens of prompt reading (25 s+ on a laptop CPU: the 4B model timed out on every first call)."""
        t = time.monotonic()
        self.generate_json(command_schema(), "warm up", timeout=600, max_tokens=24, system=system_prompt())
        self.warm_seconds = round(time.monotonic() - t, 1)
        return self.warm_seconds

    def generate_json(self, schema: dict[str, Any], prompt: str, timeout: float = 20.0, max_tokens: int = 200,
                      system: str = "") -> dict[str, Any]:
        with self._waiting_lock:
            if self._waiting >= self.max_queue:
                self.stats.busy += 1
                raise ProviderBusy(f"{self._waiting} requests already waiting")
            self._waiting += 1
        deadline = time.monotonic() + timeout
        try:
            if not self._lock.acquire(timeout=max(0.0, timeout)):
                self.stats.timeouts += 1
                raise ProviderTimeout("waited too long for the model")
            try:
                llm = self.load()
                t0 = time.monotonic()
                msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt + " /no_think"}]
                parts: list[str] = []
                for chunk in llm.create_chat_completion(
                        messages=msgs, temperature=0.0, max_tokens=max_tokens, stream=True,
                        response_format={"type": "json_object", "schema": schema}):
                    parts.append(chunk["choices"][0]["delta"].get("content") or "")
                    if time.monotonic() > deadline:  # stop generating: the user gets the rules' answer now
                        self.stats.timeouts += 1
                        raise ProviderTimeout(f"no answer within {timeout:.0f}s")
                data = parse_json("".join(parts))
                self.stats.lat.append(time.monotonic() - t0)
                self.stats.ok += 1
                return data
            finally:
                self._lock.release()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — model file missing / broken: degrade, never crash
            self.stats.failed += 1
            self.load_error = str(exc)[:200]
            raise ProviderError(f"llama.cpp failed: {str(exc)[:160]}") from exc
        finally:
            with self._waiting_lock:
                self._waiting -= 1

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": self.model_path.exists() and self.load_error is None,
                "model": self.model_path.name, "loaded": self._llm is not None, "waiting": self._waiting,
                "max_queue": self.max_queue, "threads": self.threads, "error": self.load_error, **self.stats.summary()}


class LlamaServerProvider:
    """llama.cpp's llama-server (run it next to the backend; see docker-compose.yml)."""

    name = "llamaserver"

    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.stats = _Stats()

    def generate_json(self, schema: dict[str, Any], prompt: str, timeout: float = 20.0, max_tokens: int = 200,
                      system: str = "") -> dict[str, Any]:
        import httpx

        t0 = time.monotonic()
        try:
            r = httpx.post(f"{self.url}/v1/chat/completions", timeout=timeout, json={
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt + " /no_think"}],
                "temperature": 0.0, "max_tokens": max_tokens,
                "response_format": {"type": "json_object", "schema": schema}})
        except httpx.TimeoutException as exc:
            self.stats.timeouts += 1
            raise ProviderTimeout(f"llama-server: no answer within {timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            self.stats.failed += 1
            raise ProviderError(f"llama-server unreachable: {exc}") from exc
        if r.status_code == 503:
            self.stats.busy += 1
            raise ProviderBusy("llama-server busy")
        if r.status_code != 200:
            self.stats.failed += 1
            raise ProviderError(f"llama-server HTTP {r.status_code}")
        data = parse_json(r.json()["choices"][0]["message"]["content"])
        self.stats.lat.append(time.monotonic() - t0)
        self.stats.ok += 1
        return data

    def health(self) -> dict[str, Any]:
        import httpx

        try:
            ok = httpx.get(f"{self.url}/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            ok = False
        return {"provider": self.name, "ok": ok, "url": self.url, **self.stats.summary()}


# ---- configuration -------------------------------------------------------------------------------------------
def models_dir() -> Path:
    return Path(os.environ.get("CUTMIND_MODELS_DIR") or ROOT / "models")


def model_path(name: str) -> Path:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))["models"][name]
    return models_dir() / m["file"]


def default_model() -> str:
    return os.environ.get("LLM_MODEL") or json.loads(MANIFEST.read_text(encoding="utf-8"))["default"]


_PROVIDERS: dict[str, LLMProvider] = {}
_PROVIDERS_LOCK = threading.Lock()


def get_provider(kind: str | None = None, model: str | None = None) -> LLMProvider:
    """The configured provider (one instance per kind+model, so a model is loaded once per process)."""
    kind = (kind or os.environ.get("LLM_PROVIDER", "auto")).lower()
    model = model or default_model()
    if kind == "auto":
        kind = "llamacpp" if model_path(model).exists() else "rules"
    key = f"{kind}:{model}"
    with _PROVIDERS_LOCK:
        if key not in _PROVIDERS:
            if kind == "llamacpp":
                _PROVIDERS[key] = LlamaCppProvider(model_path(model), max_queue=int(os.environ.get("LLM_MAX_QUEUE", "8")))
            elif kind == "llamaserver":
                _PROVIDERS[key] = LlamaServerProvider(os.environ.get("LLM_SERVER_URL", "http://127.0.0.1:8080"))
            elif kind == "mock":
                _PROVIDERS[key] = MockProvider()
            else:
                _PROVIDERS[key] = RulesOnlyProvider()
        return _PROVIDERS[key]


def set_provider_for_tests(provider: LLMProvider) -> None:
    """Tests: make `get_provider()` (any kind) return this provider."""
    with _PROVIDERS_LOCK:
        _PROVIDERS.clear()
        for kind in ("auto", "llamacpp", "llamaserver", "rules", "mock"):
            _PROVIDERS[f"{kind}:{default_model()}"] = provider
