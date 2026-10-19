"""Analyzer agent: measures every clip (no LLM — pure measurement, cached per clip)."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, field_validator

from ..ffmpeg_utils import detect_silence, extract_audio_wav, ffmpeg_bin, measure_loudness, probe, run_ffmpeg
from ..photos import is_photo
from .base import AgentContext, AgentResult, BaseAgent, ClipRef, Feedback

ANALYSIS_VERSION = 8
# voice for this share of the clip = people talk in it (a podcast measured 0.77; a song WITH vocals 0.48)
VOICE_TALKING = 0.6


class Word(BaseModel):
    text: str
    start: float
    end: float
    prob: float = 1.0
    native: str = ""  # the word in its own script when `text` is a romanised form (Hindi: गुलाब → text "gulab")


class ClipAnalysis(BaseModel):
    clip_id: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    scenes: list[float] = Field(default_factory=list, description="scene cut times (s)")
    silences: list[tuple[float, float]] = Field(default_factory=list)
    idle: list[tuple[float, float]] = Field(default_factory=list, description="frozen / static stretches (s)")
    words: list[Word] = Field(default_factory=list)
    transcript: str = ""
    transcription: str = "skipped"  # ok | skipped | unavailable | error:<msg>
    # share of the clip where a human voice is heard (silero VAD) — people can be talking even when speech-to-text
    # can't read the words (a noisy Hindi podcast gave whisper-base nothing usable; it is still a talking video)
    voice_share: float = 0.0
    language: str = ""   # spoken language (whisper's guess, e.g. "hi", "en")
    stt: str = ""        # which speech-to-text read it: "whisper-<model>" / "vosk-hi"
    loudness: dict[str, float] = Field(default_factory=dict)

    @field_validator("loudness", mode="before")
    @classmethod
    def _finite_loudness(cls, v: Any) -> Any:
        # -inf (silent track) is written to the JSON cache as null: read it back as "very quiet"
        return {k: (-99.0 if x is None else x) for k, x in v.items()} if isinstance(v, dict) else v
    sharpness: float = 0.0
    motion: float = 0.0
    luma: float = 0.5               # mean brightness 0..1
    rgb_mean: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    tempo: float | None = None
    beats: list[float] = Field(default_factory=list)
    quality: float = 0.0            # combined sharpness/motion score 0..1 (for "best moments")
    motion_curve: list[float] = Field(default_factory=list, description="picture change per 0.5 s (for hook shots)")
    recorded_at: float | None = None  # when it was filmed (epoch s), from the file name or metadata — for smart order

    @property
    def has_speech(self) -> bool:
        return len(self.words) > 0 or self.voice_share >= VOICE_TALKING

    @property
    def has_words(self) -> bool:
        return len(self.words) > 0


class ProjectAnalysis(BaseModel):
    clips: dict[str, ClipAnalysis]

    def get(self, clip_id: str) -> ClipAnalysis:
        return self.clips[clip_id]

    @property
    def any_speech(self) -> bool:
        return any(c.has_speech for c in self.clips.values())

    @property
    def any_words(self) -> bool:
        return any(c.has_words for c in self.clips.values())


# ---- faster-whisper (loaded lazily, once per process) --------------------------------------------
_whisper_lock = threading.Lock()
_whisper_models: dict[str, Any] = {}


_clip_locks: dict[str, threading.Lock] = {}
_stt_lock = threading.Lock()
_clip_locks_guard = threading.Lock()


def _clip_lock(key: str) -> threading.Lock:
    """One analysis per clip at a time (upload-time preparation and a job may overlap)."""
    with _clip_locks_guard:
        return _clip_locks.setdefault(key, threading.Lock())


def import_faster_whisper() -> Any:
    """Import faster-whisper even when PyAV can't load.

    faster-whisper imports PyAV at import time only for `decode_audio`, which we never call (we pass
    16 kHz samples decoded by FFmpeg). On Windows, Smart App Control can block PyAV's DLLs; in that case
    a placeholder module is registered so the rest of faster-whisper still works.
    """
    try:
        import faster_whisper
    except ImportError:
        for name in [m for m in sys.modules if m == "av" or m.startswith("av.") or m.startswith("faster_whisper")]:
            del sys.modules[name]
        sys.modules["av"] = types.ModuleType("av")  # placeholder: decode_audio is never used
        import faster_whisper
    return faster_whisper


def _whisper(model_name: str) -> Any:
    with _whisper_lock:
        if model_name not in _whisper_models:
            fw = import_faster_whisper()  # heavy import, only when needed
            _whisper_models[model_name] = fw.WhisperModel(model_name, device="cpu", compute_type="int8")
        return _whisper_models[model_name]


def voice_share(wav: Path) -> float:
    """Share of the audio where a human voice is heard (silero VAD bundled with faster-whisper; ~1 s per 30 s)."""
    import soundfile as sf

    try:
        import_faster_whisper()
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        audio, sr = sf.read(str(wav), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000 or not len(audio):
            return 0.0
        ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300))
        return round(sum(x["end"] - x["start"] for x in ts) / len(audio), 3)
    except Exception:  # noqa: BLE001 — an optional measurement
        return 0.0


VOSK_HI = Path(__file__).resolve().parent.parent.parent / "assets" / "models" / "vosk-hi"
_vosk_model: Any = None


def spoken_language(wav: Path, model_name: str) -> str:
    """Whisper's language guess only (first 30 s, ~4 s on CPU) — no full decode."""
    import soundfile as sf

    try:
        audio, _sr = sf.read(str(wav), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        lang, prob, *_ = _whisper(model_name).detect_language(audio)
        return str(lang) if prob >= 0.5 else ""
    except Exception:  # noqa: BLE001 — older faster-whisper: the full decode decides
        return ""


def vosk_hindi_available() -> bool:
    if not (VOSK_HI / "am").exists():
        return False
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False
    return True


def vosk_hindi(wav: Path) -> tuple[list[Word], str]:
    """Hindi speech → words (Hinglish text, Devanagari kept in `native`) with times. CPU, ~0.3 s per audio second."""
    import json as _json

    import soundfile as sf
    import vosk

    from ..hindi import romanize

    global _vosk_model
    with _whisper_lock:
        if _vosk_model is None:
            vosk.SetLogLevel(-1)
            _vosk_model = vosk.Model(str(VOSK_HI))
    audio, sr = sf.read(str(wav), dtype="int16")
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype("int16")
    rec = vosk.KaldiRecognizer(_vosk_model, sr)
    rec.SetWords(True)
    raw: list[dict[str, Any]] = []
    for i in range(0, len(audio), 8000):
        if rec.AcceptWaveform(audio[i:i + 8000].tobytes()):
            raw += _json.loads(rec.Result()).get("result", [])
    raw += _json.loads(rec.FinalResult()).get("result", [])
    words = [Word(text=romanize(w["word"]), native=w["word"], start=round(w["start"], 3), end=round(w["end"], 3),
                  prob=round(float(w.get("conf", 1.0)), 3)) for w in raw if float(w.get("conf", 1.0)) >= 0.3]
    return words, " ".join(w.text for w in words)


def transcribe(wav: Path, model_name: str) -> tuple[list[Word], str]:
    words, text, _lang = transcribe_lang(wav, model_name)
    return words, text


def transcribe_lang(wav: Path, model_name: str) -> tuple[list[Word], str, str]:
    import soundfile as sf

    model = _whisper(model_name)
    # pass samples, not a path: avoids faster-whisper's PyAV decoder (version-sensitive)
    audio, sr = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        raise ValueError(f"expected 16 kHz audio, got {sr}")
    # temperature=0: no random re-decoding on hard audio — deterministic and ~7x faster on noisy clips
    segments, info = model.transcribe(audio, word_timestamps=True, beam_size=1, vad_filter=False,
                                      condition_on_previous_text=False, temperature=0.0)
    words: list[Word] = []
    texts: list[str] = []
    for seg in segments:
        # whisper's own hallucination signals: repetitive text ("पादे पादे पादे…" on room noise, seen on a
        # user clip) has a huge compression ratio; made-up sentences have a very low average log-prob
        if seg.no_speech_prob > 0.6 or seg.compression_ratio > 2.4 or seg.avg_logprob < -1.0:
            continue
        texts.append(seg.text.strip())
        for w in seg.words or []:
            if w.probability < 0.3 or not w.word.strip():
                continue
            words.append(Word(text=w.word.strip(), start=round(w.start, 3), end=round(w.end, 3), prob=round(w.probability, 3)))
    return words, " ".join(texts).strip(), str(getattr(info, "language", "") or "")


_NAME_TS = re.compile(r"(20\d\d)[-_.]?(\d\d)[-_.]?(\d\d)[-_. T]?(?:(\d\d)[-_.:]?(\d\d)[-_.:]?(\d\d))?")


def recording_time(filename: str, created: str | None) -> float | None:
    """When a clip was filmed. Camera / phone file names carry it (IMG_20260930_151012, 20260930151012.avi,
    VID-20260930-WA0012); otherwise the container's creation_time tag. None if unknown."""
    from datetime import datetime, timezone

    m = _NAME_TS.search(Path(filename).stem)
    if m:
        y, mo, d, hh, mi, ss = (int(x) if x else 0 for x in m.groups())
        try:
            t = datetime(y, mo, d, hh, mi, ss, tzinfo=timezone.utc).timestamp()
            wa = re.search(r"WA(\d{1,5})", filename, re.I)  # WhatsApp: same date, running number
            return t + (int(wa.group(1)) if wa and not m.group(4) else 0)
        except ValueError:
            pass
    if created:
        try:
            return datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def voice_to_prompt(wav: Path, model_name: str) -> tuple[str, str | None]:
    """A spoken edit request (Hindi, Hinglish, English, …) → English text the planner understands.

    Whisper's built-in `translate` task does speech → English in one pass, locally. Returns (text, language).
    """
    import soundfile as sf

    audio, sr = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        raise ValueError(f"expected 16 kHz audio, got {sr}")
    segments, info = _whisper(model_name).transcribe(audio, task="translate", beam_size=1, vad_filter=False,
                                                     condition_on_previous_text=False, temperature=0.0)
    texts = [s.text.strip() for s in segments
             if not (s.no_speech_prob > 0.6 or s.compression_ratio > 2.4 or s.avg_logprob < -1.0)]
    return " ".join(t for t in texts if t).strip(), getattr(info, "language", None)


def visual_stats(path: Path, duration: float) -> dict[str, Any]:
    """Sample small frames at 2 fps: sharpness (Laplacian variance), motion (frame diff), colour means."""
    import cv2

    w, h = 160, 90
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-vf", f"fps=2,scale={w}:{h}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=300).stdout
    n = len(raw) // (w * h * 3)
    if n == 0:
        return {"sharpness": 0.0, "motion": 0.0, "luma": 0.5, "rgb_mean": [0.0, 0.0, 0.0], "motion_curve": []}
    frames = np.frombuffer(raw[: n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)
    gray = frames.mean(axis=3).astype(np.float32)
    sharp = float(np.mean([cv2.Laplacian(g, cv2.CV_32F).var() for g in gray]))
    motion = float(np.mean(np.abs(np.diff(gray, axis=0)))) if n > 1 else 0.0
    rgb = frames.reshape(-1, 3).mean(axis=0)
    curve = [round(float(x), 2) for x in np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2))] if n > 1 else []
    return {"sharpness": sharp, "motion": motion, "luma": float(gray.mean() / 255.0), "rgb_mean": [float(x) for x in rgb],
            "motion_curve": curve}


def detect_idle(path: Path, min_seconds: float = 1.5) -> list[tuple[float, float]]:
    """Stretches where the picture doesn't change (FFmpeg freezedetect on a small, 10 fps copy)."""
    try:
        log = run_ffmpeg(["-i", str(path), "-map", "0:v:0", "-vf",
                          f"fps=10,scale=320:-2,freezedetect=n=0.003:d={min_seconds}", "-f", "null", "-"])
    except Exception:  # noqa: BLE001 — best effort
        return []
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", log)]
    out = list(zip(starts, ends, strict=False))
    if len(starts) > len(ends):  # frozen until the end of the clip
        out.append((starts[-1], probe(path).duration))
    return [(round(s, 3), round(e, 3)) for s, e in out]


def detect_scenes(path: Path) -> list[float]:
    try:
        from scenedetect import ContentDetector, detect

        scenes = detect(str(path), ContentDetector(threshold=27.0), show_progress=False)
        return [round(s[0].get_seconds(), 3) for s in scenes[1:]]
    except Exception:  # noqa: BLE001 — scene detection is best-effort
        return []


def beat_grid(wav: Path) -> tuple[float | None, list[float]]:
    try:
        import librosa

        y, sr = librosa.load(str(wav), sr=22050, mono=True)
        if y.size == 0 or float(np.abs(y).max()) < 1e-3:
            return None, []
        tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
        beats = librosa.frames_to_time(frames, sr=sr).tolist()
        return float(np.atleast_1d(tempo)[0]), [round(b, 3) for b in beats]
    except Exception:  # noqa: BLE001
        return None, []


class AnalyzerAgent(BaseAgent):
    name = "analyzer"
    system_prompt = "You measure video clips. (Deterministic — no LLM is used.)"

    def _cache_path(self, ctx: AgentContext, clip: ClipRef, transcribed: bool | None = None) -> Path | None:
        """Per-clip cache. `transcribed` picks the variant with / without speech-to-text."""
        if ctx.work_dir is None:
            return None
        if transcribed is None:
            transcribed = ctx.settings.enable_transcription
        stat = clip.path.stat()
        key = hashlib.sha1(
            f"{ANALYSIS_VERSION}|{clip.path}|{stat.st_size}|{stat.st_mtime_ns}|{transcribed}|"
            f"{ctx.settings.whisper_model}".encode()
        ).hexdigest()[:16]
        cache_dir = ctx.work_dir.parent.parent / "analysis"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{clip.id}_{key}.json"

    def analyze_clip(self, ctx: AgentContext, clip: ClipRef, tmp: Path, transcribe_speech: bool = True) -> ClipAnalysis:
        info = probe(clip.path)  # original size / fps are what the user uploaded
        media = clip.media       # decode the light proxy when there is one (same timeline)
        a = ClipAnalysis(clip_id=clip.id, duration=info.duration, width=info.width, height=info.height,
                         fps=info.fps, has_audio=info.has_audio)
        a.recorded_at = recording_time(clip.filename, info.created)

        def picture() -> None:
            vs = visual_stats(media, info.duration)
            a.sharpness, a.motion, a.luma, a.rgb_mean = vs["sharpness"], vs["motion"], vs["luma"], vs["rgb_mean"]
            a.motion_curve = vs["motion_curve"]

        def sound() -> None:
            if not info.has_audio:
                return
            a.silences = [(round(s, 3), round(e, 3)) for s, e in detect_silence(clip.path)]
            # audio-only steps read the ORIGINAL (decoding just the audio track is cheap and avoids a re-encode)
            a.loudness = measure_loudness(clip.path)
            wav = extract_audio_wav(clip.path, tmp / f"{clip.id}.wav", sr=16000)
            silent_total = sum(e - s for s, e in a.silences)
            if transcribe_speech and silent_total < info.duration - 0.3:
                try:
                    with _stt_lock:  # one whisper decode at a time (it already uses every core)
                        lang = spoken_language(wav, ctx.settings.whisper_model) if vosk_hindi_available() else ""
                        if lang in ("hi", "ur"):
                            # Hindi: whisper tiny/base looped ("देगा देगा…") or wrote Urdu letters on a real
                            # podcast; the 45 MB Kaldi Hindi model read it cleanly, with word times
                            a.words, a.transcript = vosk_hindi(wav)
                            a.language, a.stt = "hi", "vosk-hi"
                        else:
                            a.words, a.transcript, a.language = transcribe_lang(wav, ctx.settings.whisper_model)
                            a.stt = f"whisper-{ctx.settings.whisper_model}"
                    a.transcription = "ok"
                except ImportError:
                    a.transcription = "unavailable"
                except Exception as exc:  # noqa: BLE001 — never fail the job because STT failed
                    a.transcription = f"error:{str(exc)[:120]}"
                if a.transcription == "ok":
                    a.voice_share = voice_share(wav)
            a.tempo, a.beats = beat_grid(wav)

        def scenes() -> None:
            a.scenes = detect_scenes(media)

        def idle() -> None:
            # a photo is still on purpose, not frozen footage: before, the auto edit cut both photos of a "car edit
            # with 2 photos" away as idle ("nothing to keep")
            a.idle = [] if is_photo(clip.filename) else detect_idle(media)

        # independent measurements run side by side (each is mostly an FFmpeg decode)
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="analyze") as pool:
            for f in [pool.submit(fn) for fn in (sound, picture, scenes, idle)]:
                f.result()
        return a

    def rules(self, ctx: AgentContext, feedback: list[Feedback] | None) -> dict[str, Any]:
        tmp = (ctx.work_dir or Path(".")) / "analyzer_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        results: dict[str, ClipAnalysis] = {}

        def one(clip: ClipRef) -> None:
            # the upload-time preparation thread may be analysing this clip right now: wait for it
            with _clip_lock(str(clip.path)):
                self._analyze_one(ctx, clip, tmp, results)

        with ThreadPoolExecutor(max_workers=min(2, max(1, len(ctx.clips))), thread_name_prefix="clip") as pool:
            for f in [pool.submit(one, c) for c in ctx.clips]:
                f.result()
        results = {c.id: results[c.id] for c in ctx.clips}
        self._finish(results)
        analysis = ProjectAnalysis(clips=results)
        ctx.analysis = analysis
        return json.loads(analysis.model_dump_json())

    def _analyze_one(self, ctx: AgentContext, clip: ClipRef, tmp: Path, results: dict[str, ClipAnalysis]) -> None:
        want = ctx.settings.enable_transcription and ctx.need_transcript
        full = self._cache_path(ctx, clip, ctx.settings.enable_transcription)
        part = self._cache_path(ctx, clip, False)
        # a cache WITH speech-to-text serves every request; one without it only requests that don't need words
        for cache in (full, None if want else part):
            if cache and cache.exists():
                results[clip.id] = ClipAnalysis.model_validate_json(cache.read_text(encoding="utf-8"))
                ctx.log(self.name, "info", f"{clip.filename}: analysis loaded from cache")
                return
        ctx.log(self.name, "info", f"analyzing {clip.filename}" + ("" if want else " (no speech-to-text needed)"))
        a = self.analyze_clip(ctx, clip, tmp, transcribe_speech=want)
        results[clip.id] = a
        cache = full if want or not ctx.settings.enable_transcription else part
        if cache and not a.transcription.startswith("error"):  # never cache a failed transcription
            cache.write_text(a.model_dump_json(), encoding="utf-8")
        ctx.log(self.name, "info",
                f"{clip.filename}: {a.duration:.1f}s {a.width}x{a.height}, {len(a.scenes)} scene cuts, "
                f"{len(a.silences)} silences, {len(a.words)} words ({a.transcription}), tempo={a.tempo and round(a.tempo)}")

    @staticmethod
    def _finish(results: dict[str, ClipAnalysis]) -> None:
        # quality = normalised sharpness*motion so "best moments" can rank clips
        if results:
            sharp_max = max(r.sharpness for r in results.values()) or 1.0
            motion_max = max(r.motion for r in results.values()) or 1.0
            for r in results.values():
                r.quality = round(0.6 * r.sharpness / sharp_max + 0.4 * r.motion / motion_max, 3)

    def run(self, ctx: AgentContext, feedback: list[Feedback] | None = None, attempt: int = 1) -> AgentResult:
        output = self.rules(ctx, feedback)
        if ctx.db is not None:
            ctx.db.record_run(ctx.job_id, self.name, attempt, "measure clips", {"clips": list(output["clips"].keys())}, "rules")
        return AgentResult(self.name, output, "rules", "measure clips")
