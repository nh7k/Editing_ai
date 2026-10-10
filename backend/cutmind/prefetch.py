"""Download every model the backend needs, ahead of time (Docker build / first deploy).

    python -m cutmind.prefetch            # LLM (if PLANNER_MODE=local or --llm) + faster-whisper
"""

from __future__ import annotations

import sys
import time

from .config import get_settings


def main(argv: list[str]) -> int:
    s = get_settings()
    want_llm = s.planner_mode == "local" or "--llm" in argv
    if want_llm:
        from .local_llm import MODEL_LITE, MODEL_STANDARD, LocalLLMClient

        # LLM_REPO=auto picks a model at runtime from free RAM, so ship both
        repos = [MODEL_STANDARD, MODEL_LITE] if s.llm_repo == "auto" and not s.llm_model_dir else [None]
        for repo in repos:
            t = time.time()
            client = LocalLLMClient(repo=repo, settings=s)
            client.load()
            print(f"LLM ready: {s.llm_model_dir or client.repo}/{s.llm_file} ({time.time() - t:.0f}s)")
    if s.enable_transcription:
        from .agents.analyzer import import_faster_whisper

        t = time.time()
        import_faster_whisper().utils.download_model(s.whisper_model)
        print(f"faster-whisper '{s.whisper_model}' ready ({time.time() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
