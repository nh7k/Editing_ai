"""LangGraph workflow: live SSE events, checkpoint resume after a crash, router, capabilities."""

from __future__ import annotations

import json

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind import workflow
from cutmind.agent_registry import REGISTRY, route
from cutmind.agents.base import AgentContext, ClipRef
from cutmind.agents.director import DirectorAgent
from cutmind.api import create_app
from cutmind.db import Database
from cutmind.ffmpeg_utils import probe
from cutmind.intent import parse_intent

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path, music_dir):
    with TestClient(create_app(make_settings(tmp_path / "data", music_dir))) as c:
        yield c


def _sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        ev = {k: v for k, _, v in (line.partition(": ") for line in block.splitlines() if ": " in line)}
        if "event" in ev:
            out.append({"event": ev["event"], **json.loads(ev.get("data", "{}"))})
    return out


def test_live_events_stream_every_real_step(client, media):
    pid = client.post("/projects", json={"name": "events"}).json()["id"]
    files = [("files", (p.name, p.read_bytes(), "video/mp4")) for p in (media["a"], media["c"])]
    assert client.post(f"/projects/{pid}/clips", files=files).status_code == 201
    solid = client.post("/understand", json={"prompt": "silence hata aur captions laga, starting ke 2 sec zoom"}).json()
    assert "Remove silences." in solid["solid_prompt"] and "Zoom in for the first 2 seconds." in solid["solid_prompt"]
    job_id = client.post(f"/projects/{pid}/edit", json={"prompt": solid["solid_prompt"]}).json()["job_id"]
    with client.stream("GET", f"/jobs/{job_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _sse(r.read().decode())
    kinds = [e["event"] for e in events]
    assert kinds[-1] == "end" and events[-1]["status"] == "done"
    seqs = [e["seq"] for e in events if "seq" in e]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    nodes = [e["node"] for e in events if e["event"] == "node_completed"]
    assert nodes[:2] == ["understand", "analyze"] and {"audio", "cutter", "color", "effects", "render", "review", "finalize"} <= set(nodes)
    assert all(e["ms"] >= 0 for e in events if e["event"] == "node_completed")
    picked = next(e for e in events if e["event"] == "agents_selected")["agents"]
    ids = {a["id"] for a in picked}
    assert {"transcriber", "silence_detector", "caption_writer", "fx_scheduler"} <= ids and "lut_teal_orange" not in ids
    assert "review_completed" in kinds and "final_ready" in kinds and "job_done" in kinds
    started = {e["agent"] for e in events if e["event"] == "agent_started"}
    assert {"director", "analyzer", "audio", "cutter", "color", "effects", "reviewer"} <= started
    job = wait_job(client, job_id)
    assert job["status"] == "done"
    # a finished job replays its events (e.g. after a page reload)
    with client.stream("GET", f"/jobs/{job_id}/events?after={seqs[-5]}") as r:
        replay = _sse(r.read().decode())
    assert [e["seq"] for e in replay if "seq" in e] == seqs[-4:]


def test_checkpoint_resume_skips_finished_nodes(tmp_path, media, music_dir, monkeypatch):
    settings = make_settings(tmp_path / "data", music_dir)
    clips = [ClipRef("A", media["a"], "a.mp4", 0), ClipRef("C", media["c"], "c.mp4", 1)]

    def ctx() -> AgentContext:
        return AgentContext(job_id="crash_job", prompt="trim to 8 seconds, warm color", clips=clips, settings=settings,
                            db=Database(tmp_path / "db.sqlite3"), work_dir=tmp_path / "proj" / "work" / "crash_job")

    real_render = workflow.render
    calls = {"render": 0}

    def crashing_render(*a, **k):
        calls["render"] += 1
        if calls["render"] == 1:
            raise RuntimeError("simulated power cut during rendering")
        return real_render(*a, **k)

    monkeypatch.setattr(workflow, "render", crashing_render)
    with pytest.raises(Exception, match="power cut"):
        DirectorAgent().run_job(ctx(), tmp_path / "out.mp4")

    class Counting:
        nodes: list[str] = []

        def stage(self, *a, **k): ...
        def agent(self, *a, **k): ...

        def event(self, kind, **data):
            if kind == "node_started":
                self.nodes.append(data["node"])

    tracker = Counting()
    result = DirectorAgent().run_job(ctx(), tmp_path / "out.mp4", tracker, resume=True)
    # resumed AT the render node: understanding, analysis and planning were not redone
    assert tracker.nodes[0] == "render" and "understand" not in tracker.nodes and "cutter" not in tracker.nodes
    assert abs(probe(tmp_path / "out.mp4").duration - 8.0) < 0.6
    assert result.review.match_percent >= 90


@pytest.mark.parametrize("prompt,must,must_not", [
    ("silence hata aur captions laga", {"transcriber", "silence_detector", "caption_writer"}, {"style_designer", "music_supervisor"}),
    ("warm cinematic bana", {"color_grader"}, {"transcriber", "caption_writer", "clip_selector"}),
    ("mast sa edit kar do", {"auto_editor", "hook_finder", "story_arranger"}, {"video_generator"}),
    ("glitch effect, pixelize transitions", {"fx_glitch", "tr_pixelize"}, {"transcriber"}),
])
def test_router_runs_only_what_is_needed(prompt, must, must_not):
    ids = {s.id for s in route(parse_intent(prompt))}
    assert must <= ids and not (must_not & ids)
    assert len(ids) < 40


def test_registry_is_large_but_every_role_is_backed_by_code():
    assert len(REGISTRY) >= 150
    assert all(s.impl and s.impl != "-" for s in REGISTRY if s.available)
    assert all(s.unavailable_reason for s in REGISTRY if not s.available)


def test_warm_cinematic_skips_speech_to_text(tmp_path, media, music_dir):
    settings = make_settings(tmp_path / "data", music_dir)
    clips = [ClipRef("A", media["a"], "a.mp4", 0)]
    c = AgentContext(job_id="warm_job", prompt="warm cinematic bana", clips=clips, settings=settings,
                     work_dir=tmp_path / "proj" / "work" / "warm_job")
    DirectorAgent().run_job(c, tmp_path / "warm.mp4")
    assert c.need_transcript is False
    assert c.analysis.get("A").transcription == "skipped" and not c.analysis.get("A").words


def test_capabilities_and_developer_endpoints(client):
    cap = client.get("/capabilities").json()
    assert {"cpu_threads", "ram_total_mb", "gpu", "ffmpeg", "features"} <= set(cap)
    if not cap["gpu"]:
        assert "GPU feature unavailable" in cap["features"]["video_generation"]
    assert cap["features"]["video_editing"] == "available"
    reg = client.get("/agents", params={"prompt": "captions daal do"}).json()
    assert reg["total"] >= 150 and "caption_writer" in reg["selected"]
    assert "understand --> analyze" in client.get("/workflow").json()["mermaid"]


def test_server_restart_resumes_an_interrupted_job(tmp_path, media, music_dir, monkeypatch):
    """A job dies mid-render (power cut). The next server start continues it from the checkpoint."""
    settings = make_settings(tmp_path / "data", music_dir)
    app = create_app(settings)
    db = app.state.db
    pid = db.create_project("crash")["id"]
    clip_path = settings.projects_dir / pid / "clips" / "a.mp4"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(media["a"].read_bytes())
    info = probe(clip_path)
    cid = db.add_clip(pid, "a.mp4", str(clip_path), {"duration": info.duration, "width": info.width, "height": info.height,
                                                    "fps": info.fps, "has_audio": info.has_audio,
                                                    "size_bytes": info.size_bytes})["id"]
    job_id = db.create_job(pid, "trim to 6 seconds, cool color", {})
    db.update_job(job_id, status="running")
    real_render = workflow.render
    monkeypatch.setattr(workflow, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("power cut")))
    ctx = AgentContext(job_id=job_id, prompt="trim to 6 seconds, cool color",
                       clips=[ClipRef(cid, clip_path, "a.mp4", 0)], settings=settings, db=db,
                       work_dir=settings.projects_dir / pid / "work" / job_id)
    with pytest.raises(Exception, match="power cut"):
        DirectorAgent().run_job(ctx, settings.projects_dir / pid / "output" / f"{job_id}.mp4")
    monkeypatch.setattr(workflow, "render", real_render)
    # "restart": a new app on the same data directory
    with TestClient(create_app(settings)) as c:
        job = wait_job(c, job_id)
    assert job["status"] == "done", job.get("error")
    kinds = [e["type"] for e in job["events"]]
    assert "job_resumed" in kinds and kinds.index("job_resumed") < kinds.index("node_started")
    nodes = [e["node"] for e in job["events"] if e["type"] == "node_started"]
    assert nodes[0] == "render" and "understand" not in nodes
    assert abs(job["output"]["duration"] - 6.0) < 0.5


def test_no_rerender_when_the_failure_cannot_be_fixed(tmp_path, media, music_dir):
    """Captions asked for footage where nobody speaks: report it, but don't burn two more renders retrying."""
    settings = make_settings(tmp_path / "data", music_dir)
    clips = [ClipRef("C", media["c"], "c.mp4", 0)]  # scenes clip: no speech
    c = AgentContext(job_id="nospeech", prompt="add captions, warm color", clips=clips, settings=settings,
                     work_dir=tmp_path / "proj" / "work" / "nospeech")
    result = DirectorAgent().run_job(c, tmp_path / "o.mp4")
    assert len(result.history) == 1
    failed = {ch.name for ch in result.review.checks if not ch.passed}
    assert failed == {"speech_detected", "captions_present"}
    assert any("nobody speaks" in ch.detail for ch in result.review.checks)
