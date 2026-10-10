# Models

| Model | Use | License | Size | Install |
|---|---|---|---|---|
| faster-whisper `tiny` (CTranslate2, int8) | captions, transcripts, voice prompts (`translate` → English) | MIT | ~75 MB | downloaded on first use |
| onnx-community/Qwen2.5-1.5B-Instruct `model_q4.onnx` | Director planner when `PLANNER_MODE=local` | Apache-2.0 | ~1.1 GB | `python -m cutmind.prefetch` |
| onnx-community/Qwen2.5-0.5B-Instruct `model_q4.onnx` | same, picked automatically with <3.5 GB free RAM | Apache-2.0 | ~0.5 GB | `LLM_REPO=auto` |

Settings: `PLANNER_MODE=mock|local`, `LLM_REPO=auto|<repo>`, `LLM_AGENTS=director` (which agents may call the LLM),
`WHISPER_MODEL=tiny|base|small`, `ENABLE_TRANSCRIPTION=1`.

Why these: they run in-process on CPU (no separate server — Ollama was evaluated and dropped at the user's request
and to keep one deployable service; llama-cpp-python's DLL is blocked by Windows Smart App Control), they are
permissively licensed, and the keyword guard + evidence gate keep a small model from inventing edits.

Not shipped (need a GPU to be practical): Wan / LTX-Video / HunyuanVideo / FramePack (video generation),
SD / Flux (images), RIFE (interpolation), Real-ESRGAN (upscaling). See CPU_MODE.md.

## Added 2026-10-07

| Model | Licence | Size | Where | Used for |
|---|---|---|---|---|
| PP-HumanSeg (OpenCV Zoo `human_segmentation_pphumanseg_2023mar.onnx`) | Apache-2.0 | 6 MB | `backend/assets/models/` | text behind the person |
| faster-whisper `base` (Systran) | MIT | ~140 MB | HuggingFace cache (downloaded on first use, no login) | song lyrics (`LYRICS_MODEL`, falls back to `tiny`) |

## Added 2026-10-08

| Model | Licence | Size | Where | Used for |
|---|---|---|---|---|
| Vosk `vosk-model-small-hi-0.22` (Alpha Cephei, Kaldi) | Apache-2.0 per the Vosk model list (check the official table) | 45 MB zip / 79 MB unpacked, ~300 MB RAM | `backend/assets/models/vosk-hi/` (from alphacephei.com/vosk/models) | Hindi speech → words with times. Picked when whisper's language check says `hi`: on a real Hindi podcast whisper tiny/base looped or wrote Urdu letters, Vosk read it cleanly (~11 s for 33 s). Words are romanised to Hinglish (`cutmind/hindi.py`) for captions and sticker words; the Devanagari stays in `Word.native`. |

Removed 2026-10-08 (not used by the running app; downloaded again only if `PLANNER_MODE=local` is used): the base
Qwen2.5-0.5B / 1.5B ONNX models and the translator benchmark candidates Qwen3-1.7B / Gemma-3-1B. The fine-tuned
translator in `backend/assets/models/translator/` (it beat Qwen3-1.7B and Gemma-3-1B on our Hinglish set) stays.
