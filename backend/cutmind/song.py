"""What the song "feels" like, so the edit can move with it.

From the music track (librosa, CPU, cached per file): tempo and beats, loudness energy every 0.5 s, how busy the
drums are (onsets per second), the drop (biggest jump in energy), the strong beats (above the song's median
energy) and an overall FEEL: slow / medium / fast. The agents use it for cut length, how hard the beat punches
are, which text animations fit, and where the big hits go.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from .ffmpeg_utils import extract_audio_wav

SONG_VERSION = 4  # 4: the beat grid is moved onto the kick drum (beatmap.kick_phase)
Feel = Literal["slow", "medium", "fast"]
STEP = 0.5  # seconds per energy value

# per feel: target seconds per cut, beat punch strength, kinetic text animations, beats a word stays on screen
STYLE: dict[str, dict[str, object]] = {
    "slow": {"cut_seconds": 2.0, "pulse": 0.45, "hold_beats": 4,
             "anims": ("fade", "blur_in", "cascade", "slide_up", "zoom_out", "typewriter", "glow_pulse")},
    "medium": {"cut_seconds": 1.0, "pulse": 0.85, "hold_beats": 2,
               "anims": ("pop", "zoom_in", "drop_in", "blur_in", "fly_left", "fly_right", "slide_up", "flip_in")},
    "fast": {"cut_seconds": 0.5, "pulse": 1.25, "hold_beats": 2,
             "anims": ("pop", "zoom_in", "shake", "flicker", "bounce", "drop_in", "heartbeat", "spin_in")},
}


@dataclass
class SongProfile:
    tempo: float = 0.0
    beats: list[float] = field(default_factory=list)
    energy: list[float] = field(default_factory=list)  # 0..1 every STEP seconds
    onset_rate: float = 0.0
    feel: Feel = "medium"
    drop: float | None = None
    strong_beats: list[float] = field(default_factory=list)
    duration: float = 0.0

    @property
    def period(self) -> float:
        b = self.beats
        return float(np.median(np.diff(b))) if len(b) > 2 else (60.0 / self.tempo if self.tempo else 0.5)

    def energy_at(self, t: float) -> float:
        if not self.energy:
            return 0.5
        return self.energy[min(len(self.energy) - 1, max(0, int(t / STEP)))]

    def mean_energy(self, a: float, b: float) -> float:
        vals = [self.energy_at(a + k * STEP) for k in range(max(1, int((b - a) / STEP)))]
        return float(np.mean(vals))

    def grid(self, until: float | None = None) -> list[float]:
        """A beat for every beat of the song: the tracked beats, with gaps (a drum-less intro, a break) filled at
        the tempo, extended back to 0 and forward to `until`; the drop is always on it."""
        p = max(self.period, 0.2)
        end = self.duration if until is None else until
        real = sorted(b for b in self.beats if b >= 0)
        if not real:
            real = [p]
        out: list[float] = []
        t = real[0]
        while t - p > 0.05:  # back to the start
            t -= p
            out.insert(0, round(t, 3))
        for a, b in zip(real, [*real[1:], None], strict=False):
            out.append(a)
            if b is not None and b - a > 1.5 * p:  # a gap: fill it evenly
                n = round((b - a) / p)
                out += [round(a + (b - a) * k / n, 3) for k in range(1, n)]
        while out[-1] + p < end + 1e-6:
            out.append(round(out[-1] + p, 3))
        if self.drop is not None:
            out = sorted({*(x for x in out if abs(x - self.drop) > 0.15), self.drop})
        return out

    def shifted(self, start: float) -> "SongProfile":
        """The song as heard when the music starts `start` seconds in (beats / energy / drop move with it)."""
        if start <= 0:
            return self
        k = int(round(start / STEP))
        return SongProfile(tempo=self.tempo, beats=[round(b - start, 3) for b in self.grid() if b >= start],
                           energy=self.energy[k:], onset_rate=self.onset_rate, feel=self.feel,
                           drop=None if self.drop is None or self.drop < start else round(self.drop - start, 3),
                           strong_beats=[round(b - start, 3) for b in self.strong_beats if b >= start],
                           duration=round(max(0.0, self.duration - start), 3))

    def start_for(self, length: float) -> float:
        """Where to start the song so its drop lands about 40 % into an edit of `length` seconds (on a beat).
        0 when the drop already falls inside, or there is no drop."""
        if self.drop is None or self.drop <= 0.75 * length:
            return 0.0
        want = self.drop - 0.4 * length
        return min((b for b in self.grid() if b <= want + 1e-6), default=0.0, key=lambda b: abs(b - want))

    def style(self) -> dict[str, object]:
        return STYLE[self.feel]

    def beats_per_cut(self) -> int:
        return max(1, round(float(self.style()["cut_seconds"]) / max(self.period, 0.2)))


def classify_feel(tempo: float, onset_rate: float) -> Feel:
    """Tempo alone is unreliable (librosa often halves / doubles it), so busy-ness of the drums decides too."""
    if tempo and tempo < 95 and onset_rate < 3.5:
        return "slow"
    if (tempo >= 115 and onset_rate >= 2.0) or onset_rate >= 4.5:
        return "fast"
    return "medium"


def _snap_drop(y: np.ndarray, sr: int, rough: float, beats: list[float]) -> float:
    """The beat near `rough` where loudness jumps the most (fine 50 ms loudness, 0.3 s before vs after)."""
    hop = int(sr * 0.05)
    rms = np.array([float(np.sqrt(np.mean(y[i:i + hop] ** 2))) for i in range(0, len(y), hop)]) + 1e-9
    db = 20 * np.log10(rms)

    def jump(t: float) -> float:
        k = int(t / 0.05)
        return float(db[k:k + 6].mean() - db[max(0, k - 6):k].mean()) if 6 <= k < len(db) - 6 else -99.0

    near = [b for b in beats if abs(b - rough) <= 0.8]
    best = max(near, key=jump, default=None)
    return round(best if best is not None else rough, 3)


def analyze_song(track: Path, work: Path, cache_dir: Path | None = None, only_cached: bool = False) -> SongProfile | None:
    """Song profile (cached per file). `only_cached`: None unless it was worked out before (for fast listings)."""
    st = track.stat()
    key = hashlib.sha1(f"{track.resolve()}|{st.st_size}|{st.st_mtime_ns}|{SONG_VERSION}".encode()).hexdigest()[:16]
    cache = cache_dir / f"song_{key}.json" if cache_dir else None
    if cache and cache.exists():
        try:
            return SongProfile(**json.loads(cache.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            pass
    if only_cached:
        return None
    import librosa

    work.mkdir(parents=True, exist_ok=True)
    wav = extract_audio_wav(track, work / f"song_{key}.wav", sr=22050)
    y, sr = librosa.load(str(wav), sr=22050, mono=True)
    prof = SongProfile(duration=round(len(y) / sr, 3))
    if y.size and float(np.abs(y).max()) > 1e-3:
        tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
        prof.tempo = round(float(np.atleast_1d(tempo)[0]), 1)
        prof.beats = [round(float(b), 3) for b in librosa.frames_to_time(frames, sr=sr)]
        from .beatmap import kick_phase

        off = kick_phase(y, sr, prof.beats, prof.duration)
        if off:  # the tracker sat on the off-beat: the beats (and everything placed on them) move onto the kick
            prof.beats = [round(b + off, 3) for b in prof.beats if b + off < prof.duration]
        hop = int(sr * STEP)
        rms = np.array([float(np.sqrt(np.mean(y[i:i + hop] ** 2))) for i in range(0, len(y), hop)]) + 1e-9
        db = 20 * np.log10(rms / rms.max())
        prof.energy = [round(float(x), 3) for x in np.clip((db + 30) / 30, 0, 1)]  # last 30 dB → 0..1
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        prof.onset_rate = round(len(onsets) / max(prof.duration, 1.0), 2)
        prof.feel = classify_feel(prof.tempo, prof.onset_rate)
        e = np.array(prof.energy)
        if len(e) > 6:
            rise = np.array([e[i:i + 4].mean() - e[max(0, i - 4):i].mean() for i in range(4, len(e) - 2)])
            if rise.size and rise.max() > 0.15:
                rough = (int(rise.argmax()) + 4) * STEP
                prof.drop = _snap_drop(y, sr, rough, prof.beats)
        med = float(np.median(e)) if len(e) else 0.5
        prof.strong_beats = [b for b in prof.beats if prof.energy_at(b) >= med]
    if cache:
        cache_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
        cache.write_text(json.dumps(asdict(prof)), encoding="utf-8")
    return prof
