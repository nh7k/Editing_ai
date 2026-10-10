"""Edit like a reference video, noise removal, focus on one person — real renders, real measurements."""

from __future__ import annotations

import time

import numpy as np
import pytest
import soundfile as sf
from conftest import make_settings
from fastapi.testclient import TestClient

from cutmind import segmentation
from cutmind.ffmpeg_utils import extract_frame, probe, run_ffmpeg
from cutmind.media_gen import make_song
from cutmind.plan import Canvas, ClipSegment, EditPlan
from cutmind.reference import analyze_reference
from cutmind.renderer import render

pytestmark = pytest.mark.integration


def _wait(client, job_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(1)
    raise AssertionError("timeout")


@pytest.fixture
def reference_video(tmp_path, media):
    """A 'finished edit': 9:16, 0.5 s shots cut on a 120 bpm beat, every 3rd shot black & white, one white flash."""
    song = make_song(tmp_path / "ref_song.m4a", 120, 8, busy=True)
    parts = []
    for k in range(16):
        out = tmp_path / f"p{k}.mp4"
        vf = "crop=ih*9/16:ih,scale=360:640" + (",hue=s=0" if k % 3 == 2 else "") + (",negate,hue=s=0,eq=brightness=0.9" if k == 7 else "")
        run_ffmpeg(["-ss", f"{(k * 0.7) % 10:.2f}", "-i", str(media["c"]), "-vf", vf + ",fps=30", "-frames:v", "15", "-an",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])  # exactly 0.5 s = one beat at 120 bpm
        parts.append(out)
    lst = tmp_path / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    joined = tmp_path / "joined.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    ref = tmp_path / "reference.mp4"
    run_ffmpeg(["-i", str(joined), "-i", str(song), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", str(ref)])
    return ref


def test_reference_is_measured(reference_video, tmp_path):
    r = analyze_reference(reference_video, tmp_path / "w")
    assert r.aspect == "9:16" and 7.0 < r.duration < 8.5
    assert 0.4 < r.shot_median < 0.65, r.cuts
    assert 0.2 < r.bw_share < 0.5
    assert r.beat_z >= 2, (r.on_beat, r.beat_z)  # cut on the beat (every 0.5 s at 120 bpm)


def test_edit_raw_footage_like_the_reference(tmp_path, media, music_dir, reference_video):
    from cutmind.api import create_app

    with TestClient(create_app(make_settings(tmp_path / "data", music_dir))) as client:
        pid = client.post("/projects", json={"name": "ref"}).json()["id"]
        for k in ("b", "c"):
            with open(media[k], "rb") as f:
                assert client.post(f"/projects/{pid}/clips", files={"files": (f"{k}.mp4", f, "video/mp4")}).status_code == 201
        with open(reference_video, "rb") as f:
            r = client.post(f"/projects/{pid}/reference", files={"file": ("their_edit.mp4", f, "video/mp4")})
        assert r.status_code == 201, r.text
        assert r.json()["recipe"]["song"] == "their_edit_sound.m4a"
        job = client.post(f"/projects/{pid}/edit", json={"prompt": "is reference video jaisa mera video edit karo"}).json()
        done = _wait(client, job["job_id"])
        assert done["status"] == "done", done.get("error")
        plan = client.get(f"/projects/{pid}/plan").json()
        assert plan["canvas"]["aspect_ratio"] == "9:16"
        assert plan["audio"]["music"] == "their_edit_sound.m4a"
        shots = [(c["out"] - c["in"]) / c["speed"] for c in plan["clips"]]
        assert np.median(shots) < 1.0                                    # fast like the reference
        assert any(e["type"] in ("film_bw", "mono") for e in plan["effects"])  # some black & white shots
        assert any(d["skill"] == "reference_style" for d in plan["decisions"])
        assert client.get(f"/projects/{pid}/reference").json()["summary"]
        assert client.delete(f"/projects/{pid}/reference").json()["ok"]


def test_noise_removal_lifts_the_voice_above_the_noise(tmp_path, media):
    noisy = tmp_path / "noisy.mp4"
    run_ffmpeg(["-i", str(media["a"]), "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.06:d=15", "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                "-c:a", "aac", str(noisy)])
    snr = {}
    for clean in (False, True):
        plan = EditPlan(canvas=Canvas(aspect_ratio="16:9", resolution=360),
                        clips=[ClipSegment(source="a", **{"in": 0}, out=12, order=0)], audio={"voice_cleanup": clean})
        out = render(plan, {"a": noisy}, tmp_path / f"w{clean}", tmp_path / f"o{clean}.mp4")
        wav = tmp_path / f"o{clean}.wav"
        run_ffmpeg(["-i", str(out), "-ac", "1", "-ar", "16000", str(wav)])
        x, sr = sf.read(str(wav))
        gap = np.concatenate([x[int(2.3 * sr):int(4.7 * sr)], x[int(7.3 * sr):int(9.2 * sr)]])  # nobody speaks here
        speech = x[int(0.2 * sr):int(1.9 * sr)]
        snr[clean] = 20 * np.log10(np.sqrt((speech ** 2).mean()) / (np.sqrt((gap ** 2).mean()) + 1e-9))
    assert snr[True] > snr[False] + 8, snr


def test_focus_keeps_the_person_sharp_and_blurs_the_rest(tmp_path, monkeypatch):
    src = tmp_path / "grid.mp4"  # detailed picture everywhere, so sharpness can be measured on both halves
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:d=3:r=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)])
    seg = [ClipSegment(source="c", **{"in": 0}, out=3, order=0)]
    canvas = Canvas(aspect_ratio="16:9", resolution=360)

    def left_person(video, windows, out, color=None, only_one=False):  # "the person" = left half of the frame
        info = probe(video)
        run_ffmpeg(["-f", "lavfi", "-i", f"color=black:s={info.width}x{info.height}:r={info.fps}:d={info.duration}",
                    "-vf", f"drawbox=x=0:y=0:w={info.width // 2}:h={info.height}:color=white:t=fill",
                    "-c:v", "ffv1", "-pix_fmt", "gray", str(out)])
        return out

    monkeypatch.setattr(segmentation, "available", lambda: True)
    monkeypatch.setattr(segmentation, "mask_video", left_person)
    plain = render(EditPlan(canvas=canvas, clips=seg), {"c": src}, tmp_path / "p", tmp_path / "p.mp4")
    foc = render(EditPlan(canvas=canvas, clips=seg, focus={"mode": "blur", "color": "#3B82F6"}), {"c": src},
                 tmp_path / "f", tmp_path / "f.mp4")
    import cv2

    pp, ff = extract_frame(plain, 1.5), extract_frame(foc, 1.5)
    w = pp.shape[1]

    def sharp(img, cols):
        return float(cv2.Laplacian(cv2.cvtColor(img[:, cols], cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())

    left, right = slice(10, w // 2 - 20), slice(w // 2 + 20, w - 10)
    assert sharp(ff, left) > 0.8 * sharp(pp, left)     # the person keeps its detail
    assert sharp(ff, right) < 0.4 * sharp(pp, right)   # the rest is blurred
