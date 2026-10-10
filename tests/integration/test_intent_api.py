"""The "yaha screen white kar do nomal jasia tha" failure end to end through the API (docs/INTENT_FAILURE_REVIEW.md):
a timeline comment on a black-and-white moment gets choices (restore first, white flash among them) instead of a
dead end; tapping a choice makes a new version that really looks like the original there; undo gives the exact
previous version back; the same sentence in the chat no longer starts an automatic re-edit."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import extract_frame, run_ffmpeg
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration
BUG = "yaha screen white kar do nomal jasia tha"


def sat(f) -> float:  # noqa: ANN001
    f = f.astype(float)
    return float((f.max(axis=2) - f.min(axis=2)).mean())


@pytest.fixture(scope="module")
def env(tmp_path_factory, music_dir):
    d = tmp_path_factory.mktemp("intent")
    clip = d / "c.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=8", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    with TestClient(create_app(make_settings(d / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "intent"}).json()["id"]
        assert c.post(f"/projects/{pid}/clips", files=[("files", (clip.name, clip.read_bytes(), "video/mp4"))]).status_code == 201
        # the user's situation: black and white on 3-5.5 s
        r = c.post(f"/projects/{pid}/tools", json={"calls": [
            {"id": "grayscale", "time": {"mode": "between_times", "start": 3.0, "end": 5.5}}]})
        assert r.status_code == 202, r.text
        assert wait_job(c, r.json()["job_id"])["status"] == "done"
        yield c, pid


def plan_of(c, pid) -> EditPlan:  # noqa: ANN001
    return EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())


def test_the_comment_gets_choices_not_a_dead_end_and_the_restore_choice_restores(env, tmp_path):
    c, pid = env
    before = plan_of(c, pid)
    r = c.post(f"/projects/{pid}/edit", json={"prompt": BUG, "at": 4.3})
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "choose" and err["request_id"]
    ids = [x["id"] for x in err["choices"]]
    assert ids[0] == "restore_normal" and "flash" in ids, ids
    assert "rose ka sticker" not in err["message"]  # the old fixed list is gone
    # the user taps the first chip: a new version, the black and white is gone at 4.3 s, the rest stays
    run = c.post(f"/projects/{pid}/tools", json={"calls": err["choices"][0]["calls"], "prompt": BUG})
    assert run.status_code == 202, run.text
    job = wait_job(c, run.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert c.post("/tools/resolve/pick", json={"request_id": err["request_id"], "choice_id": ids[0]}).json()["ok"]
    out = c.get(f"/projects/{pid}/output")
    assert out.status_code == 200
    video = tmp_path / "restored.mp4"
    video.write_bytes(out.content)
    after = plan_of(c, pid)
    grey_left = [e for e in after.effects if e.type == "grade"]
    tl = after.timeline()
    at_marker = next(e for e in tl if e.start <= 4.3 < e.end)
    assert not any(e.target in (-1, at_marker.index) for e in grey_left), after.effects
    assert abs(after.total_duration() - before.total_duration()) < 1e-6
    assert sat(extract_frame(video, 4.3)) > 40  # colour is back on screen (testsrc2 is colourful; grey is ~0)
    # undo gives the exact previous version back
    assert c.post(f"/projects/{pid}/undo").status_code == 200
    assert plan_of(c, pid).to_json() == before.to_json()
    c.post(f"/projects/{pid}/redo")


def test_the_same_words_in_the_chat_do_not_start_an_automatic_re_edit(env):
    c, pid = env
    r = c.post(f"/projects/{pid}/edit", json={"prompt": BUG})
    assert r.status_code in (202, 422), r.text
    if r.status_code == 202:  # applied directly: it must be a tool job (not the director's auto edit)
        job = wait_job(c, r.json()["job_id"])
        assert (job.get("explain") or {}).get("tools"), job
    else:
        assert r.json()["error"]["code"] == "choose"


def test_a_clear_comment_is_applied_directly_and_said_back(env):
    c, pid = env
    r = c.post(f"/projects/{pid}/edit", json={"prompt": "is jagah white flash lagao", "at": 1.0})
    assert r.status_code == 202, r.text
    assert "flash" in r.json().get("did", "") or wait_job(c, r.json()["job_id"])["status"] == "done"
    assert wait_job(c, r.json()["job_id"])["status"] == "done"


def test_resolve_endpoint_reads_what_is_on_screen_from_the_project(env):
    c, pid = env
    plan = plan_of(c, pid)
    grey = next((e for e in plan.effects if e.type == "grade"), None)
    t = next(x for x in plan.timeline() if grey and x.index == grey.target).start + 0.2 if grey else 4.3
    r = c.post("/tools/resolve", json={"prompt": BUG, "project_id": pid, "context": {"marker_time": t}}).json()
    assert r["choices"] and r["decision"] in ("choose", "apply")


def test_yaha_in_the_chat_means_the_playhead(env):
    c, pid = env
    plan = plan_of(c, pid)
    grey = [e for e in plan.effects if e.type == "grade"]
    if not grey:  # put the black and white back (an earlier test restored it)
        r = c.post(f"/projects/{pid}/tools", json={"calls": [
            {"id": "grayscale", "time": {"mode": "between_times", "start": 3.0, "end": 5.5}}]})
        assert wait_job(c, r.json()["job_id"])["status"] == "done"
    r = c.post(f"/projects/{pid}/edit", json={"prompt": "yaha pehle jaisa kar do", "playhead": 4.3})
    if r.status_code == 422:
        assert r.json()["error"]["choices"][0]["id"] == "restore_normal", r.text
    else:
        assert r.status_code == 202 and "normal" in r.json().get("did", ""), r.text
        assert wait_job(c, r.json()["job_id"])["status"] == "done"
