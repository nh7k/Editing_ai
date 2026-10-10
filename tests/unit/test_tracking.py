"""Person tracking: association/smoothing logic, follow crop, spotlight and tracked text — checked on pixels."""

from __future__ import annotations

import numpy as np
import pytest

from cutmind.ffmpeg_utils import extract_frame, run_ffmpeg
from cutmind.framing import Frame, piecewise
from cutmind.plan import Canvas, ClipSegment, EditPlan, Effect, TextItem, TextStyle
from cutmind.renderer import build_ass, render
from cutmind.tracking import follow, models_available


@pytest.fixture(scope="module")
def moving_box(tmp_path_factory):
    """3 s, 1280x720: a white 100x100 box moving left → right (x = 100 + 326·t)."""
    out = tmp_path_factory.mktemp("trk") / "box.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=1280x720:d=3:r=30", "-f", "lavfi", "-i", "color=c=white:s=100x100:d=3:r=30",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-filter_complex", "[0:v][1:v]overlay=x='100+326*t':y=310[v]", "-map", "[v]", "-map", "2:a", "-t", "3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])
    return out


def box_points(dur: float = 3.0) -> list[list[float]]:
    return [[t, (150 + 326 * t) / 1280, 360 / 720, 100 / 1280, 100 / 720] for t in np.arange(0, dur + 0.01, 0.5)]


def white_x(frame: np.ndarray) -> float | None:
    ys, xs = np.where(frame.mean(axis=2) > 200)
    return float(xs.mean()) if len(xs) else None


def plan_for(effects: list[Effect], text: list[TextItem] | None = None) -> EditPlan:
    return EditPlan(canvas=Canvas(aspect_ratio="9:16", resolution=720), clips=[ClipSegment(source="b", **{"in": 0}, out=3, order=0)],
                    effects=effects, text=text or [])


def test_follow_crop_keeps_the_subject_centred(moving_box, tmp_path):
    plain = render(plan_for([]), {"b": moving_box}, tmp_path / "w0", tmp_path / "plain.mp4")
    fol = render(plan_for([Effect(type="follow", target=0, points=box_points())]), {"b": moving_box}, tmp_path / "w1",
                 tmp_path / "follow.mp4")
    w = 720
    for t in (0.3, 1.5, 2.7):
        x = white_x(extract_frame(fol, t))
        assert x is not None and abs(x - w / 2) < w * 0.12, (t, x)
    # without following, the centre crop loses the box at the start and the end
    assert white_x(extract_frame(plain, 0.3)) is None and white_x(extract_frame(plain, 2.7)) is None


def test_spotlight_darkens_away_from_the_subject(tmp_path):
    grey = tmp_path / "grey.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=0x808080:s=1280x720:d=2:r=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(grey)])
    pts = [[t, 0.25, 0.5, 0.1, 0.2] for t in (0.0, 1.0, 2.0)]  # subject on the left
    canvas = Canvas(aspect_ratio="16:9", resolution=720)
    seg = [ClipSegment(source="g", **{"in": 0}, out=2, order=0)]
    out = render(EditPlan(canvas=canvas, clips=seg, effects=[Effect(type="spotlight", target=0, points=pts)]),
                 {"g": grey}, tmp_path / "w", tmp_path / "spot.mp4")
    f = extract_frame(out, 1.0).astype(float).mean(axis=2)
    near = f[330:390, 290:350].mean()      # around (0.25·1280, 0.5·720)
    far = f[330:390, 1180:1260].mean()     # same height, far right
    assert near > 100 and far < near * 0.6, (near, far)


def test_tracked_text_follows_the_points(moving_box, tmp_path):
    track = [[0.0, 150.0, 300.0], [1.5, 360.0, 300.0], [3.0, 570.0, 300.0]]
    item = TextItem(kind="text", text="RIYA", start=0, end=3, track=track,
                    style=TextStyle(position="top", size=70, box_color="#FACC15", color="#111827"))
    ass = build_ass([item], 720, 1280)
    assert ass.count("\\move(") == 2 and "\\an2" in ass
    out = render(plan_for([], [item]), {"b": moving_box}, tmp_path / "w", tmp_path / "txt.mp4")
    for t, x_expected in ((0.2, 150 + 210 * 0.2 / 1.5), (2.8, 360 + 210 * 1.3 / 1.5)):
        f = extract_frame(out, t)
        ys, xs = np.where((f[:, :, 0] > 200) & (f[:, :, 1] > 160) & (f[:, :, 2] < 90))  # yellow label box
        assert len(xs) and abs(xs.mean() - x_expected) < 60 and ys.max() <= 330, (t, xs.mean() if len(xs) else None)


def test_follow_picks_one_person_and_ignores_a_jump_to_someone_else():
    a = (0.30, 0.5, 0.2, 0.5, 0.9)
    b = (0.85, 0.5, 0.15, 0.4, 0.9)   # another person far away
    frames = [[a, b], [(0.32, 0.5, 0.2, 0.5, 0.9), b], [b], [(0.36, 0.5, 0.2, 0.5, 0.9), b], []]
    tr = follow([0.0, 0.2, 0.4, 0.6, 0.8], frames, "person", "test")
    xs = [p[1] for p in tr.points]
    assert all(0.28 <= x <= 0.38 for x in xs), xs  # never jumps to the person at x=0.85
    assert tr.found == pytest.approx(3 / 5)


def test_frame_geometry_and_piecewise():
    fr = Frame(1920, 1080, 720, 1280, "follow", 1.0)
    sw, sh = fr.scaled
    assert sh == 1280 and sw == 2276
    assert fr.crop_origin(0.0, 0.5)[0] == 0 and fr.crop_origin(1.0, 0.5)[0] == sw - 720
    x, _y = fr.to_output(0.5, 0.5, (0.5, 0.5))
    assert abs(x - 360) < 1
    assert piecewise([(0, 5)]) == "5" and piecewise([(0, 0), (1, 10)]).startswith("if(lt(t")


@pytest.mark.skipif(not models_available()["person"], reason="YOLOX-nano model not downloaded")
def test_yolox_finds_no_person_in_an_empty_frame():
    from cutmind.tracking import detect_people

    assert detect_people(np.zeros((360, 640, 3), dtype=np.uint8)) == []
