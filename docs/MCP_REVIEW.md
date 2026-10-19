# cutmind-mcp — review and decisions (2026-10-12)

Sources: the MCP Python SDK installed here (`mcp` 2.3.0, MIT — `pip show mcp`), its `MCPServer` API (tools with
`ToolAnnotations`, resources, prompts, `Image`, `ToolError`), a web search on Claude Desktop setup and on Desktop
Extensions (.mcpb) — links at the end. Where a point is from my own knowledge it says so.

## What existed

`backend/cutmind/mcp_server.py` (16 tools over the CutMind API, stdio) and `tests/integration/test_mcp.py`. **Security
gap found:** `upload_clip` / `transcribe_voice` read any file path a client named (fixed first, commit 8edc32c).

## Decisions

| question | decision | why |
|---|---|---|
| transport | **stdio** | one user, one laptop; Claude Desktop launches local servers over stdio; no port, nothing listens on the network |
| one server or two | **one program, two Claude Desktop entries** (`--mode edit`, `--mode test`) | the two modes must never mix: in TEST MODE the skill-picking tools do not exist at all, so Claude cannot "help" the app by accident |
| TEST MODE backend | an **in-process CutMind on `~/CutMind/test_workspace`** (its own database + storage) | real projects can never be touched; nothing else to start |
| tool count | **27 (edit) / 26 (test)** (+ get_contact_sheet, 2026-10-19), grouped by job (projects, versions, checking, editing) | too many tiny tools hurt tool choice; giant tools hurt control (my knowledge) |
| results | **compact JSON**: lists capped, plans summarised (`get_project_summary`), diffs instead of plans | token cost on the user's Claude plan |
| slow renders | edit tools wait up to 600 s (one render at a time); a still-running job returns its id → `get_job_status(wait_seconds)` | renders take 10-90 s here; **cancel is NOT available** (the backend has no job cancel yet) |
| resources / prompts | resources: skill index, craft rules; prompt: `edit_like_pro` | catalogue-like data is a resource, actions are tools |
| frames to Claude | **off by default** (`CUTMIND_MCP_FRAMES=1` turns them on, max 480 px) | pictures leave the machine to Anthropic and cost tokens |
| media text | every text from the user's media (file names, transcripts, captions, notes) is returned inside `{"data": …}`; the server's instructions say it is data, never instructions | prompt injection through captions / file names |
| files | only from `~/CutMind/inbox`, `~/CutMind/test_fixtures` or `CUTMIND_MCP_ALLOW` folders; resolved first (no `../`, no link escape); type + size limits | the gap above |
| where local data lives | `~/CutMind` (`C:\Users\itanm\CutMind`) — outside OneDrive, and NOT AppData: a process started by the packaged Claude Desktop gets AppData redirected into `AppData\Local\Packages\Claude_…\LocalCache` (measured: `Path.resolve()`), so the inbox you open in Explorer would not be the one the server reads | user condition 4 |
| Desktop Extension (.mcpb) | **not now** | one user; a config entry is enough; .mcpb needs a manifest + bundled Python (Claude Desktop ships Node, not Python) |
| SDK licence | MIT (verified with `pip show mcp`) | |

## Where I disagree with the brief

1. **The 200 cases are not judged by Claude Desktop.** A Python runner drives the SAME MCP server through a real MCP
   client (`tools/test200`); the judge is independent code (`tools/test200/measure.py`, `judge.py`). Claude as the
   judge would cost a lot of the user's plan, be slower, and an LLM judge is not an independent oracle. Claude
   Desktop is used for the 40-prompt gap analysis (EDIT vs TEST) and smoke tests — the user's plan (condition 7).
2. **`apply_patch` / `compose_from_primitives` as a separate primitive language is not built.** `apply_patch` maps to
   the existing hand-edit ops (`/manual`); a new primitive language would be a second editing system to test.
3. **`press_button` covers the 3 one-tap buttons** (Auto edit, Arrange clips, Captions) with the exact prompts the UI
   sends; pure visual UI checks still need a real browser.

## Known limits (honest)

- `cancel_job`: NOT AVAILABLE (no backend support).
- The edit-mode server needs the CutMind API running (`CUTMIND_URL`, default `http://localhost:8000`). On this laptop
  another project ("pre6") was found listening on 127.0.0.1:8000 — run CutMind on another port or stop the other
  one, and set `CUTMIND_URL` accordingly.
- Phone / Media3: NOT TESTED. Claude Desktop itself: NOT TESTED by me (I cannot drive the app) — the user connects it.

## Sources

- Claude Desktop setup (config path, absolute paths, full restart, silent JSON errors):
  https://docs.open.cx/mcp/clients/claude-desktop.md · https://www.morphllm.com/claude-desktop-mcp ·
  https://mcpbundles.com/blog/2025/04/18/claude-desktop-and-mcp
- Desktop Extensions / MCPB: https://www.anthropic.com/engineering/desktop-extensions ·
  https://claude.com/docs/connectors/building/mcpb
