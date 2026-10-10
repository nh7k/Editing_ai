"""MCP server: CutMind's editing tools for any MCP client (Claude Desktop, IDE agents, …).

    python -m cutmind.mcp_server            # stdio (what desktop MCP clients launch)
    CUTMIND_URL=http://localhost:8000 CUTMIND_API_KEY=... python -m cutmind.mcp_server

MCP = tools, LangGraph = orchestration: every tool calls the running CutMind API, so edits started from an MCP
client go through the same job queue, workflow, live events and reviewer as the app. Only controlled operations
are exposed (no shell, no arbitrary FFmpeg arguments).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

INSTRUCTIONS = (
    "CutMind edits videos from plain-language prompts (English, Hindi, Hinglish). Typical flow: list_projects or "
    "create_project → upload_clip → understand (shows the clean prompt) → start_edit → wait_for_job → output_link."
)


def build_server(base_url: str | None = None, api_key: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    base = (base_url or os.environ.get("CUTMIND_URL", "http://localhost:8000")).rstrip("/")
    key = api_key if api_key is not None else os.environ.get("CUTMIND_API_KEY", "")
    headers = {"X-API-Key": key} if key else {}
    server = MCPServer("CutMind", instructions=INSTRUCTIONS)

    def client(timeout: float = 120) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base, headers=headers, timeout=timeout, transport=transport)

    async def call(method: str, path: str, **kw: Any) -> Any:
        async with client() as c:
            r = await c.request(method, path, **kw)
        try:
            body = r.json()
        except ValueError:
            body = {"text": r.text[:500]}
        if r.status_code >= 400:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise RuntimeError(f"{err.get('code', r.status_code)}: {err.get('message', body)}")
        return body

    @server.tool()
    async def capabilities() -> dict[str, Any]:
        """What this machine can do: CPU/RAM/GPU, FFmpeg, speech-to-text, which features are on or off."""
        return await call("GET", "/capabilities")

    @server.tool()
    async def list_projects() -> list[dict[str, Any]]:
        """Projects with their clips."""
        return await call("GET", "/projects")

    @server.tool()
    async def create_project(name: str) -> dict[str, Any]:
        """Create an empty project."""
        return await call("POST", "/projects", json={"name": name})

    @server.tool()
    async def upload_clip(project_id: str, file_path: str) -> dict[str, Any]:
        """Upload a local video file into a project (validated by the server: type, size, readable)."""
        p = Path(file_path).expanduser()
        if not p.is_file():
            raise RuntimeError(f"file not found: {file_path}")
        async with client(timeout=600) as c:
            with p.open("rb") as fh:
                r = await c.post(f"/projects/{project_id}/clips", files={"files": (p.name, fh, "video/mp4")})
        if r.status_code >= 400:
            raise RuntimeError(r.text[:500])
        return r.json()

    @server.tool()
    async def understand(prompt: str) -> dict[str, Any]:
        """Turn a rough / Hinglish request into the clean English prompt CutMind will follow, and what it understood."""
        return await call("POST", "/understand", json={"prompt": prompt})

    @server.tool()
    async def start_edit(project_id: str, prompt: str, aspect_ratio: str | None = None, variations: int | None = None,
                         use_coach: bool = True) -> dict[str, Any]:
        """Start an edit. With use_coach (default) the response also says how the prompt was understood."""
        understood = None
        if use_coach:
            understood = await call("POST", "/understand", json={"prompt": prompt, "project_id": project_id})
        body: dict[str, Any] = {"prompt": prompt}  # own words: the clean version drops style / genre words
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if variations:
            body["variations"] = variations
        out = await call("POST", f"/projects/{project_id}/edit", json=body)
        return {**out, "prompt_sent": prompt, "understood_as": understood["solid_prompt"] if understood else None,
                "spec": understood.get("spec") if understood else None}

    @server.tool()
    async def job_status(job_id: str) -> dict[str, Any]:
        """Status, current stage, progress, review score and failed checks of an edit job."""
        j = await call("GET", f"/jobs/{job_id}")
        review = j.get("review") or {}
        return {"status": j["status"], "stage": j.get("stage"), "progress": j.get("progress"),
                "match_percent": j.get("match_percent"), "error": j.get("error"),
                "agent_scores": review.get("agent_scores"),
                "failed_checks": [c["name"] for c in review.get("checks", []) if not c["passed"]],
                "output": j.get("output")}

    @server.tool()
    async def wait_for_job(job_id: str, timeout_seconds: int = 900) -> dict[str, Any]:
        """Wait until the job is done or failed (polls every 2 s)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout_seconds
        while True:
            st = await job_status(job_id)
            if st["status"] in ("done", "failed") or loop.time() > end:
                return st
            await asyncio.sleep(2)

    @server.tool()
    async def get_plan(project_id: str) -> dict[str, Any]:
        """The Edit Plan JSON of the last finished edit (cuts, effects, captions, audio)."""
        return await call("GET", f"/projects/{project_id}/plan")

    @server.tool()
    async def output_link(project_id: str, fmt: str = "mp4") -> str:
        """Download link of the last finished edit (mp4, or gif / mp3 when they were asked for)."""
        return f"{base}/projects/{project_id}/output" + ("" if fmt == "mp4" else f"?format={fmt}")

    @server.tool()
    async def list_effects(category: str | None = None) -> dict[str, Any]:
        """The FX catalogue (motion, video effects, transitions, LUT looks, text animations)."""
        fx = await call("GET", "/fx")
        return {category: fx.get(category, [])} if category else fx

    @server.tool()
    async def agents_for(prompt: str) -> dict[str, Any]:
        """Which specialist agents the router would run for a prompt (out of the full registry)."""
        reg = await call("GET", "/agents", params={"prompt": prompt})
        return {"total": reg["total"], "selected": reg.get("selected", [])}

    @server.tool()
    async def manual_edit(project_id: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply deterministic changes to the last edit, no AI step. Ops (each a dict with "op"): add_text (text,
        preset, font, color, animation, position, track: none|person|face), update_text, remove_text, style_captions,
        remove_captions, add_effect (type, start, end), remove_effect, set_transition (type|null), set_look (preset),
        set_style, delete_segment (index), set_speed (index, speed), move_segment (index, to)."""
        return await call("POST", f"/projects/{project_id}/manual", json={"ops": ops})

    @server.tool()
    async def text_styles() -> dict[str, Any]:
        """Fonts, text presets, colours and text animations usable in manual_edit."""
        return await call("GET", "/text-styles")

    @server.tool()
    async def pro_templates() -> dict[str, Any]:
        """Ready-made professional briefs (party reel, cinematic travel, talking head pro, …) and known video types."""
        return await call("GET", "/prompts")

    @server.tool()
    async def transcribe_voice(file_path: str) -> dict[str, Any]:
        """Spoken request (audio file, any language) → English prompt text, with the local Whisper model."""
        p = Path(file_path).expanduser()
        if not p.is_file():
            raise RuntimeError(f"file not found: {file_path}")
        async with client(timeout=300) as c:
            with p.open("rb") as fh:
                r = await c.post("/transcribe", files={"audio": (p.name, fh, "application/octet-stream")})
        if r.status_code >= 400:
            raise RuntimeError(r.text[:500])
        return r.json()

    return server


if __name__ == "__main__":
    build_server().run()
