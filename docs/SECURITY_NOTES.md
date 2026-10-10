# Security notes (supply chain, licences, data) — 2026-10-09

## Supply chain
- **No new third-party package was added for the skill library.** Everything new is our own code: registry
  (`skill_registry.py`), resolver (`engines/stack.py`, `skill_apply.py`), motion engine (`engines/motion.py`),
  prompt enhancer (`prompt_enhancer.py`, `prenormalize.py`, `hindi.py`). `jsonschema` (MIT) and `PyYAML` (MIT) were
  already dependencies.
- **Not installed (BLOCKED, untrusted):** PyPI `color-fx` (repo created 2026-05-25, 0 stars, 3 releases) and `dhvani`
  (6 releases in 8 days in 2026-05, 0-follower account); HF `Singla0009/all-indic-transliteration` (new anonymous
  upload, 0 downloads). Their functions (colour looks, Hindi handling) are written in-house instead.
- Earlier additions and how they were checked: `llama-cpp-python==0.3.36` (MIT, pinned, prebuilt CPU wheel from the
  project's own wheel index — no build scripts run), `vosk` (Apache-2.0) + the Vosk Hindi model downloaded from
  alphacephei.com, GGUF models from Hugging Face with SHA-256 checked against the LFS object id
  (`backend/scripts/download_models.py`; a mismatch deletes the file).
- No `curl | sh` / piped install scripts were run.
- **Recommendation:** pin every requirement to an exact version and hash (`pip install --require-hashes`) before
  launch; today `backend/requirements.txt` uses `>=` ranges for older dependencies.

## Licences in the shipped product
- The Android app must contain only Apache / MIT / BSD / OFL code and assets (Media3, lottie-android, Noto fonts).
- FFmpeg here is a GPLv3 build (`--enable-gpl --enable-version3 --enable-libx264`): it runs only as a server
  process; it must never be bundled in the APK. If an on-device FFmpeg is ever needed: an LGPL build without
  `--enable-gpl`/`--enable-nonfree`, dynamically linked, with its source offered (ffmpeg.org/legal.html).
- RED items (never in the product): whisper-timestamped, python-lottie, Video2X (AGPL); glaxnimate,
  RobustVideoMatting, devhyper/open-video-editor, OpenVINO Audacity plugin (GPL); facebookresearch/denoiser and
  madmom models (non-commercial); Remotion (company licence); BRIA RMBG models (paid). A grep of `backend/` finds
  none of them imported.

## Data and prompts
- Transcripts, OCR text, file names and song lyrics are data, never instructions (planner prompt + router guards).
- The planner LLM gets only the text of an unclear clause; video never leaves the server.
- Per-client rate limit on edit requests (`RATE_LIMIT_PER_MIN`, 429), bounded LLM queue (busy → rules).
- Taste / memory are local to the deployment (SQLite) and can be reset (`DELETE /taste`).
