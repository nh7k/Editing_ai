# test200 — plan (2026-10-11)

The app does the editing; the campaign is the user and the judge. Every case goes through a user entry point
(`POST /projects/{id}/edit` chat / comment / playhead, `POST /jobs/{id}/choose`, `/undo`, `/redo`, `/manual` for
panel buttons, the real browser for UI cases). No case calls a skill builder.

## What already exists and is reused (not duplicated)

| exists | used for |
|---|---|
| `backend/cutmind/media_gen.py` (FFmpeg + Windows System.Speech TTS, BPM songs, silent / corrupt clips) | fixtures |
| `tests/conftest.py make_settings` pattern (temp data dir, mock planner, transcription on) | isolation |
| FastAPI app `create_app(settings)` in-process via `TestClient` (real routes, real job queue, real FFmpeg) | API driver |
| `backend/cutmind/verify.py` (Phase A production verifier) | NOT used by the judge (independence); compared with the judge as a cross-check |
| `tests/integration/tier1_checks.py` | ideas only — it is fixture-specific (1-3 s windows, pure tones) |
| `docs/REALITY_MAP.md` | which paths exist, what is broken |
| the built-in browser pane (a real Chromium in the desktop app) | UI cases (see "challenge" below) |

## Allocation (as asked, 200)

S 109 (every skill once, natural phrasing, rotating language style) · M 25 · T 20 · X 12 · A 12 · U 12 · R 10.

## Fixtures (FFmpeg + local TTS only; manifest with ground truth)

`tools/test200/fixtures.py` writes `tools/test200/fixtures/*.mp4` + `manifest.json`:
speech_pauses (TTS sentences with known 1.2 s pauses, 640x360), speech_music, music_beats (120 BPM click song +
testsrc2), multishot (4 colour shots with hard cuts at known times), silent_single, noisy_speech, dark, bright,
shaky, portrait (360x640), square, rotated (rotation metadata), vfr, k4 (3840x2160, 3 s), fps60, no_audio,
audio_only, corrupt, short1s, long5min (generated once, used by 1 case).

## The oracle

- `tools/test200/cases.yaml` is written by `cases_src.py` BEFORE the first run and frozen (`cases.lock.json`,
  sha256). Later changes go to `docs/test200/ORACLE_CHANGES.md` with a reason.
- Each case: turns (what the user does) + expectations per instruction: an assertion kind from
  `tools/test200/judge.py` (measured on the output video against the fixture / the previous output), a set of
  acceptable outcomes (e.g. `warm` OR `cinematic` for "filmy colour"), severity.
- Final state per instruction: APPLIED (measured) / NOT_NEEDED (reason + fixture truth agrees) / COULD_NOT (a
  reason was shown) / NOT_UNDERSTOOD (422 with chips) — silence is a failure.
- Every case also: video decodes, duration/audio sane, no unrequested change (frame diff where nothing was asked),
  message honesty (never "nothing changed" when the judge measured a change; never "already" when the plan lacks
  it; a failed instruction is never claimed), originals untouched (fixture hash before/after), undo = exact plan.
- The judge reads only: the video, the fixture manifest, the API status codes and the plan JSON (as data). It never
  reads the app's `verify` results or messages to decide a pass — messages are only checked FOR honesty.

## Runner

`python tools/test200/run.py [--case S001] [--cat S] [--failed] [--wave 1]` — isolated data dir
(`tools/test200/work/data`), resumable state (`state.json`, one case at a time, renders one at a time), per-case
timeout, a failing case is rerun twice before it is classified (flaky vs real), `results.jsonl`, `results.csv`,
live `progress.md`. Failures are classified APP BUG / TEST BUG / ORACLE AMBIGUITY / ENVIRONMENT.

## Waves

Wave 1: 40 smoke cases across all categories → fix → Wave 2 (80) → fix → Wave 3 (80) → fix → full 200 →
generalisation round (5 new phrasings per fixed bug) → eval + regression gate.

## Where I disagree with the brief (and why)

1. **Playwright:** not added. The desktop app already gives me a real Chromium (the browser pane) that I drive
   step by step; adding Playwright means ~150-300 MB of browsers on a small disk and a new dependency. Cost: UI
   cases are run by me through the pane and recorded with evidence (`run.py --record`), not by an unattended
   script; they are reproducible from the written steps but not one-command. NOT TESTED: unattended UI runs.
2. **"S: 109 cases, one per skill, through chat"** measures reachability, but a first message on a fresh project
   always goes to the director (that is the product rule: the first edit is a whole edit). So every S case first
   makes a plain base version the way a user does with one tap — the resolver's "Sab jod do" chip (`/tools/resolve`
   → `/tools` merge_clips, ~5-10 s instead of a 30-90 s director job) — and then sends the skill phrase in the
   chat, which is how a user tweaks. The director path is measured by the M / T / A cases (and 10 S cases that
   send the phrase as the FIRST message, to measure what a brand-new user gets).
3. **Speed:** a director job on this laptop is 30-90 s, a skill job 10-25 s on 6-10 s fixtures. 200 cases ≈ 6-9
   hours of renders per full pass — the waves are needed; the full pass runs in the background.
4. **The 5-minute and 4K cases** are run once (R), not in every wave.
