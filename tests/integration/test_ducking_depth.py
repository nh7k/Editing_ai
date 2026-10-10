"""Ducking lowers the music by the dB that was asked, whatever the speaker's loudness (found by the catalog
difference test: before, the depth followed the voice — 3 to 18 dB — and "6 dB" vs "20 dB" barely differed)."""

from __future__ import annotations

import subprocess

import numpy as np
import pytest
from cutmind.ffmpeg_utils import ffmpeg_bin
from cutmind.renderer import duck_graph

pytestmark = pytest.mark.integration


def depth(amount_db: float, voice_gain: float) -> float:
    """Music level with the voice on minus with it off (tone bursts: 1 s on, 1 s off)."""
    g = ";".join([f"sine=f=300:d=8:r=16000,volume='if(lt(mod(t,2),1),{voice_gain},0)':eval=frame[v]",
                  "sine=f=60:d=8:r=16000,volume=1.6[m]", *duck_graph("m", "v", "o", amount_db)])
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-filter_complex", g, "-map", "[o]", "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    a = np.frombuffer(raw, np.float32)

    def db(t0: float, t1: float) -> float:
        x = a[int(t0 * 16000):int(t1 * 16000)]
        return 20 * np.log10(np.sqrt(float((x ** 2).mean())))
    return db(5.5, 5.9) - db(4.5, 4.9)


@pytest.mark.parametrize("amount", [6, 12, 20])
@pytest.mark.parametrize("voice_gain", [0.4, 0.8, 2.4])  # x the sine's 1/8: speech at about -29 / -23 / -13 dBFS
def test_duck_depth_is_what_was_asked(amount, voice_gain):
    assert abs(depth(amount, voice_gain) - amount) < 1.5
