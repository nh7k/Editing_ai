"""beatmap.py: which beats get a hit — for ANY tempo / song shape (nothing tuned to one song)."""

from __future__ import annotations

import numpy as np
import pytest

from cutmind.beatmap import LEAD, MIN_GAP, kick_strength, plan_hits


def grid(bpm: float, total: float) -> list[float]:
    p = 60.0 / bpm
    return [round(k * p, 3) for k in range(1, int(total / p))]


@pytest.mark.parametrize("bpm", [70, 92, 100, 120, 128, 150, 160])
def test_density_follows_energy_at_every_tempo(bpm):
    total = 20.0
    beats = grid(bpm, total)
    calm = lambda t: 0.3 if t < 10 else 0.9  # noqa: E731 — a quiet first half, a loud second half
    bm = plan_hits(beats, calm, [0.5] * len(beats), total)
    first = [h for h in bm.hits if h.beat < 10]
    second = [h for h in bm.hits if h.beat >= 10]
    n1, n2 = sum(b < 10 for b in beats), sum(b >= 10 for b in beats)
    # calm: about every 4th beat; loud: (nearly) every beat, never closer than MIN_GAP
    assert len(first) <= n1 / 3 + 1
    assert len(second) >= min(n2, int((total - 10) / MIN_GAP)) * 0.6
    gaps = np.diff([h.t for h in bm.hits])
    assert gaps.size == 0 or gaps.min() >= MIN_GAP - 1e-6
    # every hit lands one frame BEFORE its beat
    assert all(abs((h.beat - h.t) - LEAD) < 1e-3 for h in bm.hits if h.beat > LEAD)


def test_bar_phase_follows_the_kick():
    beats = grid(120, 16)
    kicks = [1.0 if i % 4 == 2 else 0.2 for i in range(len(beats))]  # the "1" of the bar is beat index 2
    bm = plan_hits(beats, lambda t: 0.3, kicks, 16)
    assert bm.phase == 2
    assert all((beats.index(h.beat) - 2) % 4 == 0 for h in bm.hits)


def test_the_drop_hits_hardest_with_a_flash_and_a_shake():
    beats = grid(100, 20)
    drop = beats[14]
    bm = plan_hits(beats, lambda t: 0.5, [0.4] * len(beats), 20, drop=drop)
    d = next(h for h in bm.hits if abs(h.beat - drop) < 1e-6)
    assert d.kind == "drop" and d.strength == max(h.strength for h in bm.hits)
    assert d.t in bm.flashes and d.t in bm.shakes
    # after the drop: every beat for a while
    after = [h for h in bm.hits if drop < h.beat < drop + 4 * 0.6]
    assert len(after) >= 3


def test_no_hits_outside_the_video_and_none_without_beats():
    assert plan_hits([], lambda t: 0.9, [], 10).hits == []
    bm = plan_hits(grid(120, 30), lambda t: 0.9, [0.5] * 60, 10.0)
    assert bm.hits and max(h.beat for h in bm.hits) < 10.0


def test_kick_strength_finds_the_low_band_hits():
    sr = 22050
    t = np.arange(int(sr * 4)) / sr
    y = 0.05 * np.sin(2 * np.pi * 3000 * t)
    beats = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    for b in beats[::2]:  # a 60 Hz kick on every 2nd beat only
        i = int(b * sr)
        y[i:i + 1500] += 0.8 * np.sin(2 * np.pi * 60 * t[:1500]) * np.exp(-t[:1500] * 30)
    k = kick_strength(y.astype(np.float32), sr, beats)
    assert min(k[0], k[2], k[4]) > max(k[1], k[3], k[5]) + 0.3
