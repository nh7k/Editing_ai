# Live editing view · Copy an Edit · Templates — API contract

Three features added together (2026-10-07). Backend: `backend/cutmind/` (live.py, blueprint.py, templates.py, api.py).
App: `mobile/src/`.

## 1. Live editing view ("watch the agent edit")

While a job runs, the SSE stream `GET /jobs/{id}/events` now also sends:

| event type | data | when |
|---|---|---|
| `thought` | `{agent, text}` | every decision an agent makes, in plain words ("Picked 9 shots of ~4 s from 3 clips") |
| `timeline` | `{track, items}` (see below) | after an agent fills its part of the timeline |

`track` is one of `video`, `text`, `fx`, `music`, `color`. Items (all times in seconds on the OUTPUT timeline):

```jsonc
// video
{"clip_id": "clp_..", "filename": "a.mp4", "start": 0.0, "dur": 4.0, "in": 12.3, "out": 16.3, "speed": 1.0,
 "thumb": "/projects/{pid}/clips/{cid}/frame?t=14.3"}
// text
{"start": 1.0, "dur": 1.5, "text": "RONALDO", "kind": "title" | "caption" | "word"}
// fx  (effects, transitions, colour passes)
{"start": 3.0, "dur": 0.3, "type": "flash"}
// music
{"start": 0.0, "dur": 30.0, "name": "calm_80bpm.m4a"}
// color: a single item
{"preset": "warm", "lut": null}
```

A later `timeline` event for the same track REPLACES that track (a retry re-cuts the video). The latest state of
every track is also in the job snapshot: `GET /jobs/{id}` → `"timeline": {"video": [...], "text": [...], ...}` and
`"thoughts": [{t, agent, text}]` (last 200).

`GET /projects/{pid}/clips/{cid}/frame?t=<seconds>&w=160` → small JPEG of that moment (cached).

## 2. Copy an Edit (separate from "Edit like a reference" style tips)

Upload a finished edit you like; the agent watches ALL of it, shot by shot, and rebuilds the same edit from your raw
footage: same number of shots, same shot lengths in the same order, black & white on the same shots, flashes and
zoom hits at the same moments, the same aspect, the same soundtrack starting at the same point (so the cuts land on
the same beats), text at the same times.

| method | path | body | returns |
|---|---|---|---|
| POST | `/projects/{pid}/copy-edit` | multipart `file` (video, ≤ 3 min) | 202 `{status: "analyzing", progress: 0}` — watched in the background (~1.5 min for a 21 s reel on a laptop CPU, mostly reading the text) |
| GET | `/projects/{pid}/copy-edit` | | `{status: "analyzing", progress, step}` · `{status: "ready", blueprint}` · `{status: "failed", error}` · 404 `no_blueprint` |
| DELETE | `/projects/{pid}/copy-edit` | | `{deleted: true}` |
| POST | `/projects/{pid}/copy-edit/run` | `{prompt?: string, keep_sound?: boolean = true}` | `{job_id, status}` (202) |
| POST | `/projects/{pid}/copy-edit/template` | `{name: string}` | `Template` (201) — saves the blueprint as "My template" |

```jsonc
// Blueprint
{"name": "liked.mp4", "duration": 21.4, "aspect": "9:16", "song": "liked_sound.m4a" | null,
 "shots": [{"start": 0.0, "dur": 1.2, "bw": false, "flash": false, "zoom": false, "motion": 0.62,
            "bright": 0.48, "text": false}],
 "summary": ["21s 9:16", "17 shots, 0.4–3.1 s", "cuts follow its soundtrack (92 bpm)", "2 white flashes", ...],
 "color": {"preset": "warm" | "cool" | "vivid" | "bw" | null}, "thumbs": ["/projects/{pid}/copy-edit/thumb/0", ...]}
```

`GET /projects/{pid}/copy-edit/thumb/{i}` → JPEG of shot i of the liked video.

## 3. Templates

| method | path | body | returns |
|---|---|---|---|
| GET | `/templates` | | `{templates: Template[], categories: string[]}` |
| POST | `/projects/{pid}/templates/{tid}/apply` | `{prompt?: string}` | `{job_id, status}` (202) |
| DELETE | `/templates/{tid}` | | only "mine" templates |
| GET | `/templates/{tid}/preview` | | JPEG preview card (built-ins: drawn; mine: the liked video's frame) |

```jsonc
// Template
{"id": "tpl_velocity", "name": "Velocity Fan Edit", "category": "Sports", "kind": "builtin" | "mine",
 "description": "Fast beat cuts, stutters, B&W flashes, big name titles", "tags": ["fast", "beat"],
 "prompt": "<the professional brief the agent gets>", "duration": 15, "aspect": "9:16",
 "colors": ["#0b0b0b", "#e8e8e8"], "preview_url": "/templates/tpl_velocity/preview"}
```

Applying a template runs a normal edit (same live view, same versions/undo, same memory). A "mine" template made
from Copy an Edit replays the blueprint on the new footage.

## Measured (2026-10-07, this laptop)

* Copy an Edit on a 21 s Instagram reel (8 shots, 3 zooms, 7 captions): cuts found at the same times; 6 of its 7
  captions read correctly + 1 false one (text filmed on a laptop screen); rebuilt from 3 raw clips in ~20 s, review
  100% (12/12). Extra words work: "same edit karo par text mat lagao aur black and white bana do" → no text, B&W.
* Templates: 17 built-in, every prompt understood (unit test); Velocity / Travel Diary / Old Movie rendered at 100%.
* Talking to the agent 7 times in a row (fast edit → thoda slow → B&W → text → B&W hata + warm → end slow-mo →
  "pichla wala dobara"): 7/7 changes applied with every earlier change kept (scratch script memory_test.py).

## Render steps (added 2026-10-08)

While the video is rendered, the SSE stream also sends `render_step` events (latest one also in the job snapshot as
`job.render_step`):

```jsonc
{"step": "segment", "done": 4, "total": 9, "text": "rendering segment 4/9"}   // shot 4 of 9 is ready
{"step": "join",    "done": null, "total": null, "text": "joining segments"}
{"step": "finish",  ..., "text": "adding text, music and final encode"}
{"step": "reuse",   ..., "text": "reusing the cut (only text / audio changed)"}  // no per-shot rendering this time
{"step": "done",    ..., "text": "render complete"}
```
Segments are rendered in parallel, so `done` counts finished shots (not their index). After rendering the job's
stage becomes "reviewing" (node `review`): the agent watches the result.

Measured on the user's laptop for one chat message: queue wait (if another edit runs) → understand + analyse +
cut + effects ≈ 3 s (all timeline tracks arrive within ~1.5 s of each other) → render ≈ 15-25 s → review ≈ 5-7 s.
