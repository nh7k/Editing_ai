"""Hinglish → clear English, so the editing brain (rules + 36 pro skills) can understand any wording.

A small open language model (ONNX, CPU) only TRANSLATES; it never decides the edit. The rule parser + editorial
brain then read the English. That split keeps every decision explainable and lets a 1–4B model do the one thing small
models are good at. Chat templates for the model families tried (Qwen, Gemma, Llama, Phi) are below; the best one
(by tests/benchmark in docs/LEARNING_AND_REAL_AGENT.md) is the default.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

SYSTEM = ("You translate requests for a video editing app from Hindi / Hinglish (Hindi written in English letters) "
          "into clear, simple English editing instructions. Keep numbers, seconds, colours, names and quoted text "
          "exactly. Translate what is asked, nothing more. Answer with the English only, on one line.")
EXAMPLES: list[tuple[str, str]] = [
    ("rang gehre karo aur thoda ujala", "Make the colours more vivid and a bit brighter."),
    ("jahan koi nahi bol raha wo hissa kaat do", "Remove the silent parts where nobody is talking."),
    ("pehle 3 second zoom karo phir black and white", "Zoom in for the first 3 seconds, then black and white."),
    ("gaana mat lagao, captions peele rang me", "No music. Yellow captions."),
    ("screen hilao jab beat aaye", "Shake the camera on every beat."),
]

FAMILIES: dict[str, dict[str, Any]] = {
    "qwen": {"eos": ("<|im_end|>", "<|endoftext|>")},
    "gemma": {"eos": ("<end_of_turn>", "<eos>")},
    "llama": {"eos": ("<|eot_id|>", "<|end_of_text|>")},
    "phi": {"eos": ("<|end|>", "<|endoftext|>")},
}
MODELS: dict[str, tuple[str, str, str]] = {  # name → (repo, onnx file, family)
    "qwen2.5-1.5b": ("onnx-community/Qwen2.5-1.5B-Instruct", "onnx/model_q4.onnx", "qwen"),
    "qwen3-1.7b": ("onnx-community/Qwen3-1.7B-ONNX", "onnx/model_q4.onnx", "qwen"),
    "gemma3-1b": ("onnx-community/gemma-3-1b-it-ONNX", "onnx/model_q4.onnx", "gemma"),
    "llama3.2-3b": ("onnx-community/Llama-3.2-3B-Instruct-ONNX", "onnx/model_q4.onnx", "llama"),
    "phi4-mini": ("onnx-community/Phi-4-mini-instruct-ONNX", "onnx/model_q4.onnx", "phi"),
    "qwen3-4b": ("onnx-community/Qwen3-4B-Instruct-2507-ONNX", "onnx/model_q4.onnx", "qwen"),
}
# the model trained on Colab (training/finetune_translator.ipynb), unzipped here
TRAINED_DIR = Path(__file__).resolve().parent.parent / "assets" / "models" / "translator"
MODELS["trained"] = (str(TRAINED_DIR), "onnx/model_q4.onnx", "qwen")
DEFAULT_MODEL = os.environ.get("TRANSLATOR_MODEL", "trained")


# What the trained model may answer: only the sentences it was taught (training/make_hinglish_dataset.py). Anything
# else (a made-up sentence) is rejected, so a model mistake can't sneak an edit in through loose keyword matches.
_COLOURS = "red|yellow|green|blue|white|black"
KNOWN_PATTERNS = [re.compile(x) for x in (
    r"\d+ seconds\.", r"Strong zoom in for the first \d+ seconds\.", r"Black and white for the last \d+ seconds\.",
    rf"Focus on the person in ({_COLOURS}) shirt, blur the rest\.", rf"({_COLOURS.title()}) captions\.")]


def known_sentences() -> set[str]:
    from .phrasebook import COMMANDS

    return set(COMMANDS) | {"Cut on the beat.", "Reverse order.", "Play the video backwards.", "Person zoom effect.",
                            "No black and white.", "No zoom in.", "Faded film look.", "Old movie black and white look.",
                            "Strong zoom in for the first 3 seconds."}


def is_known(english: str) -> bool:
    """Every sentence of the model's answer is one it was taught."""
    sentences = re.findall(r"[^.]+\.", english.strip())
    if not sentences or "".join(sentences).replace(" ", "") != english.strip().replace(" ", ""):
        return False
    known = known_sentences()
    return all(x.strip() in known or any(p.fullmatch(x.strip()) for p in KNOWN_PATTERNS) for x in sentences)


def trained_available() -> bool:
    if os.environ.get("CUTMIND_TRANSLATOR", "auto").lower() in ("off", "0", "false"):
        return False  # switched off (tests, or a server without the RAM for it)
    return (TRAINED_DIR / "onnx" / "model_q4.onnx").exists() and (TRAINED_DIR / "tokenizer.json").exists()


def chat_prompt(family: str, system: str, shots: list[tuple[str, str]], user: str, think_block: bool = False) -> str:
    if family == "qwen":
        s = f"<|im_start|>system\n{system}<|im_end|>\n"
        for u, a in shots:
            s += f"<|im_start|>user\n{u}<|im_end|>\n<|im_start|>assistant\n{a}<|im_end|>\n"
        # Qwen3: an empty think block = answer directly (no long reasoning on a CPU); Qwen2.5 has none
        think = "<think>\n\n</think>\n\n" if think_block else ""
        return s + f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{think}"
    if family == "gemma":
        s = "<bos>"
        first = True
        for u, a in [*shots, (user, None)]:
            text = f"{system}\n\n{u}" if first else u
            first = False
            s += f"<start_of_turn>user\n{text}<end_of_turn>\n<start_of_turn>model\n"
            if a is not None:
                s += f"{a}<end_of_turn>\n"
        return s
    if family == "llama":
        s = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
        for u, a in shots:
            s += (f"<|start_header_id|>user<|end_header_id|>\n\n{u}<|eot_id|>"
                  f"<|start_header_id|>assistant<|end_header_id|>\n\n{a}<|eot_id|>")
        return s + f"<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    if family == "phi":
        s = f"<|system|>{system}<|end|>"
        for u, a in shots:
            s += f"<|user|>{u}<|end|><|assistant|>{a}<|end|>"
        return s + f"<|user|>{user}<|end|><|assistant|>"
    raise ValueError(family)


# seconds one translation may take (the app waits for it inside a chat message)
TIME_BUDGET = float(os.environ.get("CUTMIND_TRANSLATE_SECONDS", "6"))


class Translator:
    _lock = threading.Lock()
    _loaded: dict[str, tuple[Any, Any, dict]] = {}

    def __init__(self, name: str = DEFAULT_MODEL, max_new_tokens: int = 48) -> None:
        self.name = name
        self.repo, self.file, self.family = MODELS[name]
        self.max_new_tokens = max_new_tokens

    def load(self) -> tuple[Any, Any, dict]:
        with self._lock:
            if self.name not in self._loaded:
                import onnxruntime as ort
                from huggingface_hub import hf_hub_download, list_repo_files
                from tokenizers import Tokenizer

                local = Path(self.repo)
                if local.is_dir():  # a model folder on disk (the one trained on Colab)
                    model = str(local / self.file)
                    tok = Tokenizer.from_file(str(local / "tokenizer.json"))
                    cfg = json.loads((local / "config.json").read_text(encoding="utf-8"))
                else:
                    files = list_repo_files(self.repo)
                    for extra in (f for f in files if f.startswith(self.file + "_data")):
                        hf_hub_download(self.repo, extra)  # external weights live next to the graph
                    model = hf_hub_download(self.repo, self.file)
                    tok = Tokenizer.from_file(hf_hub_download(self.repo, "tokenizer.json"))
                    cfg = json.loads(Path(hf_hub_download(self.repo, "config.json")).read_text(encoding="utf-8"))
                cfg = cfg.get("text_config", cfg)
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
                opts.log_severity_level = 3
                sess = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
                self._loaded[self.name] = (sess, tok, cfg)
            return self._loaded[self.name]

    def generate(self, prompt: str) -> str:
        sess, tok, cfg = self.load()
        meta = {i.name: i for i in sess.get_inputs()}
        n_layers = cfg["num_hidden_layers"]
        kv_heads = cfg.get("num_key_value_heads", cfg["num_attention_heads"])
        head_dim = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
        kv_dtype = np.float16 if "float16" in meta["past_key_values.0.key"].type else np.float32
        eos = {tok.token_to_id(t) for t in FAMILIES[self.family]["eos"]} - {None}
        ids = tok.encode(prompt, add_special_tokens=False).ids
        past = {f"past_key_values.{i}.{kv}": np.zeros((1, kv_heads, 0, head_dim), dtype=kv_dtype)
                for i in range(n_layers) for kv in ("key", "value")}
        step, total, out = ids, 0, []
        t0 = time.monotonic()
        for _ in range(self.max_new_tokens):
            if time.monotonic() - t0 > TIME_BUDGET:
                return ""  # a chat message must not wait on a rambling answer: the rules / "samajh nahi aaya" take over
            feed: dict[str, Any] = {"input_ids": np.array([step], dtype=np.int64),
                                    "attention_mask": np.ones((1, total + len(step)), dtype=np.int64), **past}
            if "position_ids" in meta:
                feed["position_ids"] = np.arange(total, total + len(step), dtype=np.int64)[None, :]
            if "num_logits_to_keep" in meta:
                feed["num_logits_to_keep"] = np.array(1, dtype=np.int64)
            res = sess.run(None, feed)
            for i in range(n_layers):
                past[f"past_key_values.{i}.key"], past[f"past_key_values.{i}.value"] = res[1 + 2 * i], res[2 + 2 * i]
            total += len(step)
            nxt = int(np.argmax(res[0][0, -1]))
            if nxt in eos:
                break
            out.append(nxt)
            if "\n" in tok.decode(out[-1:]) and tok.decode(out).strip():
                break
            step = [nxt]
        return tok.decode(out).strip().split("\n")[0].strip()

    _memo: dict[tuple[str, str], str] = {}  # the app asks twice per message (/understand, then /edit): ~5 s each

    def translate(self, text: str) -> str:
        key = (self.name, text.strip().lower())
        if key in self._memo:
            return self._memo[key]
        if self.name == "trained":  # fine-tuned: same plain chat format as in training, no examples needed
            prompt = (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n"
                      "<|im_start|>assistant\n")
            out = self.generate(prompt)
        else:
            out = self.generate(chat_prompt(self.family, SYSTEM, EXAMPLES, text, think_block="qwen3" in self.name))
        if len(self._memo) > 500:
            self._memo.clear()
        self._memo[key] = out
        return out
