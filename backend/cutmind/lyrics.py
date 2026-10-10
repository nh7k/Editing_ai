"""The sung words of a song, with their times (for lyric text: "TOO / COLD" landing as they are sung).

faster-whisper on CPU (LYRICS_MODEL, default "base": the "tiny" model used for speech misses most sung words).
Singing over loud music is hard for any speech model, so only confident words are kept and the result is
cached per song file. Songs without (clear) vocals simply give no words — the edit then uses the subject's name.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .agents.analyzer import Word, _whisper, spoken_language, vosk_hindi, vosk_hindi_available
from .ffmpeg_utils import extract_audio_wav

LYRICS_VERSION = 2  # 2: Hindi songs read by the Vosk Hindi model (whisper looped on them)
MIN_PROB = 0.35


def lyrics_model() -> str:
    return os.environ.get("LYRICS_MODEL", "base")


def song_words(track: Path, work: Path, cache_dir: Path | None = None, only_cached: bool = False) -> list[Word] | None:
    """Sung words with times (song seconds). `only_cached`: None unless they were worked out before."""
    st = track.stat()
    model = lyrics_model()
    key = hashlib.sha1(f"{track.resolve()}|{st.st_size}|{st.st_mtime_ns}|{model}|{LYRICS_VERSION}".encode()).hexdigest()[:16]
    cache = cache_dir / f"lyrics_{key}.json" if cache_dir else None
    if cache and cache.exists():
        try:
            return [Word(**w) for w in json.loads(cache.read_text(encoding="utf-8"))]
        except (ValueError, TypeError):
            pass
    if only_cached:
        return None
    import soundfile as sf

    work.mkdir(parents=True, exist_ok=True)
    wav = extract_audio_wav(track, work / f"lyrics_{key}.wav", sr=16000)
    audio, _sr = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if vosk_hindi_available() and spoken_language(wav, "tiny") in ("hi", "ur"):
        # a Hindi song: Vosk read "dekhte dekhte mujhe pyar…" off a real reel; whisper looped or wrote Urdu letters
        words = [w for w in vosk_hindi(wav)[0] if w.prob >= 0.6]
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps([w.model_dump() for w in words], ensure_ascii=False), encoding="utf-8")
        return words
    try:
        m = _whisper(model)
    except Exception:  # noqa: BLE001 — model not downloadable here: the small model still finds clear vocals
        m = _whisper("tiny")
    segments, _info = m.transcribe(audio, word_timestamps=True, beam_size=1, vad_filter=False,
                                   condition_on_previous_text=False, temperature=0.0)
    words: list[Word] = []
    for seg in segments:
        if seg.no_speech_prob > 0.85 or seg.compression_ratio > 2.4:
            continue  # music only / repeated hallucination
        for w in seg.words or []:
            text = re.sub(r"[^\w'’-]+", "", w.word, flags=re.UNICODE).strip("'’-")
            if text and w.probability >= MIN_PROB and w.end > w.start:
                words.append(Word(text=text, start=round(w.start, 3), end=round(w.end, 3), prob=round(w.probability, 3)))
    if cache:
        cache_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
        cache.write_text(json.dumps([w.model_dump() for w in words]), encoding="utf-8")
    return words
