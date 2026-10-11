"""The five prerequisites of the goal loop (docs/REALITY_MAP.md), end to end through the real API and FFmpeg:

1. "Use this" makes the chosen look's plan the current version (tested in test_e2e_api three_versions too).
2. "3 versions" is one-time (memory never carries it) and the asked look is the edit (rank 0).
3. One path for clear changes: after a director edit, "warm karo" is the warm skill on the current version;
   style words are read with negation ("violet authority hata do" takes it off, never adds it).
4. The answer reports a look change as a change, and "already in your edit" is checked on the plan.
5. Skill jobs are measured by the production verifier (the warm skill must make the picture warmer)."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import run_ffmpeg

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def env(tmp_path_factory, music_dir):
    d = tmp_path_factory.mktemp("prereq")
    clip = d / "c.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=6", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    with TestClient(create_app(make_settings(d / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "prereq"}).json()["id"]
        assert c.post(f"/projects/{pid}/clips", files=[("files", (clip.name, clip.read_bytes(), "video/mp4"))]).status_code == 201
        yield c, pid


def edit(c, pid, prompt, **extra):  # noqa: ANN001
    r = c.post(f"/projects/{pid}/edit", json={"prompt": prompt, **extra})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    return r.json(), job


def plan(c, pid):  # noqa: ANN001
    return c.get(f"/projects/{pid}/plan").json()


def test_asked_look_is_rank_0_and_three_versions_do_not_come_back(env):
    c, pid = env
    _, job = edit(c, pid, "violet authority look wala reel bana do", variations=3)
    assert [v["style"] for v in job["variations"]][0] == "violet_authority"  # the asked look is the edit
    assert plan(c, pid)["style"] == "violet_authority"
    # a later DIRECTOR message (a look ask) renders ONE version, not 3 again
    _, job2 = edit(c, pid, "midnight drift look lagao")
    assert job2["variations"] == [] and plan(c, pid)["style"] == "midnight_drift"
    ex = job2["explain"]
    assert any(x.startswith("look:") for x in ex["changed"]), ex  # a look change is a change
    assert not any("nothing" in w.lower() for w in ex["warnings"]), ex


def test_negated_look_is_taken_off_and_the_wanted_one_is_put_on(env):
    c, pid = env
    _, job = edit(c, pid, "cyan kinetic look lagao, violet authority hata do")
    assert plan(c, pid)["style"] == "cyan_kinetic", job["explain"]
    _, job = edit(c, pid, "cyan kinetic look hata do")
    p = plan(c, pid)
    assert p["style"] is None and not p["overlays"], job["explain"]


def test_clear_change_after_a_director_edit_is_the_skill_and_is_measured(env):
    c, pid = env
    before = plan(c, pid)
    body, job = edit(c, pid, "warm karo")
    assert body.get("decision") == "apply", body  # the skills, not a director re-edit
    after = plan(c, pid)
    assert len(after["clips"]) == len(before["clips"])  # exactly that change on the current version
    checks = job["explain"]["verify"]
    warm = next(x for x in checks if x["skill"] == "warm")
    assert warm["status"] == "passed", checks  # measured warmer on the video, not taken from the skill's notes
    assert isinstance(job["explain"]["summary"], str)
