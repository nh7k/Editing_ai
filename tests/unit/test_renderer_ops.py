"""Every extra FFmpeg operation, rendered for real and verified on the output pixels / audio."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from cutmind.ffmpeg_utils import extract_frame, measure_loudness, probe, run_ffmpeg
from cutmind.plan import EditPlan
from cutmind.renderer import extra_path, render


@pytest.fixture(scope="module")
def src(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("ops")
    halves = d / "halves.mp4"  # left half red, right half blue, + a tone
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=320x360:d=4", "-f", "lavfi", "-i", "color=c=blue:s=320x360:d=4",
                "-f", "lavfi", "-i", "sine=f=330:d=4", "-filter_complex", "[0:v][1:v]hstack[v]", "-map", "[v]", "-map", "2:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(halves)])
    ramp = d / "ramp.mp4"  # gets brighter over time
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=4,format=gray,geq=lum='T*55':cb=128:cr=128",
                "-f", "lavfi", "-i", "sine=f=500:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(ramp)])
    detail = d / "detail.mp4"  # high-frequency test pattern
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(detail)])
    return {"halves": halves, "ramp": ramp, "detail": detail}


def go(tmp: Path, source: Path, name: str, **plan_parts) -> Path:
    base = {"canvas": {"aspect_ratio": "1:1", "resolution": 360},
            "clips": [{"source": "s", "in": 0, "out": 3.5, "order": 0}]}
    for k, v in plan_parts.items():
        base[k] = {**base.get(k, {}), **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    plan = EditPlan.model_validate(base)
    return render(plan, {"s": source}, tmp / f"w_{name}", tmp / f"{name}.mp4")


def mean_rgb(frame: np.ndarray, rows: slice = slice(None), cols: slice = slice(None)) -> np.ndarray:
    return frame[rows, cols].reshape(-1, 3).mean(axis=0)


def sharpness(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())


def test_rotate_90_moves_left_to_top(src, tmp_path):
    f = extract_frame(go(tmp_path, src["halves"], "rot", canvas={"rotate": 90}), 1.0)
    top, bottom = mean_rgb(f, slice(0, 120)), mean_rgb(f, slice(240, 360))
    assert top[0] > 150 and top[2] < 80 and bottom[2] > 150  # clockwise: left (red) is now on top


def test_flip_horizontal_swaps_sides(src, tmp_path):
    f = extract_frame(go(tmp_path, src["halves"], "flip", canvas={"flip": "h"}), 1.0)
    left, right = mean_rgb(f, cols=slice(0, 100)), mean_rgb(f, cols=slice(260, 360))
    assert left[2] > 150 and right[0] > 150  # blue now left, red right


def test_reverse_plays_backwards(src, tmp_path):
    out = go(tmp_path, src["ramp"], "rev", canvas={"aspect_ratio": "16:9"},
             clips=[{"source": "s", "in": 0, "out": 3.5, "order": 0, "reverse": True}])
    first, last = extract_frame(out, 0.1).mean(), extract_frame(out, 3.3).mean()
    assert first > last + 60  # bright → dark
    assert probe(out).has_audio


def test_reverse_length_is_limited():
    with pytest.raises(ValueError, match="reversed segments"):
        EditPlan.model_validate({"clips": [{"source": "s", "in": 0, "out": 20, "order": 0, "reverse": True}]})


def test_sepia_and_gamma(src, tmp_path):
    f = extract_frame(go(tmp_path, src["detail"], "sepia", color={"preset": "sepia"}), 1.0)
    r, g, b = mean_rgb(f)
    assert r > g > b and r - b > 25
    neutral = extract_frame(go(tmp_path, src["detail"], "neutral"), 1.0).mean()
    bright = extract_frame(go(tmp_path, src["detail"], "gamma", color={"gamma": 1.8}), 1.0).mean()
    assert bright > neutral + 10


def test_vignette_blur_sharpen(src, tmp_path):
    neutral = extract_frame(go(tmp_path, src["detail"], "n2"), 1.0)
    vig = extract_frame(go(tmp_path, src["detail"], "vig", effects=[{"type": "vignette", "target": -1}]), 1.0)
    corner = slice(0, 50)
    assert mean_rgb(vig, corner, corner).mean() < mean_rgb(neutral, corner, corner).mean() - 15
    blur = extract_frame(go(tmp_path, src["detail"], "blur", effects=[{"type": "blur", "target": -1}]), 1.0)
    sharp = extract_frame(go(tmp_path, src["detail"], "sharp", effects=[{"type": "sharpen", "target": -1}]), 1.0)
    assert sharpness(blur) < 0.5 * sharpness(neutral) < sharpness(sharp)


def test_mute_and_audio_fades(src, tmp_path):
    muted = go(tmp_path, src["detail"], "mute", audio={"mute": True})
    assert probe(muted).has_audio
    assert measure_loudness(muted).get("max_volume", -99) < -60
    faded = go(tmp_path, src["detail"], "afade", audio={"fade_in": 1.0, "fade_out": 1.0})
    head = tmp_path / "head.wav"
    mid = tmp_path / "mid.wav"
    run_ffmpeg(["-i", str(faded), "-t", "0.15", str(head)])
    run_ffmpeg(["-ss", "1.5", "-i", str(faded), "-t", "0.5", str(mid)])
    assert measure_loudness(head)["max_volume"] < measure_loudness(mid)["max_volume"] - 15


def test_watermark_in_corner(src, tmp_path):
    plain = extract_frame(go(tmp_path, src["detail"], "plain"), 1.0)
    wm = go(tmp_path, src["detail"], "wm", text=[{"kind": "watermark", "text": "@cutmind", "start": 0, "end": 3.5,
                                                  "style": {"position": "top_right", "size": 40, "box_color": None}}])
    f = extract_frame(wm, 1.0)
    corner = (slice(0, 60), slice(200, 360))
    changed = (np.abs(f[corner].astype(int) - plain[corner].astype(int)).max(axis=2) > 30).mean()
    assert changed > 0.03


def test_gif_and_mp3_extras(src, tmp_path):
    out = go(tmp_path, src["detail"], "extras", export={"extras": ["gif", "mp3"]})
    gif, mp3 = probe(extra_path(out, "gif")), probe(extra_path(out, "mp3"))
    assert gif.video_codec == "gif" and gif.width == 270 or gif.width == 480
    assert mp3.audio_codec == "mp3" and abs(mp3.duration - 3.5) < 0.2


def test_crossfade_right_after_a_hard_cut(tmp_path, media):
    """A travel edit failed: cut, cut, then a crossfade → 'timebase do not match' in xfade."""
    from cutmind.plan import Canvas, ClipSegment, EditPlan, Transition
    from cutmind.renderer import render

    segs = [ClipSegment(source="c", **{"in": float(k * 2)}, out=float(k * 2 + 1.5), order=k) for k in range(4)]
    segs[3] = ClipSegment(source="c", **{"in": 6.0}, out=7.0, order=3, speed=0.5)  # a slowed last shot, as in the bug
    plan = EditPlan(canvas=Canvas(aspect_ratio="16:9", resolution=360), clips=segs,
                    transitions=[Transition(type="crossfade", after=2, duration=0.4)])
    out = render(plan, {"c": media["c"]}, tmp_path / "w", tmp_path / "o.mp4")
    from cutmind.ffmpeg_utils import probe

    assert abs(probe(out).duration - plan.total_duration()) < 0.2
