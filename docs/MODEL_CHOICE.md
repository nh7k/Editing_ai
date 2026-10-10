# Planner model choice (measured on this machine, 2026-10-08)

Machine: Windows 11 laptop, Intel i5-1334U (12 threads), 8 GB RAM (≈1 GB free while the app runs), no GPU.
llama-cpp-python 0.3.36 (CPU wheel), 6 threads, n_ctx 4096, GGUF Q4_K_M, temperature 0, flat JSON schema
(grammar) + value checks. Accuracy = `eval/run_eval.py` on the 67 cases of `eval/cases.yaml` (same path as a chat
message). Cost = `scripts/bench_llm.py` + a separate RAM probe.

## Accuracy (67 cases)
| Setup | Before (old routing) | After (prenormalize + half-understood routing + warm-up) | Paraphrases (not taught to the rules) | LLM calls | JSON valid | Model answer used / rejected by the safety checks |
|---|---|---|---|---|---|---|
| Rules only (no model) | 54/67 (80.6 %) | **60/67 (89.6 %)** | 8/15 | 0 | – | – |
| + Qwen3-0.6B | 57/67 (85.1 %) | **61/67 (91.0 %)** | 9/15 | 23 | 95.7 % | 17 / 5 |
| + Qwen3-1.7B | 56/67 (83.6 %) | 61/67 (91.0 %) | 9/15 | 23 | 100 % | 17 / 4 |
| + Qwen3-4B | 55/67 (82.1 %) | **63/67 (94.0 %)** | 11/15 | 23 | 91.3 % | 18 / 1 |
| + Phi-4-mini | not run (see below) | 62/67 (92.5 %) | 11/15 | 23 | 100 % | 13 / 5 |
| + Qwen3-0.6B, Qwen3-4B when unsure | – | 62/67 (92.5 %) | 10/15 | 29 | – | 17 / 4 |
"Before": the model was only asked about clauses the rules understood nothing of, with no warm-up — the 1.7B and
4B models timed out (25 s) on most first calls. Phi-4-mini's "before" run was stopped because the code had already
changed; it was run once, with the final code.
Devanagari Hindi went 0/4 → 4/4 and typos 2/4 → 4/4 with no model at all (`prenormalize.py`).

## Cost on this CPU
| Model | File | RAM (private, after warm-up) | Load | Warm-up (system prompt into the KV cache) | p50 / p95 per request (warm) | 1 at a time | 5 at once (30 s timeout) | 20 at once (queue 8) |
|---|---|---|---|---|---|---|---|---|
| Qwen3-0.6B | 0.40 GB | 1.5 GB | 1.4 s | 17.5 s | **3.9 s / 16.0 s** | ok | 5/5 ok (17.5 s) | 5 ok, 12 busy (instant), 3 timeouts |
| Qwen3-1.7B | 1.28 GB | 2.0 GB | 2.5 s | 30.1 s | 5.5 s / 17.4 s | ok | 5/5 ok (29.3 s) | 5 ok, 12 busy, 3 timeouts |
| Qwen3-4B | 2.50 GB | 3.2 GB | 40.9 s | 101.6 s | 12.1 s / 35.6 s | ok | 1 ok, 4 timeouts | 3 ok, 12 busy, 5 timeouts |
| Phi-4-mini | 2.49 GB | 2.8 GB | 12.7 s | 60.3 s | 10.1 s / 26.2 s | ok | 2 ok, 3 timeouts | 2 ok, 12 busy, 6 timeouts |

**Where it breaks:** one llama.cpp process answers one request at a time. On this laptop the 0.6B model keeps up
with 5 simultaneous requests; at 20 the bounded queue (8) refuses 12 instantly and the rest wait — every refused or
timed-out request is answered by the rules at once, so nothing hangs. The 4B model already times out with 5 at once.
Only ≈0.35 messages in 1 reach the model (the rules understand the rest), which is why this is enough for small
traffic.

## Recommendation
- **Default (`models.json` → `qwen3-0.6b`):** same accuracy as the 1.7B model at 70 % of its latency and 75 % of
  its RAM; the only one that fits next to the app on an 8 GB laptop and handles 5 simultaneous requests here.
- **On a server with ≥ 8 GB RAM for the model:** `LLM_MODEL_BIG=qwen3-4b` (asked only when the 0.6B answer was
  unusable) or `LLM_MODEL=qwen3-4b` alone for the best accuracy (94 %) if latency of ~12 s per unclear clause is
  acceptable. Run it in llama-server (`docker-compose.yml`, `LLM_GGUF=Qwen3-4B-Q4_K_M.gguf`, `LLM_MEMORY=4g`).
- Qwen3-1.7B and Phi-4-mini are not recommended: no accuracy gain over 0.6B (1.7B) / 4B (Phi) for their cost.
  Both files were deleted after the benchmark (re-download: `python backend/scripts/download_models.py qwen3-1.7b`).

## What the model still gets wrong (4B, after)
"subtitles peele rang mein" → white (wanted yellow); "isko MrBeast jaisa edit karo" timed out; "make the colours
pop" kept the rules' reading (pop text animation); "get rid of the background track" → mute (rejected by the safety
check, since fixed by adding "get rid"/"drop" to the take-away words — NOT re-measured).
