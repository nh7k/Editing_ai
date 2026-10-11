# Understanding engine v2 — eval (2026-10-11)

"Before" = commit `262c6f6` (the resolver of docs/INTENT_EVAL.md), run in a separate git worktree on the same
corpus. "After" = this work. Corpus: `eval/understanding_corpus.yaml` (1,556 prompts; written by
`eval/understanding_corpus_src.py`). Commands: `eval/run_understanding_eval.py`, `eval/calibration.py`,
`eval/scale_test.py`, `eval/regression_gate.py`, `eval/confusability.py`.

Honesty notes:
- I wrote every hand-written prompt myself (no real-user prompts yet). The headline numbers are the **held-out**
  hand-written set (125), run once at the end. Generated prompts (972) are the skills' own synonyms with machine
  misspellings: the matcher has seen those phrases, so they only test spelling robustness.
- Four corpus labels were corrected during the work (documented in the corpus file): "fade in / fade out" means
  the picture fade (`fade_black`) by an earlier documented decision, and "sabke chehre blur" is the face-blur skill.
  The "before" numbers use the corrected labels too.
- **Silent wrong edit** = a wrong skill applied AND no alternative shown. A wrong best guess shown with one-tap
  alternatives and Undo is counted separately ("wrong applied, alternatives shown").

## Headline — held-out (125 hand-written, run once)

| | before | after |
|---|---|---|
| dead ends | 0 | **0** |
| single-skill top-1 | 87.5 % | 86.5 % (−1 prompt) |
| single-skill top-3 | 92.7 % | **93.8 %** |
| silent wrong edits | 3 | 3 |
| wrong applied, alternatives shown | 0 | 3 (the cost of "act, show, undo") |
| multi-instruction: every understood part applied | 3 / 7 (share 54 %) | **5 / 7 (share 92 %)** |
| relative ("aur thoda", "kam karo", "dobara", "isko hata do") | 0 / 10 | **10 / 10** |
| greeting / question: no edit, an answer | 5 / 6 | **6 / 6** |
| unsupported: nothing applied, closest options shown | 4 / 6 | **6 / 6** |
| latency p50 / p95 | 84 / 241 ms | 68 / 185 ms |

## Dev (459 hand-written) and generated (972)

| | dev before | dev after | generated before | generated after |
|---|---|---|---|---|
| top-1 / top-3 | 90.8 / 96.2 % | 91.6 / 96.7 % | 90.2 / 95.0 % | 90.1 / 96.0 % |
| silent wrong | 7 | 5 | 17 | 8 |
| multi all-applied | 5 / 23 (share 28 %) | 18 / 23 (share 91 %) | — | — |
| relative | 0 / 30 | 29 / 30 | — | — |
| non-edit | 18 / 19 | 19 / 19 | — | — |
| unsupported acted on | 4 | 1 ("car ka colour red karo sirf" → colour pop red: arguably right) | — | — |
| dead ends | 0 | 0 | 0 | 0 |

Latency on this laptop (warm, dev): rules path p50 46 / p95 129 ms (budget 150); retrieval path p50 90 / p95 281
ms (budget 400). A brand-new word can take ~1.6 s once (spelling comparison, cached after).

## Policy calibration (dev, `eval/results/calibration.json`)

| decision | n | top reading right |
|---|---|---|
| apply (no question) | 265 | **98.1 %** |
| act (best guess applied + alternatives) | 41 | 82.9 % |
| choose (one tap) | 61 | 70.5 % (the first chip) |

The raw score alone is NOT calibrated (the 0.8-0.9 score bin was right only 4 / 9 times). The decision combines the
score with the margin to the second reading, the share of the prompt's meaning words left unexplained, "not
available yet" names and the user's own past reactions — that combination is what the table above measures.
Act thresholds from a sweep (`ACT_MIN 0.70`, `ACT_UNEXPLAINED 0.5`): 34 right / 7 wrong acts and 1 unsupported
request acted on; 0.6 would act 47 right but 11 wrong and on 4 unsupported requests.

**What the system can and cannot tell apart (measured):** the share of a prompt's words that no skill explains is
0.45-0.88 for unsupported requests AND for oddly worded supported ones that ended in "choose". So the engine
cannot honestly say "this is not supported" from the words alone; it says "pakka nahi samjha — inme se koi?" and
says "abhi available nahi" only for names on the known not-yet list (4k upscale, face swap of the registry's
"later" names). An earlier version claimed "ye kaam abhi nahi aata" for any far match — removed.

## Accuracy as the catalog grows (`eval/results/scale.json`, retrieval step only)

| skills | flat top-1 / top-3 (hard distractors) | category-first | ms / prompt (flat) |
|---|---|---|---|
| 108 (today) | 85.8 / 96.2 % | 84.9 / 94.5 % | 45 |
| 500 | 79.4 / 91.3 % | 78.3 / 90.1 % | 83 |
| 2,000 | 66.1 / 83.8 % | 67.0 / 82.6 % | 197 |
| 10,000 | 53.6 / 65.5 % | 54.2 / 67.0 % | 834 |

Random distractors: 62.3 / 75.9 % flat at 10,000; category-first only 38.8 / 45.8 %. **The category-first route I
built does not improve accuracy** (it is ~2× faster); the flat scorer degrades from ~500 skills and is too slow at
10,000. At today's 109 skills the engine is in its good range; a 2,000+ catalog needs a better retriever (the
already-shipped multilingual embedding model as a second signal, or per-skill discriminative synonyms) — measured
here, not built.

## Gates

- `eval/regression_gate.py`: per-skill first-try hits (dev + generated) must not drop; baseline 1,213 hits over 108
  skills; it caught one real regression during this work (boomerang's "forward and backward" split on "and").
- `eval/confusability.py`: 173 confused skill pairs, 0 over the limit (6); the worst: `split` ← `crop` 6/62.
- Both run in CI through `tests/integration/test_understanding_gate.py`.

## End to end (real API + FFmpeg)

`tests/integration/test_understanding_e2e.py` — 30 messages in a row on one project (chat and timeline comments),
each output measured (length, colour, brightness, warmth, audio, versions). Passed after fixing 7 real bugs it
found (see CHANGELOG 61). Includes: the white-screen bug with a marker, restore, relative edits, a 5-instruction
message with 2 unsupported parts (the other 3 applied), greeting / question / emoji (no edit), an unsupported
request (no edit, closest options), Devanagari and typo prompts, undo and the alternative chip.
