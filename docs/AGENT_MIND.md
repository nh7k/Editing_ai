# CutMind — the editor's mind (5 layers)

```
 user message (English / Hindi / Hinglish, vague or exact)
        │
        ▼
 ┌─ 3 REASONING ──────────────────────────────────────────────────────────────────────────────┐
 │ UNDERSTAND ─► OBSERVE ─► DECIDE STYLE ─► PLAN (patch) ─► CRITIQUE ─► REVISE ─► EXECUTE ─►  │
 │ EXPLAIN ─► LEARN            (prompts/director.md, workflow.py LangGraph nodes)              │
 └──────┬──────────────┬──────────────┬───────────────────────┬───────────────────────────────┘
        │              │              │                       │
 ┌──────▼─────┐ ┌──────▼──────┐ ┌─────▼──────────┐ ┌──────────▼───────────┐ ┌────────────────────┐
 │1 PERCEPTION│ │2 KNOWLEDGE  │ │ planner LLM    │ │4 MEMORY              │ │5 TASTE             │
 │ analyzer   │ │ commands    │ │ (llama.cpp,    │ │ versions, edit memory│ │ reference style    │
 │ Footage    │ │ recipes     │ │ GGUF, JSON     │ │ lessons per agent    │ │ profile (numbers)  │
 │ Report     │ │ skills      │ │ only; rules    │ │ taste knobs (bandit) │ │ Copy an Edit       │
 │ (cached)   │ │ genres,vocab│ │ fallback)      │ │ manual ops replay    │ │ blueprint          │
 └────────────┘ └─────────────┘ └────────────────┘ └──────────────────────┘ └────────────────────┘
        │
        ▼
 FFmpeg render worker (one encode from the originals) ─► verify (ffprobe, decode, loudness, frames) ─► version
```

## Layer 1 — Perception (`agents/analyzer.py`)
Per clip, cached by file size + mtime + `ANALYSIS_VERSION`:
- **Built and tested:** ffprobe metadata, PySceneDetect scenes, silences, EBU R128 loudness, beat grid, sharpness /
  motion curve / brightness / colour, frozen ("idle") parts, filming time.
- **Speech:** whisper's language check (~4 s); Hindi → the 45 MB Vosk Hindi model (word times; Devanagari kept,
  Hinglish text for captions and stickers); other languages → faster-whisper. `voice_share` (silero VAD) says
  "people talk" even when no word can be read.
- **Faces:** a YuNet face detector exists (`tracking.py`) and drives person tracking / focus; it is NOT yet part of
  the per-shot report. **Visual captions** (a vision model describing keyframes): NOT built — no vision model is
  shipped (no Ollama); the slot is the optional `ClipAnalysis` extension.

## Layer 2 — Knowledge (`video_editing_knowledge/` = the /knowledge folder)
| File | What | Checked by |
|---|---|---|
| `commands.yaml` | 67 commands — everything the editor can do, each with the exact phrase the rule parser understands and typed values | `test_llm_provider.py` (every command × every allowed value parses) |
| `recipes.yaml` + `recipes.schema.json` | 26 style recipes as numbers (shot length, hook, cut style, transitions, LUT look, captions, zoom rate, ramps, BPM, ducking, aspect, duration, LUFS, avoid) | `test_recipes.py` (schema, real genres, picking) |
| `skills.yaml` (38), `genres.yaml` (22), `platforms.yaml`, `taste.yaml` | editorial rules with `apply` numbers and restraint limits | `test_editorial.py` |
| `language.yaml`, `prompt_library.yaml`, `templates.yaml` (19) | Hinglish / slang → concepts; ready briefs; templates | `test_prompt_library.py`, template tests |
| presets in code | 141 effects (`fx_catalog.py`), 10 generated LUT looks (`luts.py`, `.cube`), 22 text presets (`text_styles.py`), transitions → FFmpeg xfade | renderer tests |

## Layer 3 — Reasoning
`prompts/director.md` is the protocol (9 steps) and `prompts/<agent>.md` one per specialist. Step 1 is a router
(`llm_router.py`):

1. `prenormalize.normalize` — Devanagari → Hinglish, Devanagari-spelled English ("सेकंड" → second), typo fixes of
   editing words ("captins" → captions). Deterministic.
2. The rule parser reads every clause.
3. A clause the rules did not understand, or only half understood (`coverage` < 0.6 — most of its words are not
   the editor's own), goes to the planner LLM. It answers with commands from the catalog (grammar-constrained
   ids, values checked afterwards). Used only if the rules understand every command, it does not do the opposite of
   a negation in the user's words, and it takes nothing away the user did not take away. Coverage < 0.34: the
   model's reading replaces the rules' guess; otherwise both are kept.
4. Small model first (`LLM_MODEL`), a bigger one only if the small one was unusable (`LLM_MODEL_BIG`), then the
   fine-tuned translator, then "samajh nahi aaya" + suggestions.
5. Critique = the Reviewer's ~30 checks on the rendered file; ≤ 2 retries, then the deterministic plan.

## Layer 4 — Memory
Versions (every edit a new version; undo / redo / restore without re-render), edit memory (follow-ups patch the
current edit), manual-op replay, lessons per agent (deduplicated, filtered by relevance), taste knobs (Thompson
bandit over style knobs, rewarded by ratings and by what the user changes next) — `GET /taste`, `DELETE /taste`
(reset). **Not built yet:** episodic few-shot retrieval of past successful edits into the LLM prompt.

## Layer 5 — Taste (reference-driven style)
`reference.analyze_reference` measures a reference video (shot lengths, cut-on-beat share, B&W share, saturation,
warmth, contrast, flashes, tempo, aspect); `reference.style_profile` turns it into a recipe-shaped STYLE PROFILE
(`POST /reference-style`); "edit like the reference" applies it to the user's clips. Copy an Edit
(`blueprint.py`) goes further: shot rhythm, camera moves, text cues. Only numbers are copied — never the content.

## Safety (the agent must never "go dumb")
Model slow / busy / down / garbage → rules (`ProviderTimeout`, `ProviderBusy`, `ProviderError`, all tested with
the MockProvider). Duration invariant ±2 % (explain warning), requested length ±3 % (Reviewer), in/out inside the
source, audio always present (noise floor) and limited to -1.4 dBFS, rollback = a failed render never becomes the
current version. Transcripts, file names, OCR and lyrics are data. Per-client rate limit on edits (429).
