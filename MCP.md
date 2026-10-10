# MCP server

`backend/cutmind/mcp_server.py` (MCP Python SDK 2.x, `MCPServer`). It exposes CutMind's editing tools to any MCP
client. The tools call the running CutMind API, so MCP-started edits use the same queue, LangGraph workflow,
live events and Reviewer as the app. MCP = tools; LangGraph = orchestration.

## Run

```bash
cd backend
.venv/Scripts/python -m cutmind.mcp_server
```

Environment: `CUTMIND_URL` (default `http://localhost:8000`), `CUTMIND_API_KEY` (if the API has one).

Claude Desktop / other clients (`mcpServers` entry):

```json
{
  "cutmind": {
    "command": "C:/path/to/video editing/backend/.venv/Scripts/python.exe",
    "args": ["-m", "cutmind.mcp_server"],
    "cwd": "C:/path/to/video editing/backend",
    "env": {"CUTMIND_URL": "http://localhost:8000"}
  }
}
```

## Tools

| Tool | What it does |
|---|---|
| capabilities | CPU / RAM / GPU / FFmpeg / speech-to-text, which features are on |
| list_projects, create_project | projects |
| upload_clip(project_id, file_path) | upload a local video (server validates type/size/readability) |
| understand(prompt) | Hinglish / rough text → clean English prompt + what was understood |
| start_edit(project_id, prompt, aspect_ratio?, variations?, use_coach=True) | start an edit (coach first) |
| job_status(job_id), wait_for_job(job_id) | progress, review score, failed checks |
| get_plan(project_id), output_link(project_id, fmt) | Edit Plan JSON, download link |
| list_effects(category?) | FX catalogue |
| agents_for(prompt) | which specialists the router would run |
| transcribe_voice(file_path) | spoken request → English prompt (local Whisper) |

No tool runs shell commands or arbitrary FFmpeg arguments.

## Tested

* `tests/integration/test_mcp.py`: a real MCP client connects in-process, lists the tools, and runs a full edit
  (create → upload → understand → start_edit → wait → get_plan; 9:16 + captions, match ≥ 90 %), plus an error case.
* Manually over **stdio** against the live server: 13 tools listed; `understand` answered.
