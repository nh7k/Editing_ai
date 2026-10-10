# Learning, reference edits, and the road to a "real" editing agent

## 1. What runs today (tested)

| Piece | What it does | Where |
|---|---|---|
| Hinglish understanding | rules + 36 pro skills + genres/platforms → explicit / inferred-with-reason / unknown; "X mat karo" negations; who to focus on (clothes colour); text in front / behind | `intent.py`, `editorial.py` |
| Taste learning (RL, bandit) | 5 knobs (cut pace, beat-punch strength, B&W rate, text mood, impact hits) × 3 options; Thompson sampling per video type + song feel; rewards from 👍/👎, the next prompt ("thoda slow", "perfect"), hand changes | `learning.py`, `GET /learning` |
| Edit like a reference | measures a finished edit (shots, beat sync z-score, B&W share, colour, flashes, aspect, length), copies it onto raw footage with the same song; explicit words still win | `reference.py`, `POST /projects/{id}/reference` |
| Song-driven editing | cuts / motion / text follow the song's energy and drop | `song.py`, docs/SONG_DRIVEN_EDITING.md |
| Noise removal | RNNoise (`arnndn`) on "noise hata do / awaaz saaf karo"; measured +16 dB speech-to-noise on a noisy test clip | `renderer.finish` |

Simulated user test: a user who only likes faster cuts → after 60 edits the agent picks "faster" in ≥ 16 of the last 20
(`tests/unit/test_learning.py`).

## 1b. The agent learns your words (phrasebook) — and what was measured

* A part of a prompt the rules understand nothing from is no longer silently turned into "auto edit": `/understand`
  returns it as `unclear` with up to 3 "did you mean" suggestions; one tap teaches the phrase (`POST /phrasebook`),
  and its Hinglish word forms (thoda/thode/thodi, feeka/feeke) are understood from then on. Misses are logged
  (`GET /phrasebook`) as data for new rules / fine-tuning.
* Suggestions: paraphrase-multilingual-MiniLM-L12-v2 (Apache-2.0, 115 MB, ~15 ms/sentence on CPU). On 12 held-out
  Hinglish sentences: right answer first 6/12, in the top 3 8/12 — good enough to ASK, not to act alone.
* Tried and rejected: the local Qwen2.5-1.5B (CPU) as a fallback interpreter took 10–26 s per sentence and was wrong on
  6 of 7 test sentences ("purane zamane ki TV jaisa" → zoom + captions). A 1.5B model is too small for Hinglish
  editing requests; option B below (7–8B on a GPU) is the real fix.

## 2. Honest limits

* No large language model runs in the default mode (`PLANNER_MODE=mock`): phrasing outside the patterns can be
  missed. Every miss found is added with a test (10 found and fixed on 2026-10-07 alone).
* The bandit learns *preferences between a few options*; it does not invent new editing techniques.
* Reference transfer copies rhythm, colour, B&W, flashes, aspect, length and song — not text designs, masks or
  transitions it cannot measure. Pixel-identical copies are impossible with different footage.

## 3. Options for a "real agent" (your decision — cost / hardware)

| Option | Quality | Cost | Notes |
|---|---|---|---|
| A. Today: rules + skills (+ optional local Qwen2.5-1.5B on CPU, `PLANNER_MODE=local`) | good on known phrasing | free | small model is weak at open-ended requests |
| B. Hybrid: rules first, an open 7–8B instruct model (Qwen2.5-7B / Llama-3.1-8B, Apache/Llama licence) for anything the rules don't cover, constrained to output our Intent JSON + skill ids | much better on new phrasing | a GPU server (~₹15–40k/month cloud) or a 16 GB+ GPU PC | recommended for the startup; keeps every decision explainable |
| C. B + fine-tuning on our own data: (prompt → Intent/plan) pairs from the app + preference pairs (👍 vs 👎 versions) with DPO | learns *your users'* taste, can go beyond the rules | one-time GPU training (LoRA, hours) | the app already stores prompts, plans, ratings and learned choices = the dataset |
| D. Paid API LLM | best language understanding | per-request cost | excluded so far (no paid APIs) |

"x + x = 3": with B/C the model proposes edits beyond the rules (from skills + its own knowledge), the Reviewer still
checks the rendered file, and the bandit + ratings decide what stays — so the agent can do better than what it was
taught, without breaking what the user explicitly asked.

## 4. Open-source work to build on (read, ideas only unless the licence allows code)

* browser-use/video-use — coding-agent video editing skill (filler / dead-space cuts, grades, subtitles).
* HKUDS/VideoAgent — agentic framework: beat-synced edits, remakes, commentary videos.
* LAVE (LLM agent assistance for video editing) — how an LLM plans edits with users.
* Automatic Non-Linear Video Editing Transfer (Google, CVPR-W 2021) — reference-style transfer (framing, content
  type, speed, lighting) — the idea behind our `reference.py`, extendable with framing / speed matching.
* MovieCuts (ECCV 2022) — 10 professional cut types; AVE dataset — 196k shots with cinematography labels;
  Learning to Cut (ICCV 2021) — ranking cut plausibility from professional edits. Candidates for training a cut scorer.
* OpenVE-3M — instruction-based video editing dataset (for a future instruction model).
