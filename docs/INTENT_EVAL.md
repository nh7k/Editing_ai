# Intent eval — before / after the resolver (2026-10-10)

Corpus: `eval/intent_corpus.yaml` (written by `eval/intent_corpus_src.py`): **420 noob phrasings** for the 40
most-used skills + restore / white requests, with typos, Hinglish spellings, Devanagari, slang, filler words,
"yaha" with a marker, trailing "normal jaisa tha" clauses. Every 4th phrase of each skill is **held-out** (85),
never looked at while tuning; the other 335 (+ the 2 original-bug items) are **dev**.

Honesty notes:
- I wrote the corpus myself, after writing the restore / white synonyms — those 28 items are easier for my code
  than real users' words would be. A native speaker's corpus would be a fairer test (see risks).
- "Before" = the code of commit `27d0a21` (before this work), run in a separate git worktree on the same corpus
  (`eval/results/intent_baseline_HEAD.json`). Not the "before" line printed by `run_intent_eval.py`, which already
  includes the new synonyms and the fixed `nearest()`.
- Dev was used for tuning (synonyms for dev failures, thresholds). Held-out was run once, at the end.
- **Silent wrong edit** = the system applies a skill without asking, and it is the wrong one. This is the worst
  outcome; asking (chips) when unsure is fine.

## Results

| set | metric | before (27d0a21) | after |
|---|---|---|---|
| dev (335) | top-1 | 64.2 % | **91.3 %** |
| dev | top-3 | 70.1 % | **96.4 %** |
| dev | applied without asking | 247 | 264 |
| dev | silent wrong edits | 42 (12.5 %) | **7 (2.1 %)** |
| **held-out (85)** | **top-1** | **71.8 %** | **85.9 %** |
| **held-out** | **top-3** | **75.3 %** | **91.8 %** |
| held-out | silent wrong edits | 8 | **3** |
| held-out | empty answer | — | 1 ("yaha whitish kar do") → fixed after the run (never empty now); the held-out was not re-tuned |
| resolver latency (warm, dev) | p50 / p95 | — | 14 ms / 97 ms |
| `/understand` on an unclear message (after warm-up) | | 21-28 s (cold first: 36-42 s) | **~2 s** |

No-regression gate (the previous eval): YAML examples of the original 105 skills **763/840 — unchanged**;
held-out `tier1_heldout.yaml` **92/110 — unchanged**; multi-instruction 28/30 — unchanged. New skills' examples:
white_screen_card 7/8, brighten_to_white 7/8, restore_normal 5/8.

## The original bug, now (real trace)

`yaha screen white kar do nomal jasia tha`, marker 4.3 s, black-and-white on 3.0–5.5 s:

```
words      yaha screen white kar do normal jaisa tha      (nomal → normal, jasia → jaisa)
exact      flash (from "screen white karo") — 55 % of the meaning words unexplained → not applied blindly
scores     restore_normal 1.04, flash 1.02, white_screen_card 0.99, brighten_to_white 0.94
decision   choose (margin 0.02 < 0.30)
chips      ★ Yaha ka effect hata ke normal karo (black and white hatega)  → restore_normal 3.0-5.5 s
             4.3s par white flash (0.3 sec)                              → flash at 4.3 s
             4.3s par 1 sec safed screen                                 → white_screen_card at 4.3 s
```

Same words, nothing on screen there: ★ white flash at 4.3 s, safed screen, screen bright / white.
Tapping the restore chip (tested end to end in `tests/integration/test_intent_api.py` with a real render): the
black and white is gone at 4.3 s, the frame is in colour again, the length is unchanged, undo returns the exact
previous plan. In the running app (web build, chat box, no marker) the same sentence showed three chips; I tapped
"white flash": its tool job ran to "done" and the pick was stored. The restore chip was NOT tapped in the app UI
itself (only through the API test above), and the timeline-comment box was not driven through the UI.

## Calibration

`eval/results/intent_sweep.json` (dev): applying directly at APPLY_MIN 0.8 with margin 0.05 → 297 applied, 19
silent wrong; margin 0.3 → 264 applied, 7 silent wrong. Chosen: **APPLY_MIN 0.8, MARGIN 0.3, CHOOSE_MIN 0.3**.
For exact matches: applied only when < 40 % of the prompt's meaning words are unexplained (dev: silent wrong 42 → 12
from this rule alone). Two scoring changes were tried and **rejected** because dev got worse: a stronger penalty for
one-word synonyms (top-1 0.887 vs 0.913) and merging meaning-alike words ("colour" = "rang", "dheere" = "slow" —
"thanda colour" went to colour pop).

## Still weak (per skill, dev top-1)

duck_music 4/8, export_preset 4/8, audio_fade 6/8, saturation 6/8, title_card 6/8, vintage_faded 6/8. Some
"failures" are label disagreements with documented decisions ("status" = WhatsApp Status 9:16, "90s look" = VHS,
"hollywood look" = teal & orange). The 20 worst cases with what was chosen: docs/FAILED_PROMPTS_FOR_REVIEW.md §3.

## Not done (and why)

- Embedding-model and tiny-LLM fallbacks for the resolver: not added. The failure was a scoring bug; the weighted
  token matcher reaches 91.8 % top-3 on held-out in ~14 ms with no new dependency. Adding a 100+ MB model needs a
  licence check and would slow the phone path — revisit only with real users' misses.
- A cheap preview frame on each chip: NOT DONE (the chip runs the real edit; undo is one tap).
