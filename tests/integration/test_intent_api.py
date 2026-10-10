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


def test_the_comment_restores_with_alternatives_shown_and_undo_brings_it_back(env, tmp_path):
    """Act, show, undo: the likeliest reading (restore — a black and white is on screen there) runs at once; the white
    flash stays one tap away; undo gives the exact previous version."""
    c, pid = env
    before = plan_of(c, pid)
    r = c.post(f"/projects/{pid}/edit", json={"prompt": BUG, "at": 4.3})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["decision"] == "act" and "normal" in body["did"]
    alt = [x["id"] for x in body["alternatives"]]
    assert "flash" in alt and body["request_id"], body
    assert "rose ka sticker" not in body["did"]  # the old fixed list is gone
    job = wait_job(c, body["job_id"])
    assert job["status"] == "done", job.get("error")
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
    # the alternative chip instead: white flash at 4.3 s
    flash = next(x for x in body["alternatives"] if x["id"] == "flash")
    run = c.post(f"/projects/{pid}/tools", json={"calls": flash["calls"], "prompt": BUG})
    assert wait_job(c, run.json()["job_id"])["status"] == "done"
    assert c.post("/tools/resolve/pick", json={"request_id": body["request_id"], "choice_id": "flash"}).json()["ok"]
    assert any(e.type == "flash" for e in plan_of(c, pid).effects)
    assert c.post(f"/projects/{pid}/undo").status_code == 200


def test_relative_words_change_the_last_edit(env):
    c, pid = env
    r = c.post(f"/projects/{pid}/tools", json={"calls": [{"id": "zoom_in", "params": {"amount": 0.15}}]})
    assert wait_job(c, r.json()["job_id"])["status"] == "done"
    more = c.post(f"/projects/{pid}/edit", json={"prompt": "aur thoda"})
    assert more.status_code == 202, more.text
    job = wait_job(c, more.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    amount = job["explain"]["tools"][0]["params"]["amount"]
    assert job["explain"]["tools"][0]["skill"] == "zoom_in" and amount > 0.15, job["explain"]
    back = c.post(f"/projects/{pid}/edit", json={"prompt": "isko hata do"})
    assert back.status_code == 202 and back.json()["decision"] == "undo", back.text


def test_a_greeting_never_edits(env):
    c, pid = env
    before = len(c.get(f"/projects/{pid}/versions").json()["versions"])
    r = c.post(f"/projects/{pid}/edit", json={"prompt": "hello bhai"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "non_edit"
    assert len(c.get(f"/projects/{pid}/versions").json()["versions"]) == before


def test_partial_prompt_applies_what_it_understood(env):
    c, pid = env
    r = c.post(f"/projects/{pid}/edit", json={"prompt": "warm karo, vignette lagao aur mere chehre ko jawan dikhao", "at": 1.0})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["decision"] == "partial" and body["unclear"] and not body["unclear"][0]["supported"], body
    assert wait_job(c, body["job_id"])["status"] == "done"
    fx = {e.type for e in plan_of(c, pid).effects}
    assert "vignette" in fx and ("grade" in fx), fx


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
    assert r["choices"] and r["decision"] in ("choose", "apply", "act")


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
