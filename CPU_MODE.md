# CPU mode (the default — no GPU needed)

CutMind is built for a laptop without a graphics card. `GET /capabilities` shows what was detected.

## What runs on the CPU

| Job | Tool | Notes |
|---|---|---|
| Cuts, trims, speed, reverse, rotate, crop/reframe, colour, LUTs, 58 transitions, 38 FX, text | FFmpeg | deterministic filters, no AI generation |
| Scene detection | PySceneDetect | on the 720p proxy |
| Silence / idle detection, loudness | FFmpeg `silencedetect`, `freezedetect`, `loudnorm` | |
| Speech-to-text, captions, voice prompts | faster-whisper `tiny`, int8 | `WHISPER_MODEL=base`/`small` = better Hindi, slower |
| Beats | librosa | cached per music track |
| Prompt understanding | rule parser (instant) + optional in-process Qwen2.5 1.5B/0.5B int4 (ONNX Runtime) | auto-picks 0.5B when <3.5 GB RAM is free |

## Speed features

* 720p30 **proxies** made at upload; ≤720p renders decode them, not the 4K originals.
* Per-clip **analysis cache** (with/without speech-to-text), **music beat cache**.
* **Parallel**: 4 measurements per clip, 2 clips at a time; segments render 2–4 at a time (`RENDER_WORKERS`);
  colour plans in parallel with audio → cutter.
* **Router**: speech-to-text is skipped when the edit doesn't use words.
* One version by default (3 styled versions only when asked).
* No retry when a failure can't be fixed; retries stop when they change nothing.

Measured on this laptop (12 threads, <1 GB free RAM): Hinglish 30 s reel from three 4K clips — 60 s end to end
(was 243 s before this pass); auto edit of the user's 37 s footage — 45 s (was 13 min).

## Not available without a GPU

AI video generation (Wan, LTX-Video, HunyuanVideo, FramePack), AI image generation (SD/Flux), AI B-roll,
RIFE interpolation, Real-ESRGAN upscaling. They show as
`disabled — GPU feature unavailable — using CPU/local fallback` and the edit continues with FFmpeg equivalents.
