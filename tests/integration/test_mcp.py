"""cutmind-mcp with a real MCP client, both modes (docs/MCP_REVIEW.md).

EDIT MODE: Claude may pick skills — search_skills → apply_skill → verify_output → undo; plus edit_with_words.
TEST MODE: no skill picking exists; a phrase reaches the app only through run_prompt (the chat path) and the
result carries the app's own reading, route, message and measurements."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from conftest import make_settings
from mcp import Client

from cutmind.api import create_app
from cutmind.ffmpeg_utils import run_ffmpeg
from cutmind.mcp_server import build_server

pytestmark = pytest.mark.integration


def data(result) -> object:  # noqa: ANN001
    assert not result.is_error, " ".join(getattr(x, "text", "") for x in result.content)
    sc = getattr(result, "structured_content", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


@pytest.fixture
def env(tmp_path, monkeypatch, music_dir):
    local = tmp_path / "local"
    (local / "inbox").mkdir(parents=True)
    monkeypatch.setenv("CUTMIND_LOCAL_DIR", str(local))
    clip = local / "inbox" / "clip.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=5", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=5", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    app = create_app(make_settings(tmp_path / "data", music_dir))
    return httpx.ASGITransport(app=app), clip


def test_edit_mode_claude_picks_a_skill_verifies_and_undoes(env):
    transport, clip = env
    server = build_server("http://cutmind", api_key="", transport=transport, mode="edit")

    async def go() -> None:
        async with Client(server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"health_check", "create_project", "import_clip", "search_skills", "apply_skill", "apply_patch",
                    "verify_output", "undo", "compare_versions", "edit_with_words", "render_final"} <= names
            assert "run_prompt" not in names and "reset_workspace" not in names  # modes never mix
            h = data(await c.call_tool("health_check", {}))
            assert h["api_ok"] and h["mode"] == "edit" and h["frames_to_claude"] is False
            pid = data(await c.call_tool("create_project", {"name": "mcp edit"}))["project_id"]
            assert data(await c.call_tool("import_clip", {"project_id": pid, "path": str(clip)}))["ok"]
            found = data(await c.call_tool("search_skills", {"query": "thoda warm karo"}))
            assert found["choices"][0]["skill"] == "warm"
            dry = data(await c.call_tool("apply_skill", {"project_id": pid, "skill_id": "warm", "dry_run": True}))
            assert dry["dry_run"] and dry["skill_exists"]
            job = data(await c.call_tool("apply_skill", {"project_id": pid, "skill_id": "warm"}))
            assert job["status"] == "done" and job["route"] == "skills", job
            v = data(await c.call_tool("verify_output", {"project_id": pid}))
            assert v["ok"] and v["decodes"] and v["has_audio"]
            summ = data(await c.call_tool("get_project_summary", {"project_id": pid}))
            assert summ["versions"] >= 1 and "grade" in summ["edit"]["effects"]
            vs = data(await c.call_tool("list_versions", {"project_id": pid}))["versions"]
            w = data(await c.call_tool("edit_with_words", {"project_id": pid, "text": "halka vignette lagao"}))
            assert w["http"] == 202 and w["job"]["status"] == "done", w
            vs2 = data(await c.call_tool("list_versions", {"project_id": pid}))["versions"]
            cmp = data(await c.call_tool("compare_versions", {"project_id": pid, "a_job_id": vs[-1]["job_id"],
                                                               "b_job_id": vs2[-1]["job_id"]}))
            assert any("vignette" in x for x in cmp["changed"]), cmp
            assert data(await c.call_tool("undo", {"project_id": pid}))["version"]
            fr = data(await c.call_tool("get_frame", {"project_id": pid, "time_s": 1.0}))
            assert fr["frames_disabled"]  # no picture leaves the machine unless switched on
            rf = data(await c.call_tool("render_final", {"project_id": pid}))
            assert rf["needs_confirm"]  # costly / overwriting actions need confirm=true
            # a file outside the allowed folders is refused (the security fix, through the new tool name)
            bad = await c.call_tool("import_clip", {"project_id": pid, "path": __file__})
            assert bad.is_error and "not allowed" in " ".join(x.text for x in bad.content)
            # every call is logged locally, without prompt text
            logs = data(await c.call_tool("get_logs", {"correlation_id": w["correlation_id"]}))["lines"]
            assert logs and all("halka" not in json.dumps(x) for x in logs)

    asyncio.run(go())


def test_test_mode_only_run_prompt_reaches_the_app(env):
    transport, clip = env
    server = build_server("http://cutmind-test", api_key="", transport=transport, mode="test")

    async def go() -> None:
        async with Client(server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert "run_prompt" in names and "compare_claims_vs_measurements" in names
            assert not {"apply_skill", "search_skills", "apply_patch", "edit_with_words"} & names  # no helping the app
            pid = data(await c.call_tool("create_project", {"name": "mcp test"}))["project_id"]
            data(await c.call_tool("import_clip", {"project_id": pid, "path": str(clip)}))
            dry = data(await c.call_tool("run_prompt", {"project_id": pid, "text": "blak and wite kro", "dry_run": True}))
            assert dry["dry_run"] and dry["reading"]["decision"] in ("apply", "act", "choose")
            assert "black" in dry["reading"]["normalized"]  # the app's own normalisation, shown as data
            first = data(await c.call_tool("run_prompt", {"project_id": pid, "text": "warm karo"}))
            assert first["http"] == 202 and first["job"]["status"] == "done"
            r = data(await c.call_tool("run_prompt", {"project_id": pid, "text": "blak and wite kro"}))
            assert r["http"] == 202 and r["job"]["status"] == "done" and r["versions"][1] == r["versions"][0] + 1, r
            cc = data(await c.call_tool("compare_claims_vs_measurements", {"project_id": pid}))
            assert cc["measured"]["picture_change"] > 3 and cc["problems"] == [], cc
            nope = data(await c.call_tool("run_prompt", {"project_id": pid, "text": "asdf qwerty zxcv"}))
            assert nope["http"] == 422 and nope["code"] == "not_understood" and nope["chips"]  # never a dead end
            assert data(await c.call_tool("reset_workspace", {}))["needs_confirm"]

    asyncio.run(go())
