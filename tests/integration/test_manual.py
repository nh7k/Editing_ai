"""Manual editing (no AI): text/fonts/animations/looks/timeline operations, incremental re-render, clear errors."""

from __future__ import annotations

import time

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.manual import ManualError, apply_ops
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def env(tmp_path_factory, media, music_dir):
    data = tmp_path_factory.mktemp("manual")
    with TestClient(create_app(make_settings(data, music_dir))) as c:
        pid = c.post("/projects", json={"name": "manual"}).json()["id"]
        files = [("files", (p.name, p.read_bytes(), "video/mp4")) for p in (media["a"], media["c"])]
        assert c.post(f"/projects/{pid}/clips", files=files).status_code == 201
        yield c, pid


def run_manual(c, pid, ops):
    r = c.post(f"/projects/{pid}/manual", json={"ops": ops})
    assert r.status_code == 202, r.text
    t0 = time.monotonic()
    job = wait_job(c, r.json()["job_id"])
    return job, time.monotonic() - t0


def test_manual_needs_a_first_edit(env):
    c, _pid = env
    pid2 = c.post("/projects", json={"name": "empty"}).json()["id"]
    r = c.post(f"/projects/{pid2}/manual", json={"ops": [{"op": "remove_captions"}]})
    assert r.status_code == 422 and "first edit" in r.json()["error"]["message"]


def test_manual_text_change_reuses_the_cut(env):
    c, pid = env
    r = c.post(f"/projects/{pid}/edit", json={"prompt": "trim to 8 seconds, add captions"})
    first = wait_job(c, r.json()["job_id"])
    assert first["status"] == "done"
    job, took = run_manual(c, pid, [
        {"op": "add_text", "text": "HELLO", "preset": "neon", "animation": "spin_in", "position": "top"},
        {"op": "style_captions", "preset": "hormozi"},
    ])
    assert job["status"] == "done", job["error"]
    stages = [e.get("stage") for e in job["events"] if e["type"] == "progress"]
    assert "reusing the cut (only text / audio changed)" in stages  # no segment was re-rendered
    plan = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    hello = next(t for t in plan.text if t.text == "HELLO")
    assert hello.style.font == "monoton" and hello.style.animation == "spin_in"
    assert all(t.style.preset == "hormozi" for t in plan.text if t.kind == "caption")
    assert abs(job["output"]["duration"] - plan.total_duration()) < 0.3
    print(f"text-only manual edit: {took:.1f}s")


def test_manual_look_and_timeline_changes(env):
    c, pid = env
    before = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    job, _ = run_manual(c, pid, [{"op": "set_look", "preset": "teal_orange"}, {"op": "set_transition", "type": "fade"},
                                 {"op": "add_effect", "type": "vhs", "start": 0, "end": 3}])
    assert job["status"] == "done", job["error"]
    plan = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    assert plan.color.preset == "teal_orange"
    assert any(e.type == "vhs" and e.target >= 0 for e in plan.effects)
    assert len(plan.clips) == len(before.clips)


def test_manual_errors_are_clear(env):
    c, pid = env
    for ops, needle in (([{"op": "add_text", "text": "x", "preset": "nope"}], "unknown text preset"),
                        ([{"op": "add_effect", "type": "laser_eyes"}], "can't be added"),
                        ([{"op": "delete_segment", "index": 99}], "no clip #99"),
                        ([{"op": "set_look", "preset": "purple_rain"}], "unknown look")):
        r = c.post(f"/projects/{pid}/manual", json={"ops": ops})
        assert r.status_code == 422 and needle in r.json()["error"]["message"], r.text
    assert c.post(f"/projects/{pid}/manual", json={"ops": [{"op": "fly"}]}).status_code == 422


def test_apply_ops_timeline_operations(env):
    c, pid = env
    plan = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    if len(plan.clips) < 2:
        pytest.skip("needs at least two segments")
    from cutmind.manual import ManualEdit

    ops = ManualEdit.model_validate({"ops": [{"op": "set_speed", "index": 0, "speed": 2.0},
                                             {"op": "move_segment", "index": 0, "to": 1}]}).ops
    new, notes = apply_ops(plan, ops)
    first = min(new.clips, key=lambda s: s.order)
    assert first.source == sorted(plan.clips, key=lambda s: s.order)[1].source
    assert any(s.speed == 2.0 for s in new.clips) and len(notes) == 2
    with pytest.raises(ManualError):
        apply_ops(plan, ManualEdit.model_validate({"ops": [{"op": "remove_text", "index": 500}]}).ops)
