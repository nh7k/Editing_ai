# CutMind — Architecture

CutMind is a prompt-driven, multi-agent video editor. The user uploads raw clips, writes a
prompt ("30 sec travel reel, fast cuts, warm color, captions, remove silence") and a team of
agents produces an **Edit Plan**. A deterministic FFmpeg renderer turns that plan into a video,
and a Reviewer agent grades the result and the agents.

```
 Mobile app (Expo, UI only)  ──HTTP/JSON──►  FastAPI backend  ──►  Job worker thread
                                                   │                     │
                                                SQLite             Director (CEO)
                                     (projects, clips, jobs,  ┌──────────┼───────────────────────────┐
                                      agents, runs, scores,   Analyzer  Audio  Cutter  Color  Effects
                                      lessons)                └──────────┬───────────────────────────┘
                                                                   Edit Plan JSON (Pydantic)
                                                                         │
                                                              Renderer (FFmpeg, deterministic)
                                                                         │
                                                              Reviewer (ffprobe + frame checks)
                                                                         │
                                                       scores ► lessons ► retries (max 2 / agent)
```

## Core rule: agents never touch video

Agents read the prompt, the analysis and the current plan, and return **only a section of the
Edit Plan** (structured JSON, validated by Pydantic). The renderer is the only component that
runs FFmpeg on video. This makes every edit reproducible, diffable and testable.

## Edit Plan (backend/cutmind/plan.py)

| Section        | Fields |
|----------------|--------|
| `version`      | `"1.0"` |
| `canvas`       | `aspect_ratio` (`9:16`/`1:1`/`16:9`), `resolution` (short side: 360/480/720/1080), `fps`, `reframe` (`crop`/`blur_pad`) |
| `clips[]`      | `source` (clip id), `in`, `out` (seconds in source), `order`, `speed` (0.25–4), `volume` (0–2) |
| `audio`        | `music` (file name or null), `music_volume`, `ducking` (bool), `duck_amount_db`, `voice_cleanup`, `target_lufs`, `beat_sync` |
| `color`        | `brightness` (-1..1), `contrast` (0..2), `saturation` (0..3), `warmth` (-1..1), `preset` (`none/warm/cool/cinematic/vintage/bw/vivid`) |
| `text[]`       | `kind` (`caption`/`title`), `text`, `start`, `end` (output seconds), `style` (`position`, `size`, `color`, `box_color`) |
| `transitions[]`| `type` (`fade`/`crossfade`/`zoom`/`wipe`), `after` (segment index, or -1 = fade-in at start, -2 = fade-out at end), `duration` |
| `effects[]`    | `type` (`zoom`/`speed_ramp`/`blur_background`/`shake`), `target` (segment index or -1 for all), `strength` |
| `export`       | `format` (`mp4`), `video_codec` (`libx264`), `crf`, `preset`, `audio_bitrate` |

Pydantic validators enforce ranges, `in < out`, unique orders, transition durations shorter than
the neighbouring segments, and text timing inside the video. `plan.timeline()` maps every segment
to its output start/end (taking speed and transition overlaps into account) — used by Effects
(caption timing) and the Reviewer.

## Agents (backend/cutmind/agents/)

All agents subclass `BaseAgent` and expose `run(ctx, feedback=None) -> AgentResult`
(JSON-serialisable section of the plan + notes). Each has:

* a **system prompt** describing its single job,
* **lessons** (top 5 recent from SQLite) injected into that prompt,
* `PLANNER_MODE=mock` → deterministic rules (no LLM, used by tests),
* `PLANNER_MODE=local` → a small open model (default **Qwen2.5-1.5B-Instruct**, Apache-2.0, int4 ONNX,
  ~1.8 GB; lighter option Qwen2.5-0.5B) runs **inside the backend process** with ONNX Runtime on CPU
  (`backend/cutmind/local_llm.py`, greedy decoding with KV cache). No Ollama, no separate server, no API
  key — the same Docker image works on a laptop or a cloud VM. The model returns a small **decision**
  JSON, validated with Pydantic (lenient: invalid fields are dropped), retried up to 2× with the error,
  and the agent falls back to rules if it still fails (`llm_fallback`). Deterministic code turns the
  decision into exact numbers / cut points, so a small model can't produce an unrenderable plan.
  `LLM_AGENTS=director` (default) = one LLM call per job (the prompt → intent step); `all` = every
  agent also asks the model (slower on CPU).

| Agent    | Job | Output |
|----------|-----|--------|
| Director | Parses prompt → `Intent` (duration, aspect, color, captions, silence removal, fast cuts, music, transitions, effects, title). Orchestrates order, merges sections, runs reviewer, retries low scorers, writes lessons. | `Intent`, full plan |
| Analyzer | ffprobe metadata, PySceneDetect scenes, FFmpeg `silencedetect`, faster-whisper transcript (word timestamps), loudness (EBU R128), sharpness/motion (OpenCV), beat grid (librosa). Cached per clip. | `Analysis` |
| Audio    | Picks a track from `backend/assets/music` (local royalty-free), music volume, ducking under speech, voice cleanup, beat grid of the music for beat-sync. | `audio` section + music beats |
| Cutter   | Selects / trims / orders segments, removes silence + fillers (`um`, `uh`…), fits target duration (budgeting for transition overlap), fast-cut chunking (beat-snapped when beat-sync), **never cuts inside a word** (cut points snapped to word gaps). | `clips[]` |
| Color    | Preset → brightness/contrast/saturation/warmth; normalises exposure across clips from analysis (consistent look). | `color` |
| Effects  | Captions from transcript remapped to output time, titles, transitions, zoom / shake / speed-ramp / blur-background, reframing mode. | `text[]`, `transitions[]`, `effects[]`, `canvas.reframe` |
| Reviewer | Checklist on the **rendered file**: plays (full decode), duration, resolution/aspect, audio stream, loudness & clipping, captions present (plan + pixel check in caption band), silence removed, color change measurable vs source, transitions/effects/music present, clip order. Each check has an owner agent → per-agent score + overall match %. | `Review` |

### Orchestration order

`Analyzer → Audio → Cutter → Color → Effects → Renderer → Reviewer`

Audio runs before Cutter so the Cutter can snap fast cuts to the music beat grid.

### Scoring & learning

* Each checklist item is owned by one agent. Pass ⇒ `+10`, fail ⇒ `-15` (with reason) on the leaderboard.
* Agent score (0–100) = passed weight / total weight for that agent's checks. Core checks weigh more
  (`duration`, `captions_present`, `aspect_ratio`, `file_plays` = 3; `silence_removed`, `color_applied`,
  `music_present`, `transitions_present`, `resolution` = 2; others 1) so one missed core instruction
  drops the agent below the threshold. Agents with no checks get 100. Match % uses the same weights.
* The Reviewer grades against an **independent keyword reading** of the prompt, not against the
  Director-LLM's interpretation (otherwise an LLM misunderstanding would grade itself as correct). In
  local-LLM mode explicit keywords (e.g. "1080p", "vintage") override the LLM intent ("keyword guard"),
  and every override costs the Director an `llm_intent_correct` check + a lesson.
* **Evidence gate** (`backend/cutmind/evidence.py`): a field the LLM sets on its own is kept only if the
  prompt contains a word that could ask for it (English + Hinglish vocab). Real example from the 1.5B
  model: "Clean up the audio, remove ums, landscape" → it added black & white, 1080p and fades; all three
  are dropped and logged.
* The Reviewer also penalises **unrequested** additions (transitions/effects/titles/captions/music
  nobody asked for) — LLM agents sometimes "decorate".
* Score `< 70` (`SCORE_THRESHOLD`) ⇒ Director re-runs **that agent** with the Reviewer feedback
  (max 2 retries, `MAX_AGENT_RETRIES`). Dependent agents (Effects depends on the Cutter's timeline)
  are re-run after a Cutter retry so captions stay in sync. Then render + review again.
* Every failed check becomes a short **lesson** (`agent`, `check`, `text`). The 5 most recent
  distinct lessons are injected into the agent's prompt next time.
* User 👍 = `+5` to every agent in that run, 👎 = `-5` (or targeted at one agent) and a comment
  becomes a lesson.

SQLite tables: `projects`, `clips`, `jobs`, `agents`, `runs`, `scores`, `lessons`, `feedback`.

## Renderer (backend/cutmind/renderer.py)

1. **Segments** — per plan clip: trim, speed (`setpts` / `atempo` chain), reframe to canvas
   (`crop` fill or blurred background pad), fps, color grade (`eq`, `colortemperature`, preset
   curves), per-segment effects (zoom, shake, speed-ramp split), audio volume (silent clips get
   `anullsrc`). Encoded to uniform intermediates (H.264 + AAC 48 kHz stereo).
2. **Join** — `xfade` + `acrossfade` for transitions, concat otherwise; fade-in/out at edges.
3. **Finish** — text via generated ASS file + libass (`subtitles` filter), music loop/trim mixed
   with ducking (`sidechaincompress`), voice cleanup (`highpass`, `afftdn`), `loudnorm` to target
   LUFS, final encode per `export`.

Temp files live in `data/projects/<id>/work/<job>` and are deleted after the job.

## REST API (FastAPI, docs at `/docs`)

All errors: `{"error": {"code": "<snake_case>", "message": "<human readable>"}}`.

Auth (production): when `CUTMIND_API_KEY` is set, every route except `/health` and the docs needs
`X-API-Key: <key>` (or `?api_key=<key>` for `<video>`/`<img>` URLs that can't send headers) → else `401 unauthorized`.

| Method & path | Body | Response |
|---------------|------|----------|
| `GET /health` | – | `{status, planner_mode, ffmpeg: bool, whisper: bool, version, auth_required: bool, llm: {model, file?, available: bool|null}}` (`available: null` in mock mode) — always public |
| `POST /projects` | `{name}` | `Project` |
| `GET /projects` | – | `Project[]` |
| `GET /projects/{id}` | – | `Project` |
| `DELETE /projects/{id}` | – | `{ok: true}` |
| `POST /projects/{id}/clips` | multipart, field `files` (1..n) | `{clips: Clip[]}` (413 too big, 415 bad type, 400 corrupt) |
| `DELETE /projects/{id}/clips/{clip_id}` | – | `{ok: true}` |
| `GET /projects/{id}/clips/{clip_id}/thumbnail` | – | `image/jpeg` |
| `POST /projects/{id}/edit` | `{prompt, aspect_ratio?, resolution?}` | 202 `{job_id, status}` |
| `POST /transcribe` | multipart `audio` (≤5 MB, any format FFmpeg reads) | 200 `{text, language}` — spoken prompt → English (local faster-whisper `translate`) |
| `GET /jobs/{id}` | – | `Job` |
| `GET /projects/{id}/plan` | – | `EditPlan` (latest) |
| `GET /projects/{id}/output` | – | `video/mp4` |
| `POST /jobs/{id}/feedback` | `{rating: "up"|"down", comment?, agent?}` | `{ok, points_delta}` |
| `GET /agents/scoreboard` | – | `{agents: AgentStat[]}` |
| `GET /fx` | – | `{catalog: {motion, video_effect, transition, color, text_animation}, counts}` — the FX catalogue |
| `GET /projects/{id}/memory` | – | `{history, preferences, summary}` — what the agents remember |
| `GET /styles` | – | `{styles: [{id, name, description, colors}]}` — Midnight Drift, Violet Authority, Cyan Kinetic |
| `POST /jobs/{id}/choose` | `{variant}` | `{ok, chosen}` — makes that version the project output |
| `GET /projects/{id}/output?variant=&format=` | – | a specific version (`variant` 0–2) as mp4 / gif / mp3 |
| `GET /projects/{id}/clips/{cid}/filmstrip?frames=` | – | `image/jpeg`, frames × 160×90 side by side (timeline) |
| `GET /projects/{id}/clips/{cid}/waveform?points=` | – | `{peaks: number[0..1], duration}` (timeline) |

`POST /projects/{id}/edit` also accepts `variations: 1|2|3` and `style`. With 2–3 variations the Director
renders the same cut in each look (`cutmind/styles.py`: grade + animated gradient **graphic tracks** made with
FFmpeg `gradients` + `alphamerge` — glow frame, colour wash, lower bar), reviews every version and ranks them
best first (`job.variations`). Looks never change timing, so captions/cuts stay as reviewed.

```ts
Project  = { id, name, created_at, clips: Clip[], last_job_id: string|null, has_output: boolean }
Clip     = { id, filename, duration, width, height, fps, has_audio, size_bytes }
// all percentages (progress, score, match_percent) are 0..100
Job      = { id, project_id, prompt, status: "queued"|"running"|"done"|"failed", progress: number,
             stage: string, error: string|null, match_percent: number|null, created_at, finished_at,
             agents: { name, status: "pending"|"running"|"done"|"retrying"|"failed",
                       progress, score: number|null, attempts, message }[],
             logs: { t: string, agent: string, level: "info"|"warn"|"error", msg: string }[],
             review: { checks: { name, owner, passed, detail, points }[],
                       agent_scores: Record<string, number>, match_percent } | null,
             output: { duration, width, height, has_audio, size_bytes } | null }
AgentStat = { name, role, total_points, runs, avg_score: number|null, last_delta,
              recent_lessons: { text, created_at }[] }
```

## Mobile app (mobile/)

Expo + TypeScript, UI only: Projects, Import (expo-image-picker), Editor (expo-video preview,
Skia + Reanimated timeline, chat input with quick chips, voice placeholder), Agent Activity sheet
(polls `GET /jobs/{id}`), Scoreboard, Export (resolution/aspect, save, share, 👍/👎).
No video processing in JS; the backend URL is configurable in-app (persisted).

## Configuration (env vars, see `backend/cutmind/config.py`)

`PLANNER_MODE` (mock|local), `LLM_REPO`, `LLM_FILE`, `LLM_MODEL_DIR`, `LLM_AGENTS`, `LLM_THREADS`,
`LLM_MAX_NEW_TOKENS`, `LLM_PRELOAD`, `CUTMIND_API_KEY`, `CORS_ORIGINS`, `WHISPER_MODEL`, `ENABLE_TRANSCRIPTION`,
`CUTMIND_DATA_DIR`, `MAX_UPLOAD_MB`, `MAX_CLIPS`, `SCORE_THRESHOLD`, `MAX_AGENT_RETRIES`,
`FFMPEG_BIN`, `FFPROBE_BIN`, `MUSIC_DIR`.


## FX catalogue (`backend/cutmind/fx_catalog.py`, `luts.py`)

One registry drives parser, plan validation, renderer and UI: 10 motion moves, 28 CapCut-style video effects
(glitch, RGB split, VHS, film grain, old film, scanlines, flash, strobe, mirror, kaleidoscope, pixelate, posterize,
negative, colour pop, ghost trail, echo, fisheye, dreamy glow, neon edges, sketch, thermal, night vision, cinema bars,
duotones, vignette, sharpen, blur), all 58 FFmpeg `xfade` transitions (+ 4 classic names), 10 colour looks as our
own generated 33³ `.cube` LUTs applied with `lut3d`, and 6 caption/title animations written as libass override
tags (fade, pop, bounce, slide-up, typewriter, karaoke word highlight). Every entry has English + Hinglish keywords.
`tests/unit/test_fx_visible.py` renders every effect/look for real and asserts the picture actually changes.
Research behind it: `docs/RESEARCH_open_source_capcut.md`.

## Long-term memory (`backend/cutmind/memory.py`)

Table `edit_memory`: every finished edit (prompt, understood intent, delivered look/aspect/grade/length/effects),
the version the user chose, and their 👍/👎. Derived preferences across projects: favourite look (choices count
double, 👎 counts against), disliked looks, usual aspect, favourite colour look, caption habit. The Director logs
the memory summary every job, gives it to the LLM, repeats the previous edit for "same as before / pichli baar
jaisa / again" (today's instructions win), applies the favourite look for "my style / mera style", and ranks the
favourite first (disliked last) when making 3 versions. Per-agent *lessons* (mistakes) remain as before.


## Auto edit, smart arrange, voice prompts (2026-10-06)

* **Auto edit** (`Intent.auto`): vague creative prompts ("mast sa edit kar do", "make it look amazing", a bare
  "edit kar do") switch it on. After analysis the Director's `autopilot()` fills every field the user did not set:
  talking clips → pauses + um/uh removed, pop-in captions, calm ducked music, slow zoom, vivid colour, no
  transitions (jump cuts); clips without speech → beat-synced fast cuts (hard cuts), upbeat music, ≤30 s;
  a few short silent clips → crossfades. The reference intent for the Reviewer gets the same choices.
* **Smart arrange** (`order="smart"`): clips are put in filming order. The Analyzer reads the time from phone/
  camera file names (`IMG_20260930_151012`, `20260930151012.avi`, `VID-…-WA0012`) or the `creation_time` tag.
  In auto edits the Cutter also moves the most eye-catching ~2 s with nobody talking (per-0.5 s motion curve)
  to the start as a hook — moved, not copied.
* **Voice prompts**: the web app records the mic (MediaRecorder) and posts it to `/transcribe`.
* **Speed**: segments render in parallel (`RENDER_WORKERS`, default 2–4); the studio renders one version unless
  the 3-variations chip is on or the prompt asks for versions.

## LangGraph, router, MCP, live events (2026-10-06)

Orchestration is a LangGraph graph (LANGGRAPH.md) with SQLite checkpoints; the specialist registry and AgentRouter
are in AGENTS.md; the MCP server in MCP.md; CPU-only operation in CPU_MODE.md; memory/lessons in MEMORY.md.

New endpoints: `POST /understand` (prompt coach), `GET /jobs/{id}/events` (SSE), `GET /capabilities`,
`GET /agents[?prompt=]`, `GET /workflow`.
