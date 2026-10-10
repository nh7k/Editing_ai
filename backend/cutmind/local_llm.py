"""In-process LLM: a small open model (default Qwen2.5-0.5B-Instruct, Apache-2.0) run with ONNX Runtime.

No separate server (no Ollama), no API key, no GPU: the model is downloaded once from Hugging Face (or read
from a local folder baked into the Docker image) and runs inside the backend process on CPU.
Only `onnxruntime` + `tokenizers` are needed — both are already dependencies of faster-whisper.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

from .config import get_settings
from .llm import LLMError

_EOS_TEXT = ("<|im_end|>", "<|endoftext|>")
MODEL_STANDARD = "onnx-community/Qwen2.5-1.5B-Instruct"  # ~1.8 GB int4, better understanding
MODEL_LITE = "onnx-community/Qwen2.5-0.5B-Instruct"      # ~0.8 GB int4, ~5x faster on small machines
AUTO_MIN_FREE_MB = 3500


def available_ram_mb() -> int | None:
    """Free physical memory in MB (Linux /proc/meminfo, Windows GlobalMemoryStatusEx), None if unknown."""
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="ascii") as fh:
                for line in fh:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        if os.name == "nt":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = _MemStatus()
            stat.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
                return int(stat.ullAvailPhys // (1024 * 1024))
    except Exception:  # noqa: BLE001
        return None
    return None


def resolve_repo(repo: str) -> str:
    """LLM_REPO=auto: the 1.5B model when there is room for it, otherwise the 0.5B lite model."""
    if repo != "auto":
        return repo
    free = available_ram_mb()
    return MODEL_STANDARD if free is None or free >= AUTO_MIN_FREE_MB else MODEL_LITE


def schema_hint(schema: dict | None) -> str:
    """Compact, model-friendly description of a JSON schema (small models choke on raw JSON-schema)."""
    if not schema:
        return ""
    defs = schema.get("$defs", {})
    lines = []
    for name, prop in schema.get("properties", {}).items():
        options = prop.get("anyOf") or [prop]
        kinds: list[str] = []
        for opt in options:
            if "$ref" in opt:
                opt = defs.get(opt["$ref"].split("/")[-1], {})
            if "enum" in opt:
                kinds.append(" | ".join(json.dumps(v) for v in opt["enum"]))
            elif "const" in opt:
                kinds.append(json.dumps(opt["const"]))
            elif opt.get("type") == "array":
                item = opt.get("items", {})
                if "$ref" in item:
                    item = defs.get(item["$ref"].split("/")[-1], {})
                kinds.append(f"list of ({' | '.join(json.dumps(v) for v in item['enum'])})" if "enum" in item else "list")
            elif "type" in opt:
                kinds.append(str(opt["type"]))
        default = f" (default {json.dumps(prop['default'])})" if "default" in prop else ""
        lines.append(f'  "{name}": {" or ".join(kinds) or "any"}{default}')
    return "Reply with one JSON object with these keys:\n{\n" + ",\n".join(lines) + "\n}"


class LocalLLMClient:
    """Greedy decoding with a KV cache over an ONNX decoder exported by Optimum / transformers.js."""

    _lock = threading.Lock()
    _cache: dict[str, tuple[Any, Any, dict]] = {}

    def __init__(self, repo: str | None = None, filename: str | None = None, model_dir: str | None = None,
                 max_new_tokens: int | None = None, threads: int | None = None, settings: Any = None) -> None:
        s = settings or get_settings()
        self.repo = resolve_repo(repo or s.llm_repo)
        self.filename = filename or s.llm_file
        self.model_dir = model_dir if model_dir is not None else s.llm_model_dir
        self.max_new_tokens = max_new_tokens or s.llm_max_new_tokens
        self.threads = threads if threads is not None else s.llm_threads

    # ---- loading ---------------------------------------------------------------------------------
    def _paths(self) -> tuple[Path, Path, Path]:
        if self.model_dir:
            root = Path(self.model_dir)
            model, tok, cfg = root / self.filename, root / "tokenizer.json", root / "config.json"
            if not model.exists():
                raise LLMError(f"model file not found: {model}")
            return model, tok, cfg
        try:
            from huggingface_hub import hf_hub_download

            cfg = Path(hf_hub_download(self.repo, "config.json"))
            tok = Path(hf_hub_download(self.repo, "tokenizer.json"))
            model = Path(hf_hub_download(self.repo, self.filename))
            # external weights (large models) live next to the graph
            try:
                hf_hub_download(self.repo, self.filename + "_data")
            except Exception:  # noqa: BLE001 — most small models have no external data file
                pass
            return model, tok, cfg
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"could not download {self.repo}/{self.filename}: {exc}") from exc

    def load(self) -> tuple[Any, Any, dict]:
        key = f"{self.model_dir or self.repo}/{self.filename}/{self.threads}"
        with self._lock:
            if key not in self._cache:
                import onnxruntime as ort
                from tokenizers import Tokenizer

                model, tok, cfg = self._paths()
                opts = ort.SessionOptions()
                # physical cores is the sweet spot for ORT on CPU (hyper-threads slow it down)
                opts.intra_op_num_threads = self.threads or max(1, (os.cpu_count() or 2) // 2)
                opts.log_severity_level = 3
                session = ort.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])
                self._cache[key] = (session, Tokenizer.from_file(str(tok)), json.loads(cfg.read_text(encoding="utf-8")))
            return self._cache[key]

    # ---- generation --------------------------------------------------------------------------------
    def generate(self, prompt_text: str, prefix: str = "") -> str:
        session, tokenizer, cfg = self.load()
        n_layers = cfg["num_hidden_layers"]
        kv_heads = cfg.get("num_key_value_heads", cfg["num_attention_heads"])
        head_dim = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
        inputs_meta = {i.name: i for i in session.get_inputs()}
        kv_dtype = np.float16 if "float16" in inputs_meta["past_key_values.0.key"].type else np.float32
        eos_ids = {tokenizer.token_to_id(t) for t in _EOS_TEXT} - {None}

        ids = tokenizer.encode(prompt_text + prefix, add_special_tokens=False).ids
        past = {f"past_key_values.{i}.{kv}": np.zeros((1, kv_heads, 0, head_dim), dtype=kv_dtype)
                for i in range(n_layers) for kv in ("key", "value")}
        out_ids: list[int] = []
        step_ids = ids
        total = 0
        text = prefix
        depth, in_str, esc = 0, False, False
        for ch in prefix:  # track brace depth so we can stop right after the JSON object closes
            depth, in_str, esc = _scan(ch, depth, in_str, esc)
        for _ in range(self.max_new_tokens):
            n = len(step_ids)
            feed = {
                "input_ids": np.array([step_ids], dtype=np.int64),
                "attention_mask": np.ones((1, total + n), dtype=np.int64),
                **past,
            }
            if "position_ids" in inputs_meta:
                feed["position_ids"] = np.arange(total, total + n, dtype=np.int64)[None, :]
            outputs = session.run(None, feed)
            logits = outputs[0][0, -1]
            for i in range(n_layers):
                past[f"past_key_values.{i}.key"] = outputs[1 + 2 * i]
                past[f"past_key_values.{i}.value"] = outputs[2 + 2 * i]
            total += n
            nxt = int(np.argmax(logits))
            if nxt in eos_ids:
                break
            out_ids.append(nxt)
            piece = tokenizer.decode([nxt])
            text += piece
            closed = False
            for ch in piece:
                depth, in_str, esc = _scan(ch, depth, in_str, esc)
                if depth == 0 and ch == "}" and not in_str:
                    closed = True
                    break
            if closed:
                break
            step_ids = [nxt]
        return text

    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        # agents whose system prompt already lists the keys don't need the (long) schema hint
        hint = "" if "Keys:" in system else "\n\n" + schema_hint(schema)
        prompt = (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}{hint}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
        try:
            return self.generate(prompt, prefix="{")
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as an LLM failure so agents fall back cleanly
            raise LLMError(f"local model failed: {exc}") from exc


def _scan(ch: str, depth: int, in_str: bool, esc: bool) -> tuple[int, bool, bool]:
    if in_str:
        if esc:
            return depth, True, False
        if ch == "\\":
            return depth, True, True
        if ch == '"':
            return depth, False, False
        return depth, True, False
    if ch == '"':
        return depth, True, False
    if ch == "{":
        return depth + 1, False, False
    if ch == "}":
        return depth - 1, False, False
    return depth, False, False


def local_llm_status(settings: Any = None) -> dict[str, Any]:
    """Is the model available offline / cached? (does not download)"""
    s = settings or get_settings()
    if s.llm_model_dir:
        return {"model": s.llm_model_dir, "file": s.llm_file, "available": (Path(s.llm_model_dir) / s.llm_file).exists()}
    repo = resolve_repo(s.llm_repo)
    try:
        from huggingface_hub import try_to_load_from_cache

        hit = try_to_load_from_cache(repo, s.llm_file)
        cached = isinstance(hit, str) and os.path.exists(hit)
    except Exception:  # noqa: BLE001
        cached = False
    return {"model": repo, "file": s.llm_file, "available": cached, "selection": s.llm_repo,
            "free_ram_mb": available_ram_mb()}
