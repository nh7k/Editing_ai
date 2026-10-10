"""The editor's-mind API: /projects/{id}/explain, /reference-style, /taste (+ reset), /llm/health, the per-client
rate limit, and the planner-model fallback (a dead model never breaks an edit). Real FFmpeg renders."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.llm_provider import MockProvider, RulesOnlyProvider, set_provider_for_tests

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def env(tmp_path_factory, media, music_dir):
    data = tmp_path_factory.mktemp("mind")
    mp = pytest.MonkeyPatch()
    mp.setenv("RATE_LIMIT_PER_MIN", "6")
    with TestClient(create_app(make_settings(data, music_dir))) as c:
        pid = c.post("/projects", json={"name": "mind"}).json()["id"]
        files = [("files", (p.name, p.read_bytes(), "video/mp4")) for p in (media["a"], media["c"])]
        assert c.post(f"/projects/{pid}/clips", files=files).status_code == 201
        yield c, pid
    mp.undo()
    set_provider_for_tests(RulesOnlyProvider())


def edit(c, pid, prompt):
    r = c.post(f"/projects/{pid}/edit", json={"prompt": prompt})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    return job


def test_explain_after_two_edits(env):
    c, pid = env
    edit(c, pid, "8 second ka edit, warm color")
    edit(c, pid, "black and white karo")
    ex = c.get(f"/projects/{pid}/explain").json()
    assert any("colour" in x for x in ex["changed"]), ex
    assert ex["understood"] and 1 <= len(ex["suggestions"]) <= 3


def test_planner_model_reading_is_used_and_a_dead_model_never_breaks_an_edit(env):
    c, pid = env
    set_provider_for_tests(MockProvider({"gaane ki awaaz thodi dheemi kar do": {
        "commands": [{"id": "music_softer", "value": ""}], "confidence": 0.9}}))
    job = edit(c, pid, "gaane ki awaaz thodi dheemi kar do")
    assert job["status"] == "done"
    assert c.get("/llm/health").json()["last_trace"][-1]["result"] == "used"
    set_provider_for_tests(MockProvider(mode="timeout"))
    assert edit(c, pid, "thoda bright karo")["status"] == "done"  # the rules answer
    set_provider_for_tests(RulesOnlyProvider())


def test_taste_and_reset(env):
    c, _pid = env
    t = c.get("/taste").json()
    assert "preferences" in t and "knobs" in t
    r = c.delete("/taste").json()
    assert r["ok"] and r["preferences"].get("edits_remembered", 0) == 0


def test_reference_style_profile(env, media):
    c, _pid = env
    r = c.post("/reference-style", files={"file": ("ref.mp4", media["c"].read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    prof = r.json()["profile"]
    assert prof["shot_len"][0] <= prof["shot_len"][1] and prof["aspect"] in ("9:16", "16:9", "1:1")
    assert "measured" in prof


def test_rate_limit_per_client(env):
    c, pid = env
    codes = [c.post(f"/projects/{pid}/edit", json={"prompt": "kya haal hai bhai"}).status_code for _ in range(8)]
    assert 429 in codes  # 6 per minute for this client (earlier tests used some of them)
