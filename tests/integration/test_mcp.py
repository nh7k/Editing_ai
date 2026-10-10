"""MCP server: a real MCP client lists the tools and drives a full edit through them."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from conftest import make_settings
from mcp import Client

from cutmind.api import create_app
from cutmind.mcp_server import build_server

pytestmark = pytest.mark.integration


def _data(result) -> object:
    if getattr(result, "structured_content", None) is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


def test_mcp_client_runs_an_edit_end_to_end(tmp_path, media, music_dir):
    app = create_app(make_settings(tmp_path / "data", music_dir))
    server = build_server("http://cutmind", api_key="", transport=httpx.ASGITransport(app=app))

    async def scenario() -> None:
        async with Client(server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"capabilities", "create_project", "upload_clip", "understand", "start_edit", "wait_for_job",
                    "get_plan", "output_link", "list_effects", "agents_for", "transcribe_voice", "manual_edit",
                    "text_styles", "pro_templates"} <= names
            cap = _data(await c.call_tool("capabilities", {}))
            assert cap["features"]["video_editing"] == "available"
            pid = _data(await c.call_tool("create_project", {"name": "via mcp"}))["id"]
            up = _data(await c.call_tool("upload_clip", {"project_id": pid, "file_path": str(media["a"])}))
            assert len(up["clips"]) == 1
            u = _data(await c.call_tool("understand", {"prompt": "isko 9:16 bana do, thoda garam rang, captions daal do"}))
            assert "9:16 vertical." in u["solid_prompt"] and "Warm color." in u["solid_prompt"]
            started = _data(await c.call_tool("start_edit", {"project_id": pid,
                                                             "prompt": "isko 9:16 bana do, thoda garam rang, captions daal do"}))
            assert started["understood_as"] == u["solid_prompt"]
            done = _data(await c.call_tool("wait_for_job", {"job_id": started["job_id"], "timeout_seconds": 600}))
            assert done["status"] == "done" and done["match_percent"] >= 90, done
            plan = _data(await c.call_tool("get_plan", {"project_id": pid}))
            assert plan["canvas"]["aspect_ratio"] == "9:16" and any(t["kind"] == "caption" for t in plan["text"])
            m = _data(await c.call_tool("manual_edit", {"project_id": pid, "ops": [
                {"op": "add_text", "text": "MCP", "preset": "neon", "animation": "zoom_in"}]}))
            done2 = _data(await c.call_tool("wait_for_job", {"job_id": m["job_id"], "timeout_seconds": 600}))
            assert done2["status"] == "done", done2
            plan2 = _data(await c.call_tool("get_plan", {"project_id": pid}))
            assert any(t["text"] == "MCP" and t["style"]["animation"] == "zoom_in" for t in plan2["text"])
            assert len(_data(await c.call_tool("pro_templates", {}))["prompts"]) >= 20
            bad = await c.call_tool("upload_clip", {"project_id": pid, "file_path": str(tmp_path / "nope.mp4")})
            assert bad.is_error

    asyncio.run(scenario())
