"""MCP file access: import_clip (was upload_clip) / transcribe_voice read ONLY from the allowed folders (CutMind inbox, test fixtures,
CUTMIND_MCP_ALLOW). Before, any MCP client could make the server read any file on the computer (a prompt-injected
"upload C:/Users/.../secrets.txt" would have been read and sent to the API)."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
from conftest import make_settings
from mcp import Client

from cutmind import mcp_server
from cutmind.api import create_app
from cutmind.ffmpeg_utils import run_ffmpeg

pytestmark = pytest.mark.integration


@pytest.fixture
def env(tmp_path, monkeypatch, music_dir):
    local = tmp_path / "cutmind_local"
    (local / "inbox").mkdir(parents=True)
    monkeypatch.setenv("CUTMIND_LOCAL_DIR", str(local))
    monkeypatch.delenv("CUTMIND_MCP_ALLOW", raising=False)
    good = local / "inbox" / "clip.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(good)])
    outside = tmp_path / "private" / "clip.mp4"
    outside.parent.mkdir()
    outside.write_bytes(good.read_bytes())
    app = create_app(make_settings(tmp_path / "data", music_dir))
    server = mcp_server.build_server("http://cutmind", api_key="", transport=httpx.ASGITransport(app=app))
    return server, local, good, outside, tmp_path


def run(server, steps):  # noqa: ANN001
    async def go():  # noqa: ANN202
        async with Client(server) as c:
            return await steps(c)
    return asyncio.run(go())


def text(res) -> str:  # noqa: ANN001
    return " ".join(getattr(x, "text", "") for x in res.content)


def test_only_allowed_folders_can_be_read(env, monkeypatch):
    server, local, good, outside, tmp_path = env
    secret = tmp_path / "private" / "secrets.txt"
    secret.write_text("API_KEY=do-not-leak", encoding="utf-8")
    wrong_type = local / "inbox" / "notes.txt"
    wrong_type.write_text("hello", encoding="utf-8")
    traversal = str(local / "inbox" / ".." / ".." / "private" / "clip.mp4")

    async def steps(c):  # noqa: ANN001, ANN202
        pid = (await c.call_tool("create_project", {"name": "sec"})).structured_content
        pid = pid.get("result", pid)["project_id"]
        ok = await c.call_tool("import_clip", {"project_id": pid, "path": str(good)})
        assert not ok.is_error, text(ok)
        out = {}
        for name, path in {"outside": str(outside), "traversal": traversal, "secret": str(secret),
                           "wrong_type": str(wrong_type), "missing": str(local / "inbox" / "nope.mp4")}.items():
            r = await c.call_tool("import_clip", {"project_id": pid, "path": path})
            out[name] = (r.is_error, text(r))
        tv = await c.call_tool("transcribe_voice", {"path": str(secret)})
        out["transcribe_secret"] = (tv.is_error, text(tv))
        return out

    out = run(server, steps)
    for name in ("outside", "traversal", "secret", "transcribe_secret"):
        is_err, msg = out[name]
        assert is_err and "not allowed" in msg, (name, msg)
        assert "do-not-leak" not in msg  # the file was never read
    assert out["wrong_type"][0] and "file type" in out["wrong_type"][1]
    assert out["missing"][0] and "not found" in out["missing"][1]


def test_extra_folders_only_by_env_and_size_limit(env, monkeypatch):
    server, local, good, outside, tmp_path = env
    monkeypatch.setenv("CUTMIND_MCP_ALLOW", str(outside.parent))
    monkeypatch.setattr(mcp_server, "MAX_IMPORT_MB", 0)  # every file is now "too big"

    async def steps(c):  # noqa: ANN001, ANN202
        pid = (await c.call_tool("create_project", {"name": "sec2"})).structured_content
        pid = pid.get("result", pid)["project_id"]
        return await c.call_tool("import_clip", {"project_id": pid, "path": str(outside)})

    r = run(server, steps)
    assert r.is_error and "larger than" in text(r)  # allowed folder now, but over the size limit


def test_a_link_out_of_the_inbox_is_refused(env):
    server, local, good, outside, tmp_path = env
    link = local / "inbox" / "link.mp4"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("this Windows account may not create symbolic links")

    async def steps(c):  # noqa: ANN001, ANN202
        pid = (await c.call_tool("create_project", {"name": "sec3"})).structured_content
        pid = pid.get("result", pid)["project_id"]
        return await c.call_tool("import_clip", {"project_id": pid, "path": str(link)})

    r = run(server, steps)
    assert r.is_error and "not allowed" in text(r)
