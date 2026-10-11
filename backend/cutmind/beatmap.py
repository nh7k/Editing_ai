"""Where the picture hits the music: from a song's beats + energy (song.py, librosa — ISC) and its kick drum
(low-band energy, numpy), choose WHICH beats get a punch / a flash / a shake, like a pro beat edit.

Rules (docs/BEAT_EDIT.md — from the research: onset/kick detection, energy → cut and hit density, accents a frame
BEFORE the beat, a budget so it never fatigues):
- density follows the song's energy at that moment: calm → every 4th beat (the bar's downbeat), medium → every 2nd,
  loud / after the drop → every beat;
- the bar phase (which beat is "1") is the offset 0-3 whose beats carry the most kick energy;
- the drop gets the strongest punch, a white flash and a short shake;
- every hit lands LEAD seconds before the beat (one frame at 30 fps: the eye needs it to feel "on" the beat);
- at least MIN_GAP between hits; strength grows with the energy and the kick there.
Pure functions, no I/O except reading the song's audio once (cached by the caller).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

LEAD = 0.033      # s before the beat (1 frame @30 fps)
MIN_GAP = 0.22    # s between two hits
CALM, LOUD = 0.45, 0.72  # energy thresholds (song.py energy is 0..1 over the song's last 30 dB)


@dataclass
class Hit:
    t: float              # output seconds (already LEAD before the beat)
    beat: float           # the beat it belongs to
    strength: float       # 0.4 .. 1.6 — punch size factor
    kind: str = "punch"   # punch | drop


@dataclass
class BeatMap:
    hits: list[Hit] = field(default_factory=list)
    flashes: list[float] = field(default_factory=list)
    shakes: list[float] = field(default_factory=list)
    phase: int = 0
    density: dict[str, int] = field(default_factory=dict)  # beats per hit used: {"calm": 4, ...} (said back)

    def times(self) -> list[float]:
        return [h.t for h in self.hits]


def kick_strength(y: np.ndarray, sr: int, beats: list[float], win: float = 0.08) -> list[float]:
    """Low-band (40-120 Hz) energy just after each beat, 0..1 (the kick drum)."""
    out = []
    n = int(sr * win)
    for b in beats:
        i = int(max(0.0, b) * sr)
        seg = y[i:i + n]
        if len(seg) < 64:
            out.append(0.0)
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        fr = np.fft.rfftfreq(len(seg), 1 / sr)
        out.append(float(spec[(fr >= 40) & (fr < 120)].sum()))
    k = np.array(out)
    if k.size == 0 or k.max() <= 0:
        return [0.0] * len(beats)
    k = np.log10(k + k.max() * 1e-4)
    k = (k - k.min()) / max(1e-9, k.max() - k.min())
    return [round(float(x), 3) for x in k]


def load_mono(path: Path, sr: int = 22050) -> np.ndarray:
    import subprocess

    from .ffmpeg_utils import ffmpeg_bin

    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True, timeout=120).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def plan_hits(beats: list[float], energy_at, kicks: list[float], total: float, drop: float | None = None,
              intensity: float = 1.0) -> BeatMap:
    """Choose the hits. `beats` in output seconds, `energy_at(t)` 0..1, `kicks` per beat 0..1."""
    bm = BeatMap()
    bs = [(b, kicks[i] if i < len(kicks) else 0.0) for i, b in enumerate(beats) if 0.05 <= b < total - 0.05]
    if not bs:
        return bm
    # bar phase: the offset whose beats carry the most kick
    bm.phase = max(range(4), key=lambda ph: sum(k for i, (_b, k) in enumerate(bs) if i % 4 == ph))
    last = -9.0
    used = {"calm": 0, "medium": 0, "loud": 0}
    for i, (b, k) in enumerate(bs):
        e = float(energy_at(b))
        after_drop = drop is not None and drop - 0.05 <= b <= drop + 8 * 0.7
        level = "loud" if e >= LOUD or after_drop else "medium" if e >= CALM else "calm"
        stride = {"calm": 4, "medium": 2, "loud": 1}[level]
        on_grid = (i - bm.phase) % stride == 0
        is_drop = drop is not None and abs(b - drop) < 0.06
        # a strong kick off the grid still hits in medium / loud parts (the drummer, not the counter, decides)
        if not (on_grid or is_drop or (level != "calm" and k >= 0.85)):
            continue
        t = round(max(0.0, b - LEAD), 3)
        if t - last < MIN_GAP:
            continue
        s = (0.55 + 0.55 * e + 0.35 * k) * intensity
        if is_drop:
            s = max(s, 1.5 * intensity)
            bm.flashes.append(t)
            bm.shakes.append(t)
        elif level == "loud" and (i - bm.phase) % 4 == 0 and len(bm.flashes) < 6 and k >= 0.7:
            bm.flashes.append(t)  # a downbeat of a loud part with a hard kick: a flash (a few, never all)
        bm.hits.append(Hit(t=t, beat=b, strength=round(min(1.6, s), 2), kind="drop" if is_drop else "punch"))
        used[level] += 1
        last = t
    bm.density = {"calm": 4, "medium": 2, "loud": 1}
    return bm
