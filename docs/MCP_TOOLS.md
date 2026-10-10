# MCP tools

Server: `backend/cutmind/mcp_server.py` (setup in ../MCP.md). 16 tools, all backed by the CutMind API:

| Group | Tools |
|---|---|
| system | `capabilities`, `agents_for` |
| projects / media | `list_projects`, `create_project`, `upload_clip`, `transcribe_voice` |
| understanding | `understand` (clean prompt + edit spec) |
| AI edit | `start_edit`, `job_status`, `wait_for_job`, `get_plan`, `output_link` |
| manual (deterministic, no AI) | `manual_edit` (add/update/remove text incl. person-following labels, style captions, add/remove effects, transitions, looks, styles, delete/move/speed segments), `text_styles` |
| catalogues | `list_effects`, `pro_templates` |

Tested in `tests/integration/test_mcp.py` with a real MCP client: full AI edit, then a manual text edit, templates,
and an error case. Not exposed on purpose: shell access, raw FFmpeg arguments, file deletion.
