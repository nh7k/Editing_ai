# Agents

CutMind has two layers:

1. **Workflow agents** — the nodes of the LangGraph workflow (see LANGGRAPH.md). They own the Edit Plan sections.
2. **Specialists** — 202 roles in `backend/cutmind/agent_registry.py`. Each names the code that does the work
   (`impl`). The **AgentRouter** (`route(intent)`) picks the ones a request needs; the rest never run.

`GET /agents` lists the registry; `GET /agents?prompt=...` shows which specialists a prompt would use.

## Workflow agents

| Agent | Node | Owns | LLM? |
|---|---|---|---|
| Director | `understand`, `fix`, `finalize` | intent, routing, memory, retries, versions | optional (`PLANNER_MODE=local`) |
| Analyzer | `analyze` | per-clip measurements (scenes, motion curve, silences, loudness, words, beats, filming time) | no |
| Audio | `audio` | song choice (your upload > library), song feel / drop / energy, lyrics, voice & music levels, ducking, bass, loudness, mute | optional |
| Cutter | `cutter` | segments: silence/filler/idle removal, length, fast/beat cuts, song-driven cuts (energy → cut length, drop, song start), stutter / ramp, order, hook | optional |
| Color | `color` (parallel) | grade, LUT looks, exposure matching | optional |
| Effects | `effects` | canvas/reframe, captions, titles, transitions, motion/FX, timed FX, beat punches | optional |
| Reviewer | `review` | ~30 checks on the RENDERED file vs an independent keyword reading of the prompt; per-agent scores | no |

## Specialist categories (counts, from `registry_summary()`)

202 roles, 197 available: conversation 1 · intent 1 · prompt 1 · planning 2 · memory 1 · media analysis 2 · audio analysis 1 · color 13 · audio mixing 6 · timeline 3 · rendering 1 · quality control 1 · reviewer 2 · lessons 1 · error recovery 1 · export 5 · scene detection 1 · clip selection 2 · transcript 1 · silence 2 · caption 4 · subtitle styling 26 · pacing 3 · story structure 2 · music 1 · voice 1 · effects 54 · computer vision 1 · transitions 58 · video generation 1 · image generation 1 · broll 1 · enhancement 1

The five **unavailable** roles (video generation, image generation, AI B-roll, RIFE interpolation, Real-ESRGAN)
are listed with the reason; they need a GPU to be practical. CPU fallbacks are used instead.

## Router examples (from tests/integration/test_workflow.py)

| Prompt | Picked (besides the 17 core roles) | Not run |
|---|---|---|
| silence hata aur captions laga | clip selector, transcriber, silence remover, caption writer, subtitle stylist | colour LUTs, music, styles |
| warm cinematic bana | — | transcriber (speech-to-text is skipped for real), captions, clip selector |
| mast sa edit kar do | scene detector, clip selector, transcriber, story arranger, hook finder, auto editor | video generator |

## Scores and lessons

Every Reviewer check has an owner agent; failed checks cost points, and a failed check that an agent could have
avoided becomes a lesson (`lessons` table). Before the Director/agents run, their recent lessons (one per check) are filtered for relevance and added
to the LLM prompt — only lessons whose check matters for the current request (a "duration" lesson only when a
length was asked, etc.; `lesson_applies` in agents/base.py, tested in test_memory_fx.py). Footage limits ("nobody speaks in these clips") are marked `fixable: false`: they are reported,
not retried, and never turned into lessons.
