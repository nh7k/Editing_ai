"""A real chat failure (2026-10-11): after a director reel and two skill edits (captions, "sab effect hata do"), a
timeline comment "yaha pe screen black and white ke effect daal do" went through the old comment reader to the
director, whose "from memory" merge re-made the whole edit (cut 1→3 shots, a colour look, the violet look, gradient
tracks, 7 effects). Now: the comment is the grayscale skill at that moment only; skill edits survive a later director
edit (replayed like hand-made changes); a restore also clears what it took off from the remembered edit."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import run_ffmpeg
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def env(tmp_path_factory, music_dir):
    d = tmp_path_factory.mktemp("replay")
    clip = d / "c.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=10", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=10", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    with TestClient(create_app(make_settings(d / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "replay"}).json()["id"]
        assert c.post(f"/projects/{pid}/clips", files=[("files", (clip.name, clip.read_bytes(), "video/mp4"))]).status_code == 201
        yield c, pid


def edit(c, pid, prompt, **extra):  # noqa: ANN001
    r = c.post(f"/projects/{pid}/edit", json={"prompt": prompt, **extra})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    return r.json(), job, EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())


def test_a_comment_effect_changes_only_that_moment(env):
    c, pid = env
    _, _, base = edit(c, pid, "violet authority look wala reel bana do", style="violet_authority")
    assert base.style == "violet_authority"
    body, job, p = edit(c, pid, "yaha pe screen black and white ke effect daal do", at=5.0)
    assert body.get("decision") == "apply", body  # the grayscale skill, not a director re-edit
    assert p.style == base.style and len(p.overlays) == len(base.overlays)  # the look is untouched
    assert abs(p.total_duration() - base.total_duration()) < 0.05
    assert {e.type for e in p.effects} - {e.type for e in base.effects} <= {"grade"}  # nothing else was added


def test_skill_edits_survive_a_later_director_edit_and_restore_clears_memory(env):
    c, pid = env
    body, _job, p = edit(c, pid, "captions laga do")
    assert body.get("decision") == "apply" and any(t.kind == "caption" for t in p.text), body
    # a director message (a look): the captions made by the skill are kept (replayed), not lost
    _, job, p2 = edit(c, pid, "midnight drift look lagao")
    assert p2.style == "midnight_drift"
    assert any(t.kind == "caption" for t in p2.text), [t.kind for t in p2.text]
    # "everything normal", then another director message: the old look does not come back from memory
    edit(c, pid, "sab effect aur gradient hata do normal kar do")
    _, _job, p3 = edit(c, pid, "3 second ka title 'GOA' daalo shuru me")
    assert p3.style is None and not p3.overlays, (p3.style, [o.label for o in p3.overlays])
