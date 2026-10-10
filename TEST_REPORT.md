# TEST_REPORT — checkpoint 3: Tier 1 (105 skills) + the skill catalog (2026-10-10)

All on this laptop (i5-1334U, 8 GB RAM, Windows 11, no GPU, FFmpeg 9.0.1). Every number below was produced by a
command that was actually run; anything else is marked NOT TESTED.

## Commands run
```
python -m pytest tests/unit/test_tier1_engine.py                  # engine, parser, invariants
python -m pytest tests/integration/test_tier1.py                  # every Tier 1 skill rendered + measured
python -m pytest tests/integration/test_tier1_api.py              # API, versions, undo, 30 edits in a row
python -m pytest tests/integration/test_catalog_variants.py       # variant difference test
python -m pytest tests/integration/test_ducking_depth.py
python eval/run_tier1_lang.py                                     # YAML examples + held-out prompts
python eval/perf_probe.py 1 ; ... 5 ; ... 20                      # one length per process
python catalog/build_catalog.py ; python skills/tools/write_tier1_docs.py
python -m pytest tests/unit tests/integration --ignore=tests/integration/test_llm_real.py --ignore=tests/integration/stability_probe.py
```

## Results

| what | result |
|---|---|
| Tier 1 skills implemented | 105 (the brief's 100 + crop, stabilize, loop_boomerang, thumbnail, srt_export) |
| Render test (real FFmpeg render, content measured) | 105/105. The first combined run was 104/105: light_leak used a random FFmpeg seed and blended in YUV — fixed, rerun passed |
| Engine unit tests | 17/17 |
| 30 edits in a row on one project (+ undo / rollback) | 30/30, every version plays, length invariant held. The first run failed at edit 21 (a cut next to a crossfade made the video 0.36 s longer) — fixed |
| Language, YAML examples (seen while writing synonyms) | 763/840 = 90.8 % (en 209/210, hi 105/105, hinglish 209/210, typo 105/105, multi 105/105, **vague 30/105**) |
| Language, HELD-OUT prompts (written after freezing synonyms, run once, not tuned) | 92/110 = 83.6 % (en 57/69, hinglish 32/38, hi 3/3 — too few Hindi prompts to mean much) |
| Multi-instruction prompts (held-out) | 28/30 exact, mean recall 0.988 |
| Unsupported prompts | 4/5 refused with "not available yet" + 3 nearest skills. **Miss:** "ek naya video AI se bana do dragon wala" ran merge_clips |
| Contradiction prompts | 5/5 do not crash. **But they are not asked back:** "zoom in and zoom out" silently drops zoom out; "slow motion aur 2x speed" applies both |
| Catalog difference test | 93/93 axes pass; see "Catalog" below |
| Ducking depth (new test) | 9/9 (6 / 12 / 20 dB at three voice levels, within 1.5 dB) |
| Full regression | 1176 passed, 2 failed, 8 skipped (1 h 50 min, nothing edited while it ran). The 2 (old `strobe` and `echo` render tests) were test problems exposed by the exact-trim timing: sample frames fell between strobe flashes, and the clip part used barely moves. Fixed the measurement (moving shot, a frame every 0.04 s); `test_skill_renders.py` rerun alone: 150/150. The whole suite was NOT rerun after that fix. |

## Performance (Tier 1 path: prompt → 6 tool calls → one render; generated 1080p30 source + tone)

Prompt: "vertical banao blur sides ke saath, warm karo, zoom in 2 se 6 sec, music lagao, fade in fade out, progress bar"

| source length | edit wall time | × real time | FFmpeg peak RAM | Python peak RAM | plays |
|---|---|---|---|---|---|
| 1 min | 84 s | 1.4× | 1.09 GB | 46 MB | yes |
| 5 min | 719 s (12 min) | 2.4× | 1.10 GB | 46 MB | yes |
| 20 min | 4482 s (75 min) | 3.7× | 1.10 GB | 46 MB | yes |

- **Found and fixed:** every FFmpeg step had a flat 15-minute limit, so a 20-minute export could never finish.
  Now FFmpeg is stopped only if it prints no progress for 5 minutes.
- **Not linear:** 1.4× → 3.7× real time as the video gets longer. Not investigated yet (thermal throttling on a
  fanless laptop is likely; not proven). A phone doing this render is NOT TESTED and, at these numbers, too slow
  for anything but short clips: long videos must render on the server.
- Speech-to-text is not in these numbers (the source has no speech).

## Catalog (the second brief) — honest count

The number is an output of the difference test (docs/CATALOG_REVIEW.md), not a target:

- **105 bases ready** (each passed its Tier 1 render test) + **247 distinct variants ready** (each
  rendered, changes the video, and differs visibly / audibly from its siblings: 256 px frames at 6 fps, a 16×16
  tile, 0.25 s loudness, length, size, extra files).
- Rejected: 17 variants (10 duplicates of a sibling, 7 change nothing on the test media) (named in docs/SKILL_CATALOG.md with the measured reason).
- Planned: 174 variant rows (their axis is a design word, not a parameter yet, or the test media
  cannot show it, e.g. no face) + 41 planned bases from the FFmpeg filter review.
- The brief's 16,000 is not reached and is not honest to claim. Today: 105 + 247 = 352 distinct, tested items.
- The difference test found one real bug: ducking depth followed the speaker's loudness, not the asked dB (fixed,
  now within 0.2 dB). It also found three of its own measuring mistakes (fixed: small text, 0.4 s slide-ins, card
  sources).
- **Not built yet from the catalog brief:** multilingual-embedding search (needs a model decision: which free,
  small, commercially licensed embedding model — BLOCKED: needs human decision), the hand-written editor
  feature matrix (COVERAGE_MATRIX section B), Tier 2 (3,000 variants).

## NOT TESTED / not built (honest list)

- **Media3 (phone) mappings: all NOT TESTED** — 73 mapped, 19 need a custom shader, 13 server-only. No Android
  device was used.
- Real footage with faces / people (tests use generated media; face-region variants are "planned").
- A native Hindi / Hinglish speaker has not reviewed the synonyms (docs/SYNONYMS_FOR_HUMAN_REVIEW.md).
- The RNNoise model file's licence: BLOCKED (not shipped).
- "louder" reaches about -14.6 LUFS, not -11 (open from the previous checkpoint).
- Vague prompts ("mast bana do") match the right skill only 30/105 times — by design they need the Director.

## 5 biggest risks

1. **Phone rendering is unproven.** Every Media3 mapping is NOT TESTED; at 1.4–3.7× real time on a laptop CPU,
   long edits must stay on the server.
2. **Contradictions are not asked back.** "zoom in and zoom out" silently drops one; a user may not notice.
3. **Language on real users:** held-out accuracy is 83.6 % with only 3 Devanagari prompts; vague prompts 29 %.
   Needs a native-speaker review and real prompts.
4. **Generated test media only.** Effects that depend on people / faces / real speech are tested on synthetic
   stand-ins (a moving box, a TTS voice).
5. **Long-video performance grows faster than linear** (1.4× → 3.7×). Cause not found yet.

## Hindi / Hinglish phrases a native speaker should check

- Ambiguous words: kaato (alone), chhota karo, tez karo, saaf karo, mirror, status, highlight, 90s wala look,
  aaine jaisa / ulta seedha — full table in docs/SYNONYMS_FOR_HUMAN_REVIEW.md §1.
- Filler words removed: aa, aaa, aah, umm, hmm, हम्म, आ, अ; kept: matlab, toh, na, haan, basically.
- Least sure: "ye faltu part uda do", "sab chipka do", "chust karo", "sec me nipta do", "shuruat dhamakedar",
  "awaaz khinch do", "phatak se badle", "fatak se zoom", "apna thappa lagao", "gunj", "mandir jaisi gunj",
  "kampan hatao".

---

# TEST_REPORT — checkpoint 2: the editor's mind + a free, provider-agnostic planner LLM (2026-10-09)

## Commands run (all on this laptop: i5-1334U, 8 GB RAM, Windows 11, no GPU)
```
python eval/run_eval.py                                         # rules only
python eval/run_eval.py --provider llamacpp --model <m>          # m = qwen3-0.6b | qwen3-1.7b | qwen3-4b | phi-4-mini
python eval/run_eval.py --provider llamacpp --model qwen3-0.6b --big qwen3-4b
python backend/scripts/bench_llm.py <m> --load 1,5,20 --timeout 30
python -m pytest tests/unit          (from backend/, with the venv)
python -m pytest tests/integration --ignore=tests/integration/stability_probe.py
cd mobile && npx tsc --noEmit && npx jest
```

## Eval (67 instructions: English, Devanagari Hindi, Hinglish, typos, slang, vague, negations, magnitude,
## contradictions, long, empty, chit-chat, reference) — `eval/results/*.json`
| Setup | Before | After | Paraphrases | Devanagari | Typos | p50 / p95 per model call |
|---|---|---|---|---|---|---|
| Rules only | 54/67 (80.6 %) | **60/67 (89.6 %)** | 8/15 | 0/4 → 4/4 | 2/4 → 4/4 | – |
| + Qwen3-0.6B (default) | 57/67 (85.1 %) | **61/67 (91.0 %)** | 9/15 | 4/4 | 4/4 | 4.9 s / 16.7 s |
| + Qwen3-1.7B | 56/67 (83.6 %) | 61/67 (91.0 %) | 9/15 | 4/4 | 4/4 | 6.4 s / 12.3 s |
| + Qwen3-4B | 55/67 (82.1 %) | **63/67 (94.0 %)** | 11/15 | 4/4 | 4/4 | 12.5 s / 17.4 s |
| + Phi-4-mini | – | 62/67 (92.5 %) | 11/15 | 4/4 | 3/4 | 10.5 s / 19.7 s |
| + 0.6B, 4B when unsure | – | 62/67 (92.5 %) | 10/15 | 4/4 | 4/4 | 6.0 s / 19.8 s |
**Final (after the live-test fixes below):** rules only **61/67 (91.0 %)**; rules + Qwen3-0.6B with the new safety
guards **62/67 (92.5 %)** — the guards rejected 12 bad model answers (measured before the last rule fix).

**Live test through the running server (honest):** with Qwen3-0.6B, "gaane ki awaaz thodi dheemi kar do" was first
read by the model as "podcast clip" and REBUILT the user's lyric edit (wrong). Fixed: style / whole-edit commands
need a style word in the user's message, an answer must be about a topic the message mentions (the plural
"captions" slipped past the old topic check — fixed), and the rules now read "thodi / zara / bahut" in music-level
asks. Re-run live: the model's answer was rejected, the edit stayed intact (undo restored the user's v4); the rules
now answer this phrase themselves (music level 0.12). Request accepted in 23 s while the model ran — slow.

Invariants in the eval: every empty prompt refused (2/2), chit-chat never turned into an edit (2/2), every negation
case kept (6/6), no crash in any run. Details, cost and the load test: `docs/MODEL_CHOICE.md`.

## One real example from the tests (how the agent thinks now)
"gaane ki awaaz thodi dheemi kar do" — before: the rules matched "gaane" and read **upbeat music** (wrong).
Now: prenormalize → coverage 0.33 (most words are not the editor's own) → the planner model is asked →
`{"commands": [{"id": "music_softer"}], "confidence": 0.9}` → safety checks pass (nothing removed, no negation
contradicted) → its reading replaces the guess → "music thoda kam karo" → music level 0.12, the cut untouched
(`test_prenormalize.py::test_half_understood_clause_is_replaced_by_the_models_reading`, eval case p01 with 4B).

## Test results (final run of this checkpoint)
| Suite | Result |
|---|---|
| backend unit | **649 passed, 6 skipped, 0 failed** |
| backend integration (real FFmpeg renders) | full run: 81 passed, 6 failed → all 6 fixed and re-run (e2e/music/reference files: 32 + 4 passed) |
| mobile jest | 242 passed (32 suites); tsc clean |
| new integration files (mind API, real LLM, stickers + comments, non-destructive) | **15 passed** (real Qwen3-0.6B: valid catalog JSON, the deadline stops generation, the queue answers "busy" at once) |

The 6 integration failures and their fixes: 4 × e2e — the new per-client rate limit (30 edits/min) hit the suite
→ disabled in tests (`RATE_LIMIT_PER_MIN=0`; `test_mind_api.py` tests the limit itself), and sample prompts on one
project became follow-ups (they kept the earlier length — correct behaviour) → the test now says "New edit, …";
1 × text behind the person — the new "move a hidden word in front" rule (limit 0.45) also moved a word that reads
fine → limit 0.6, measured on both cases (0.52 readable, 0.65–1.0 unreadable on a close-up); 1 × reference edit —
the calm-footage autopilot (2.5 s shots) overrode the reference's rhythm → skipped when a reference is used.

## NOT TESTED / not built (honest list)
- llama-server provider and the docker-compose stack: code + config written, **not run** (no Docker on this laptop).
- Visual captions per keyframe (vision model): not built.
- Episodic few-shot retrieval of past edits into the LLM prompt: not built.
- Media3 mapping, migration script: not done in this checkpoint.
- The recipes are data + selection (`recipes.pick`); the agents still take their numbers from `skills.yaml` —
  wiring recipe numbers into the cutter / effects is the next step.
- Cost model for 100 / 1,000 / 10,000 users: estimates, not measured on a server (`docs/COST_MODEL.md`).
- The "get rid / drop" take-away fix and the "colours" vocabulary word were added after the model runs: NOT
  re-measured with a model.

## 5 biggest remaining risks
1. On this laptop a model call costs 5–12 s and the chat waits for it (only for unclear clauses, ~1 in 3 messages).
2. Small models still misread some paraphrases (0.6B: 9/15); the safety checks reject contradictions but a wrong,
   non-destructive reading can still pass (e.g. "subtitles peele" → white).
3. The coverage heuristic decides when to ask the model; words missing from the editor's vocabulary can send a
   correctly understood clause to the model (more latency) or keep a misread one from it.
4. One llama.cpp process answers one request at a time; above ~5 simultaneous unclear messages the rules answer.
5. The rate limiter and the job queue are in-memory (one API process); scaling out needs a shared store.

---

# TEST_REPORT — non-destructive editing (checkpoint 1, 2026-10-08)

Work order from the user's brief: 1) reproduce 2) root cause 3) non-destructive versioned plan + invariants + rollback
4) intent scope / patch ops 5) presets, recipe book, rules engine 6) gates + critic + fallback 7) memory, metrics,
eval harness 8) Media3 mapping 9) full test loop 10) reports. **This checkpoint covers 1–4 (partly) — see "Where to
continue".**

## 1. Reproduction (before the fix)

`tests/integration/stability_probe.py` — 3 FFmpeg-generated clips (test patterns + a tone, 12/9/7 s, 28 s total), N
consecutive prompts on ONE project, every output measured with ffprobe + a full decode.

8-step run (English prompts from the brief), before any change:

| # | prompt | dur (s) | res | kbps | audio | decodes | shots |
|---|---|---|---|---|---|---|---|
| 1 | add captions | 28.01 | 1280x720 | 1250 | y | yes | 3 |
| 2 | warm color | 28.01 | 1280x720 | 1120 | y | yes | 3 |
| 3 | add music | 28.02 | 1280x720 | 1119 | y | yes | 3 |
| 4 | make it a 9:16 reel | 28.01 | 720x1280 | 668 | y | yes | 4 |
| 5 | add fade transitions | 26.50 | 720x1280 | 683 | y | yes | 4 |
| 6 | remove silence | 26.50 | 720x1280 | 683 | y | yes | 4 |
| 7 | change caption style to bold yellow | 26.50 | 720x1280 | 683 | y | yes | 4 |
| 8 | add zoom | 26.50 | 720x1280 | 679 | y | yes | 4 |

30-step run (the 8 + 22 Hinglish follow-ups): duration only 28.01 ↔ 26.50 s, exactly following transitions on/off
(3 cross-fades × 0.5 s overlap — expected), 30/30 decode OK, audio in all 30, resolution changed only when asked.
(A film-grain step reached 5.7 Mbit/s — under the 6 Mbit/s cap added earlier.)

**So "every edit makes the video shorter until it won't play" did NOT reproduce as a duration spiral on generated
footage.** Renders always start from the ORIGINAL clips (`renderer.render(plan, sources=clip media)`; outputs are
never inputs) and from one plan → one graph → one final encode (segments are intermediate, lossless-ish crf 17
ultrafast, re-made from the originals each time). What DID make the user's edits "worse every time", found in the
app with the user's own project:

## 2. Root causes found

1. **A long follow-up message started a NEW edit.** `memory.is_follow_up` treated any message > 14 words as a whole
   new brief. The user's 24-word message ("2 sec me hi ruk agyi video kyu, … ek ronaldo text ko hata do") rebuilt
   the edit from scratch: the song, the earlier changes and the hand-made effect were gone.
2. **"make it a 9:16 reel" / "isko reel bana do" also started a new edit** (a "kind of video" counted as a new
   brief) and dropped warm colour + music (seen in the probe's step 4).
3. **Hand-made changes were never part of the "current edit".** The Effects panel's "Apply now" etc. patched the
   plan, but the next chat message re-planned from the remembered *intent* only, so those changes vanished.
4. **A silent edit stopped in Chrome at 2.3 s.** With the song gone the audio was pure digital silence; FFmpeg's AAC
   encoder writes 6-byte frames for it and Chrome's player failed on them ("PIPELINE_ERROR_DECODE: Failed to send
   audio packet for decoding, timestamp=2304000") — the user's "video 2 sec me ruk gayi". ffprobe and a full FFmpeg
   decode said the file was fine, so the quality gate did not catch it.

## 3. The fix (so far)

- **Scope is INCREMENTAL_PATCH by default** on a project that has an edit; only an explicit restart ("naya edit",
  "shuru se", "start over", "reset") or a whole-edit ask ("accha sa / mast sa bana do") is GLOBAL_REBUILD
  (`memory.FRESH_PATTERNS`, `is_follow_up`).
- **Hand-made changes are kept:** every manual op is stored (`manual_ops` table) and re-applied on top of the agents'
  new plan for every follow-up (`workflow._with_manual`, all three plan-merge points). Ops tied to the old cut
  (delete / move / speed of a shot index) are skipped and the user is told. A rebuild forgets them.
- **Versions, undo, redo, restore, compare** (`versions.py`, `GET /projects/{id}/versions`, `POST …/undo`,
  `POST …/redo`, `POST …/versions/{job}/restore`, `GET …/versions/compare?a=&b=`): every finished job is a
  version with its own output file; restore creates a new version that copies the old plan + output (no
  re-encode) and makes its memory and hand-made changes current. App: the ↶ ↷ buttons now work.
- **Explain-back + duration invariant:** every job returns `explain` = what changed / what stayed / new length, and a
  warning when the length moved > 2 % (min 0.25 s) although the message asked for nothing length-related. Shown in
  the chat answer.
- **Audio never pure silence:** an inaudible noise floor (−94 dBFS pink noise) is mixed in; verified in the app:
  the same project now plays 0 → 6.9 s+ continuously.
- "do baar text, usme se ek hatao" removes only the repeated beat words (keeps the title).

## 4. Tests run (this checkpoint)

| test | result |
|---|---|
| `tests/integration/test_nondestructive.py` (follow-ups keep earlier changes + a hand-made effect, same length ±2 %, decode; "shuru se" forgets; undo/redo/restore/compare/explain) | 3 passed |
| backend unit suite | 594 passed (one test updated for the new default scope) |
| mobile jest | 236 passed |
| app, real browser: play after an edit | plays past 2 s (was stopping at 2.0 s) |
| 8-step / 30-step probe AFTER the fix | **NOT TESTED yet** (re-run is the next step) |

## Where to continue

Next, in the brief's order: re-run the 8/30-step probe after the fix; invariant checks as a gate before render
(min shot length, in/out within source, aspect/resolution unchanged unless asked); rollback on a failed render
already holds (a failed job never becomes current) — add a browser-compat audio check to the gate; then 5) presets
library + FFmpeg recipe book tests + rules engine, 6) gates/critic/approval checkpoint, 7) eval harness, few-shot
memory, metrics, docs/AGENT_INTELLIGENCE.md, 8) Media3 mapping, migration script, LICENSES.md.

## Biggest remaining risks (so far)

1. A follow-up that asks for a new cut (pace, length) re-cuts the footage; hand-made *shot-level* changes are lost
   then (they are reported, not kept).
2. "thoda slow / fast karo" changes nothing on footage with few long clips when the edit is not a fast-cut montage
   (seen in the 30-step probe: 4 shots throughout).
3. Browser playback problems that FFmpeg tolerates are not detected automatically yet.
