"""Non-destructive chat edits: a follow-up message changes the CURRENT edit — it keeps what earlier messages and the
user's hand-made changes did, and stays the same length — while "shuru se" starts again. Real renders (FFmpeg)."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import extract_frame, decode_check, probe
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def env(tmp_path_factory, media, music_dir):
    data = tmp_path_factory.mktemp("nondestructive")
    with TestClient(create_app(make_settings(data, music_dir))) as c:
        pid = c.post("/projects", json={"name": "nd"}).json()["id"]
        files = [("files", (p.name, p.read_bytes(), "video/mp4")) for p in (media["a"], media["c"])]
        assert c.post(f"/projects/{pid}/clips", files=files).status_code == 201
        yield c, pid, data


def edit(c, pid, prompt):
    r = c.post(f"/projects/{pid}/edit", json={"prompt": prompt})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    return job, EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())


def test_follow_ups_keep_earlier_changes_and_hand_made_effects(env):
    c, pid, data = env
    _job, p1 = edit(c, pid, "8 second ka edit, warm color, music lagao")
    d1 = p1.total_duration()
    # a hand-made change in the editor (Effects panel "Apply now")
    r = c.post(f"/projects/{pid}/manual", json={"ops": [{"op": "add_effect", "type": "vignette"}]})
    assert r.status_code == 202, r.text
    assert wait_job(c, r.json()["job_id"])["status"] == "done"
    # follow-ups: a long one and a "make it a reel" one — both used to start a NEW edit and drop everything
    job, p2 = edit(c, pid, "2 sec me hi ruk gayi video kyu, aur thoda bright bhi kar do please yaar abhi ke abhi jaldi")
    assert p2.color.preset == "warm" and p2.audio.music, "earlier changes were lost"
    assert any(e.type == "vignette" for e in p2.effects), "the hand-made effect was lost"
    fails = [ck["name"] + ": " + str(ck.get("detail", "")) for ck in (job.get("review") or {}).get("checks", [])
             if not ck.get("passed", True)]
    assert not any("vignette" in f for f in fails), fails  # asked by hand: not "added without being asked"
    assert abs(p2.total_duration() - d1) <= max(0.3, 0.02 * d1), (d1, p2.total_duration())
    job, p3 = edit(c, pid, "make it a 9:16 reel")
    assert p3.canvas.aspect_ratio == "9:16" and p3.color.preset == "warm" and p3.audio.music
    assert any(e.type == "vignette" for e in p3.effects)
    out = data / "projects" / pid / "output" / f"{job['id']}.mp4"
    ok, err = decode_check(out)
    assert ok, err
    info = probe(out)
    assert info.has_audio and abs(info.duration - p3.total_duration()) < 0.3


def test_starting_over_forgets_the_old_edit(env):
    c, pid, _data = env
    _job, p = edit(c, pid, "shuru se bana do, black and white")
    assert p.color.preset == "bw"
    assert not any(e.type == "vignette" for e in p.effects)  # the old hand-made change belonged to the old edit


def test_versions_undo_redo_restore_and_explain(env):
    c, pid, data = env
    j1, p1 = edit(c, pid, "naya edit: 8 second ka, warm color")
    j2, p2 = edit(c, pid, "ab black and white kar do")
    # explain-back: what changed, what stayed, the length (no length was asked: no warning)
    ex = j2["explain"]
    # a single clear change after a director edit is made by the skills (Phase A rule): black and white may be a
    # colour preset (director) or a black-and-white grade (skill) — the answer must say it either way
    bw_said = lambda lines: any(x.startswith("colour") or "black and white" in x for x in lines)  # noqa: E731
    assert bw_said(ex["changed"]) and ex["warnings"] == [], ex
    assert abs(ex["duration_after"] - ex["duration_before"]) < 0.3 and "Changed:" in ex["summary"]
    vs = c.get(f"/projects/{pid}/versions").json()["versions"]
    assert vs[-1]["job_id"] == j2["id"] and vs[-1]["current"] and vs[-2]["job_id"] == j1["id"]
    # undo: back to the warm version, without rendering (the output file is copied)
    u = c.post(f"/projects/{pid}/undo").json()
    plan = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    assert plan.color.preset == "warm"
    out = data / "projects" / pid / "output" / f"{u['job_id']}.mp4"
    assert out.exists() and decode_check(out)[0]
    # redo: black and white again
    rd = c.post(f"/projects/{pid}/redo").json()
    # black and white again — measured on the redone video, not on how the plan spells it
    redone = data / "projects" / pid / "output" / f"{rd['job_id']}.mp4"
    f = extract_frame(redone, 1.0).astype(float)
    assert float((f.max(axis=2) - f.min(axis=2)).mean()) < 8
    # restore any version by id, and a follow-up continues from the restored edit
    c.post(f"/projects/{pid}/versions/{j1['id']}/restore")
    _j, p = edit(c, pid, "thoda bright karo")
    assert p.color.preset == "warm" or p.color.brightness > 0
    cmp = c.get(f"/projects/{pid}/versions/compare", params={"a": j1["id"], "b": j2["id"]}).json()
    assert bw_said(cmp["changed"]), cmp
    assert c.post(f"/projects/{pid}/versions/job_nope/restore").status_code == 400


def test_output_url_serves_exactly_the_asked_version(env):
    """A running / unknown job id must not get "the latest" video: the browser cached that old file under the new
    job's URL and mixed it with the new file's bytes, so the video stopped halfway after every effect."""
    c, pid, _data = env
    vs = c.get(f"/projects/{pid}/versions").json()["versions"]
    assert len(vs) >= 2
    old, new = vs[0]["job_id"], vs[-1]["job_id"]
    a, b = c.get(f"/projects/{pid}/output", params={"v": old}), c.get(f"/projects/{pid}/output", params={"v": new})
    assert a.status_code == b.status_code == 200 and a.content != b.content
    assert "immutable" in a.headers["cache-control"]
    assert c.get(f"/projects/{pid}/output", params={"v": "job_doesnotexist"}).status_code == 404
    assert c.get(f"/projects/{pid}/output").headers["cache-control"] == "no-cache"
    assert c.get(f"/projects/{pid}").json()["output_job_id"]
