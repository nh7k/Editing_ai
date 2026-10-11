"""A real chat failure (2026-10-11): after a director edit with the Midnight Drift look and black and white,
"purple video ko normal kar do" went to the director, which read "purple" as the Violet Authority look and changed
nothing. Now the chat sends "normal karo" to the restore skill, which takes off the whole look (grade numbers, the
colour wash, graphic tracks, the style) — checked on the rendered video."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import extract_frame, run_ffmpeg
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration


def sat(f) -> float:  # noqa: ANN001
    f = f.astype(float)
    return float((f.max(axis=2) - f.min(axis=2)).mean())


def test_purple_video_ko_normal_kar_do_after_a_styled_director_edit(tmp_path, music_dir):
    clip = tmp_path / "c.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=6", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    with TestClient(create_app(make_settings(tmp_path / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "style"}).json()["id"]
        assert c.post(f"/projects/{pid}/clips", files=[("files", (clip.name, clip.read_bytes(), "video/mp4"))]).status_code == 201
        r = c.post(f"/projects/{pid}/edit", json={"prompt": "black and white edit", "style": "midnight_drift"})
        assert r.status_code == 202, r.text
        assert wait_job(c, r.json()["job_id"])["status"] == "done"
        styled = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
        assert styled.style == "midnight_drift" and styled.overlays

        r = c.post(f"/projects/{pid}/edit", json={"prompt": "purple video ko normal kar do"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body.get("decision") == "apply" and "normal" in body["did"], body  # the skill, not the director
        job = wait_job(c, body["job_id"])
        assert job["status"] == "done", job.get("error")
        plan = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
        assert plan.style is None and not plan.overlays
        col = plan.color
        assert (col.preset, col.contrast, col.saturation, col.warmth) == ("none", 1.0, 1.0, 0.0)
        assert abs(plan.total_duration() - styled.total_duration()) < 1e-6
        video = tmp_path / "normal.mp4"
        video.write_bytes(c.get(f"/projects/{pid}/output").content)
        assert sat(extract_frame(video, styled.total_duration() / 2)) > 40  # colour is back (grey / tinted was low)
        # undo brings the styled version back exactly
        assert c.post(f"/projects/{pid}/undo").status_code == 200
        assert EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json()).to_json() == styled.to_json()


def test_normal_only_in_one_part_takes_the_whole_video_grade_off_there(tmp_path):
    """Restore on a window of a black-and-white edit: the global saturation 0 moves to the OTHER shots, so the
    window really gets colour back (before, only the preset name moved and the window stayed grey)."""
    from pathlib import Path

    from cutmind.tools.engine import ToolCtx, first_plan, run

    clip = tmp_path / "c.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(clip)])
    plan = first_plan(["c1"], {"c1": 6.0})
    data = plan.to_json()
    data["color"] = {**data["color"], "preset": "bw", "saturation": 0.0, "contrast": 1.12}
    plan = EditPlan.model_validate(data)
    ctx = ToolCtx(sources={"c1": Path(clip)}, gen_dir=tmp_path, clip_ids=["c1"])
    new, _ = run(plan, [{"id": "restore_normal", "params": {},
                         "time": {"mode": "between_times", "start": 2.0, "end": 4.0}}], ctx)
    assert new.color.saturation == 1.0 and new.color.preset == "none"
    tl = new.timeline()
    mid = next(e for e in tl if e.start <= 3.0 < e.end)
    grades = {e.target: e.params for e in new.effects if e.type == "grade"}
    assert mid.index not in grades
    others = [e.index for e in tl if e.index != mid.index]
    assert others and all(grades[i].get("saturation") == 0.0 for i in others)
