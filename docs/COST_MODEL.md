# What runs where, and what it costs to serve 100 / 1,000 / 10,000 users

## What runs where
| Part | Where | Cost driver | Measured here (8 GB laptop, i5-1334U 12 threads) |
|---|---|---|---|
| API + job queue | backend container | tiny | – |
| Understanding (rules + prenormalize) | backend, in-process | ~0 | < 0.1 s per message (eval: 67 cases in 0.9 s) |
| Planner LLM (only unclear / half-understood clauses) | `llm` container (llama-server) or in-process llama.cpp | CPU seconds per call | Qwen3-0.6B p50 4.9 s; see MODEL_CHOICE.md for the others |
| Footage analysis | backend worker, once per clip (cached) | CPU, ~30 s per 30 s clip | podcast clip: 30 s total (Vosk 11 s, beats 5 s, …) when the machine is not busy |
| Rendering (FFmpeg) | backend worker — never on the LLM server | CPU, the biggest cost | 15-30 s per edit of a 15-30 s 720p reel; a first edit with person masks up to ~2.5 min |
| Storage | disk / object store | GB per month | a 30 s 720p edit ≈ 4-6 MB per version |

LLM calls per message, from the eval: 0.6B made 23 calls for 67 messages ≈ **0.35 calls per message** (most
messages are understood by the rules alone).

## Assumptions (ESTIMATES — not measured on a server)
- An active user sends 10 edit messages per day; 20 % of registered users are active on a given day.
- Peak hour = 15 % of the day's messages.
- Per message: 0.35 LLM calls × 5 s (0.6B) or × 12 s (1.7B) of one CPU-slot; 1 render ≈ 25 s of 4 vCPUs.
- Server prices are typical public list prices for shared vCPU VPS in 2026 (roughly $5-8 per vCPU-month); check
  current prices before buying — NOT CHECKED in this session.

## Sizing
| Registered users | Messages / day | Peak messages / hour | Renders needed at peak (25 s × 4 vCPU each) | LLM seconds at peak (0.6B) | Suggested setup | Rough monthly cost (estimate) |
|---|---|---|---|---|---|---|
| 100 | 200 | 30 | 30 × 25 s = 12.5 min of one 4-vCPU worker | 30 × 0.35 × 5 s ≈ 1 min | 1 VPS, 4 vCPU / 8 GB (backend + llama-server together) | ~$25-40 |
| 1,000 | 2,000 | 300 | 125 min → 3 render workers (4 vCPU each) | ≈ 9 min → 1 llama-server (2 slots) | 3-4 VPS 4 vCPU / 8 GB, object storage | ~$120-200 |
| 10,000 | 20,000 | 3,000 | 1,250 min → ~25 render workers | ≈ 90 min → 3-4 llama-server replicas | autoscaled render pool, queue, CDN, object storage | ~$1,000-2,000 |

Rendering dominates: the LLM is < 10 % of the compute because most messages never reach it. Moving rendering to
the phone (Media3 Transformer, planned) would remove most of the server cost; the server would then only return
the Edit Plan JSON.

## Limits found by the load test
See `docs/MODEL_CHOICE.md` → "Load test": one llama.cpp process answers one request at a time; with a queue of 8
and a 30 s timeout, requests beyond that get an instant "busy" and the rules answer — the app never hangs.
