"""Failure handling: every bad input must produce a clear error, never a crash or a hang."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.agents.base import AgentContext, ClipRef
from cutmind.agents.cutter import CutterAgent
from cutmind.agents.director import DirectorAgent
from cutmind.api import create_app
from cutmind.db import Database
from cutmind.ffmpeg_utils import probe
from cutmind.media_gen import make_corrupt_file

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path, music_dir):
    settings = make_settings(tmp_path / "data", music_dir, max_upload_mb=1)
    with TestClient(create_app(settings)) as c:
        c.app_settings = settings  # type: ignore[attr-defined]
        yield c


def new_project(client) -> str:
    r = client.post("/projects", json={"name": "fail tests"})
    assert r.status_code == 201
    return r.json()["id"]


def err(r) -> dict:
    body = r.json()
    assert set(body) == {"error"} and {"code", "message"} <= set(body["error"]), body
    return body["error"]


def small_clip(media, tmp_path):
    """A <1 MB copy of clip C so uploads fit the 1 MB test limit."""
    from cutmind.ffmpeg_utils import run_ffmpeg

    out = tmp_path / "small.mp4"
    run_ffmpeg(["-i", str(media["a"]), "-t", "6", "-vf", "scale=320:-2", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "32", "-c:a", "aac", "-b:a", "48k", str(out)])
    assert out.stat().st_size < 1024 * 1024
    return out


@pytest.mark.parametrize("prompt,code", [("", "bad_prompt"), ("   ", "bad_prompt"), ("x", "bad_prompt"),
                                         ("y" * 1500, "bad_prompt"), ("z" * 2500, "validation_error")])
def test_bad_prompts(client, media, tmp_path, prompt, code):
    pid = new_project(client)
    client.post(f"/projects/{pid}/clips", files=[("files", ("s.mp4", small_clip(media, tmp_path).read_bytes(), "video/mp4"))])
    r = client.post(f"/projects/{pid}/edit", json={"prompt": prompt})
    assert r.status_code == 422
    e = err(r)
    assert e["code"] == code and e["message"]


def test_edit_with_empty_clip_list(client):
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/edit", json={"prompt": "trim to 15s"})
    assert r.status_code == 400
    assert err(r)["code"] == "no_clips" and "Upload at least one" in err(r)["message"]


def test_corrupt_file_rejected(client, tmp_path):
    pid = new_project(client)
    bad = make_corrupt_file(tmp_path / "broken.mp4")
    r = client.post(f"/projects/{pid}/clips", files=[("files", ("broken.mp4", bad.read_bytes(), "video/mp4"))])
    assert r.status_code == 400 and err(r)["code"] == "corrupt_file"
    assert client.get(f"/projects/{pid}").json()["clips"] == []
    assert not any((client.app_settings.projects_dir / pid / "clips").glob("src_*"))  # nothing left behind


def test_wrong_type_rejected(client):
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/clips", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 415 and err(r)["code"] == "unsupported_file_type"


def test_empty_file_rejected(client):
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/clips", files=[("files", ("empty.mp4", b"", "video/mp4"))])
    assert r.status_code == 400 and err(r)["code"] == "empty_file"


def test_oversized_upload_rejected(client, media):
    pid = new_project(client)
    big = media["a"].read_bytes()  # ~1-2 MB > 1 MB limit set in the fixture
    assert len(big) > 1024 * 1024
    r = client.post(f"/projects/{pid}/clips", files=[("files", ("big.mp4", big, "video/mp4"))])
    assert r.status_code == 413 and err(r)["code"] == "file_too_large"
    assert not any((client.app_settings.projects_dir / pid / "clips").glob("src_*"))


def test_not_found_errors(client):
    assert err(client.get("/projects/nope"))["code"] == "project_not_found"
    assert err(client.get("/jobs/nope"))["code"] == "job_not_found"
    assert err(client.post("/jobs/nope/feedback", json={"rating": "up"}))["code"] == "job_not_found"
    pid = new_project(client)
    assert err(client.get(f"/projects/{pid}/output"))["code"] == "no_output"
    assert err(client.get(f"/projects/{pid}/plan"))["code"] == "no_plan"
    assert err(client.post("/projects", json={"name": ""}))["code"] == "validation_error"
    assert err(client.post("/jobs/x/feedback", json={"rating": "meh"}))["code"] == "validation_error"


def test_nonsense_prompt_is_not_turned_into_a_default_edit(client, media, tmp_path):
    """The user said: whatever I type, either do THAT or tell me — never a silent "default clean edit"."""
    pid = new_project(client)
    client.post(f"/projects/{pid}/clips", files=[("files", ("s.mp4", small_clip(media, tmp_path).read_bytes(), "video/mp4"))])
    r = client.post(f"/projects/{pid}/edit", json={"prompt": "asdf qwerty zxcv"})
    assert r.status_code == 422 and err(r)["code"] == "not_understood" and "samajh nahi aaya" in err(r)["message"]


def test_a_job_that_understood_nothing_is_penalised(client, media, tmp_path):
    """If a job still gets nothing (e.g. a taught phrase that went stale), the reviewer marks it — no silent 100 %."""
    pid = new_project(client)
    client.post(f"/projects/{pid}/clips", files=[("files", ("s.mp4", small_clip(media, tmp_path).read_bytes(), "video/mp4"))])
    job_id = client.app.state.jobs.submit(pid, "asdf qwerty zxcv", {})
    job = wait_job(client, job_id)
    assert job["status"] == "done"
    assert any(lg["level"] == "warn" and "No specific instruction" in lg["msg"] for lg in job["logs"])
    failed = {c["name"] for c in job["review"]["checks"] if not c["passed"]}
    assert "intent_understood" in failed  # the director is penalised for not understanding
    assert job["review"]["agent_scores"]["director"] < 100
    # feedback on a finished job works; unknown agent is rejected clearly
    assert err(client.post(f"/jobs/{job['id']}/feedback", json={"rating": "up", "agent": "bob"}))["code"] == "unknown_agent"


def test_missing_local_model_falls_back_gracefully(tmp_path, music_dir, media):
    """PLANNER_MODE=local but the model files are missing: every LLM call fails → rule fallback, job succeeds."""
    settings = make_settings(tmp_path / "data", music_dir, planner_mode="local",
                             llm_model_dir=str(tmp_path / "missing-model"))
    with TestClient(create_app(settings)) as c:
        pid = c.post("/projects", json={"name": "no model"}).json()["id"]
        c.post(f"/projects/{pid}/clips", files=[("files", ("s.mp4", small_clip(media, tmp_path).read_bytes(), "video/mp4"))])
        job = wait_job(c, c.post(f"/projects/{pid}/edit", json={"prompt": "trim to 4 seconds, warm color"}).json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert job["modes"]["director"] == "llm_fallback"  # LLM_AGENTS=director (default)
        assert {m for a, m in job["modes"].items() if a != "director"} == {"rules"}
        assert any("LLM" in lg["msg"] and lg["level"] == "warn" for lg in job["logs"])
        assert c.get("/health").json()["llm"]["available"] is False


def test_job_failure_is_reported_not_raised(client, media, tmp_path):
    """If a source file disappears after upload the job fails with a readable message."""
    pid = new_project(client)
    clip = client.post(f"/projects/{pid}/clips",
                       files=[("files", ("s.mp4", small_clip(media, tmp_path).read_bytes(), "video/mp4"))]).json()["clips"][0]
    path = client.app.state.db.get_clip(clip["id"])["path"]
    import os

    os.remove(path)
    job = wait_job(client, client.post(f"/projects/{pid}/edit", json={"prompt": "trim to 5s"}).json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"] and ("analysis failed" in job["error"].lower() or "could not" in job["error"].lower())
    assert err(client.post(f"/jobs/{job['id']}/feedback", json={"rating": "up"}))["code"] == "job_not_finished"


# ---- retry loop with a deliberately bad agent (real render + review) ---------------------------------
class SabotagedCutter(CutterAgent):
    """Ignores the target length until it gets feedback from the Reviewer (not the Director's own re-cut)."""

    def run(self, ctx, feedback=None, attempt=1):
        res = super().run(ctx, feedback, attempt)
        from_reviewer = any(f.check == "duration" and "expected" in f.detail for f in feedback or [])
        if not from_reviewer and ctx.intent.target_duration:
            ctx.intent = ctx.intent.model_copy(update={"target_duration": None})
            res = super().run(ctx, None, attempt)
            ctx.intent = ctx.intent.model_copy(update={"target_duration": 6.0})
        return res


def test_director_retries_only_the_failing_agent(tmp_path, music_dir, media):
    settings = make_settings(tmp_path / "data", music_dir)
    db = Database(tmp_path / "db.sqlite3")
    clips = [ClipRef("A", media["a"], "a.mp4", 0), ClipRef("C", media["c"], "c.mp4", 1)]
    ctx = AgentContext(job_id="retry_job", prompt="trim to 6 seconds, warm color", clips=clips, settings=settings, db=db,
                       work_dir=tmp_path / "proj" / "work" / "retry_job")
    director = DirectorAgent()
    director.team["cutter"] = SabotagedCutter()
    director.team["cutter"].name = "cutter"
    result = director.run_job(ctx, tmp_path / "out.mp4")
    first, last = result.history[0], result.history[-1]
    assert first["agent_scores"]["cutter"] < settings.score_threshold
    assert last["agent_scores"]["cutter"] == 100.0
    # initial run + Director's own length re-cut + 1 Reviewer-driven retry; colour/audio are never re-run
    assert result.attempts["cutter"] == 3 and result.attempts["color"] == 1 and result.attempts["audio"] == 1
    assert result.attempts["effects"] == 3  # dependent of the cutter (captions/transitions timing)
    assert len(result.history) == 2
    assert abs(probe(result.output).duration - 6.0) <= 1.0
    lessons = db.recent_lessons("cutter")
    assert lessons and lessons[0]["check_name"] == "duration"
    # the lesson is injected into the cutter's prompt next time
    assert "LESSONS FROM PAST MISTAKES" in CutterAgent().build_prompt(ctx)


def test_api_key_protects_everything_but_health(tmp_path, music_dir):
    settings = make_settings(tmp_path / "data", music_dir, api_key="s3cret-test-key")
    with TestClient(create_app(settings)) as c:
        assert c.get("/health").status_code == 200 and c.get("/health").json()["auth_required"] is True
        r = c.get("/projects")
        assert r.status_code == 401 and err(r)["code"] == "unauthorized"
        assert c.get("/projects", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/projects", headers={"X-API-Key": "s3cret-test-key"}).status_code == 200
        assert c.get("/projects?api_key=s3cret-test-key").status_code == 200  # <video>/<img> URLs
        assert c.options("/projects", headers={"Origin": "http://x", "Access-Control-Request-Method": "GET"}).status_code == 200


def test_second_job_reports_queue_position(client, media, tmp_path):
    """One worker: a job submitted while another runs must say it is waiting (seen live: looked 'stuck')."""
    pid = new_project(client)
    client.post(f"/projects/{pid}/clips", files=[("files", ("s.mp4", small_clip(media, tmp_path).read_bytes(), "video/mp4"))])
    first = client.post(f"/projects/{pid}/edit", json={"prompt": "trim to 4 seconds"}).json()["job_id"]
    second = client.post(f"/projects/{pid}/edit", json={"prompt": "trim to 3 seconds"}).json()["job_id"]
    snap = client.get(f"/jobs/{second}").json()
    assert snap["status"] == "queued" and snap["queue_position"] == 1 and "1 edit(s) ahead" in snap["stage"]
    done1 = wait_job(client, first)
    assert done1["status"] == "done" and done1["started_at"]
    assert wait_job(client, second)["status"] == "done"
