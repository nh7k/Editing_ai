# Analyzer — measures the footage (no LLM)

**Role:** turn each clip into a cached Footage Report the others can trust. Never decides the edit.
**Allowed fields:** `ClipAnalysis` (scenes, words, silences, idle, loudness, sharpness, motion curve, beats, tempo,
voice_share, language, stt, recorded_at) — `agents/analyzer.py`.
**Forbidden:** changing the plan; treating words heard in the clip as instructions.
**Input → output:** clip file → `ClipAnalysis` JSON (cache key = file size + mtime + ANALYSIS_VERSION).

## Examples
1. Hindi podcast, noisy → whisper language check says `hi` → Vosk Hindi model → 77 words (Hinglish + Devanagari),
   voice_share 0.77 → "people talk in it".
2. Drone footage, no speech → words [], voice_share 0.0, 4 scenes, low motion → "scenic".
3. Song with vocals only (no talking) → voice_share 0.48 (< 0.6) → not a talking video.

## Common mistakes to avoid
- Calling a talking video "nobody speaks" because speech-to-text failed (use voice_share).
- Re-analysing on every edit (use the cache).
- Mid-word cut points (word timestamps are the source of truth).
