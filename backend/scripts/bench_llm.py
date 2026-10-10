"""Benchmark the planner GGUF models on THIS machine: load time, RAM, latency, JSON validity, and a concurrency
load test (N simultaneous requests through the production provider: bounded queue + per-request timeout).

    python scripts/bench_llm.py qwen3-1.7b qwen3-4b
    python scripts/bench_llm.py qwen3-1.7b --load 1,5,20 --timeout 30

Accuracy is measured by eval/run_eval.py (same prompts the app sees); this script measures cost. Writes
eval/results/bench-<model>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cutmind.llm_provider import (LlamaCppProvider, ProviderBusy, ProviderError, ProviderTimeout,  # noqa: E402
                                  command_schema, model_path, system_prompt)

PROMPTS = ["gaane ki awaaz thodi dheemi kar do", "colour thoda garam karo", "subtitles peele rang mein",
           "aakhri wala video nikal do", "awaaz saaf karo", "isko MrBeast jaisa edit karo",
           "make the colours pop", "get rid of the background track", "video bahut dheema lag raha hai",
           "make it feel like an old vhs tape"]


def rss_mb() -> float:
    """Private memory of this process in MB (what the model + its KV cache really take; a memory-mapped model's
    working set can look small when Windows pages it out)."""
    if os.name == "nt":
        import subprocess

        out = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {os.getpid()}).PrivateMemorySize64"],
                             capture_output=True, text=True).stdout.strip()
        return int(out) / 1e6 if out.isdigit() else 0.0
    with open("/proc/self/status", encoding="ascii") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1e3
    return 0.0


def pct(xs: list[float], q: float) -> float | None:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2) if xs else None


def bench(name: str, loads: list[int], timeout: float) -> dict:
    sysp, schema = system_prompt(), command_schema()
    base = rss_mb()
    p = LlamaCppProvider(model_path(name), max_queue=8)
    t = time.monotonic()
    p.load()
    load_s = time.monotonic() - t
    ram = rss_mb() - base
    first_t = time.monotonic()
    p.generate_json(schema, "warm up", timeout=600, max_tokens=120, system=sysp)  # system prompt into the KV cache
    first = time.monotonic() - first_t
    lat, valid = [], 0
    for q in PROMPTS:
        t = time.monotonic()
        try:
            d = p.generate_json(schema, q, timeout=600, max_tokens=160, system=sysp)
            valid += isinstance(d.get("commands"), list)
        except ProviderError:
            pass
        lat.append(time.monotonic() - t)
        print(f"  {name} {lat[-1]:5.1f}s {q}", flush=True)
    peak = rss_mb() - base
    load_test = []
    for n in loads:
        res: list[str] = []
        times: list[float] = []

        def one(i: int) -> None:
            t0 = time.monotonic()
            try:
                p.generate_json(schema, PROMPTS[i % len(PROMPTS)], timeout=timeout, max_tokens=160, system=sysp)
                res.append("ok")
                times.append(time.monotonic() - t0)
            except ProviderBusy:
                res.append("busy")
            except ProviderTimeout:
                res.append("timeout")
            except ProviderError:
                res.append("error")

        t0 = time.monotonic()
        th = [threading.Thread(target=one, args=(i,)) for i in range(n)]
        for x in th:
            x.start()
        for x in th:
            x.join()
        row = {"concurrent": n, "ok": res.count("ok"), "busy_rejected": res.count("busy"),
               "timed_out": res.count("timeout"), "errors": res.count("error"), "wall_s": round(time.monotonic() - t0, 1),
               "p95_ok_s": pct(times, 0.95)}
        load_test.append(row)
        print("  load", row, flush=True)
    return {"model": name, "file": model_path(name).name, "size_gb": round(model_path(name).stat().st_size / 1e9, 2),
            "load_s": round(load_s, 1), "ram_mb_after_load": round(ram), "ram_mb_peak": round(peak),
            "first_request_s": round(first, 1), "p50_s": round(statistics.median(lat), 2), "p95_s": pct(lat, 0.95),
            "json_valid_rate": round(valid / len(PROMPTS), 2), "threads": p.threads, "load_test": load_test,
            "timeout_s": timeout, "max_queue": p.max_queue}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--load", default="1,5,20")
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args()
    for m in a.models:
        r = bench(m, [int(x) for x in a.load.split(",") if x], a.timeout)
        out = ROOT.parent / "eval" / "results" / f"bench-{m}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(json.dumps(r, indent=1), flush=True)


if __name__ == "__main__":
    main()
