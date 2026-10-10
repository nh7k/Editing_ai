# Testing

```bash
cd backend
.venv/Scripts/python -m ruff check cutmind ../tests
.venv/Scripts/python -m pytest ../tests -q          # everything (~35 min on the test laptop: real renders)
.venv/Scripts/python -m pytest ../tests/unit -q     # fast (~3 min)
cd ../mobile && npx tsc --noEmit && npx expo lint && npx jest
```

Integration tests never mock FFmpeg, ffprobe, faster-whisper, PySceneDetect, librosa or LangGraph; renders are
checked with ffprobe and pixel measurements. Generated media: `tests/media/generated` (FFmpeg + Windows TTS).

| Area | File(s) |
|---|---|
| Edit plan, renderer, every FX visibly changes pixels | unit/test_plan, test_renderer*, test_fx_visible |
| Hinglish parsing, timed effects, bass, no-music | unit/test_intent, test_coach, test_autopilot |
| Prompt coach round trip (clean prompt == same edit) for 22 prompts + every FX + every LUT | unit/test_coach |
| Auto edit, smart arrange, hook shot, recording time from file names | unit/test_autopilot, integration/test_e2e_auto |
| Agents (rules + LLM fallbacks), keyword guard, evidence gate | unit/test_agents_mock, test_llm |
| Reviewer, scores, lessons, relevant-lesson retrieval | unit/test_scoring, test_memory_fx |
| LangGraph: node events, parallel planning, checkpoint resume after a crash, resume on server restart, no useless retries | integration/test_workflow |
| SSE live events (order, node timings, replay after reload) | integration/test_workflow |
| AgentRouter (only needed specialists; speech-to-text really skipped) | integration/test_workflow |
| CapabilityManager, /agents, /workflow | integration/test_workflow |
| MCP server (real client, full edit through tools) | integration/test_mcp |
| Voice prompt (TTS → Opus/WebM → /transcribe → planner) | integration/test_voice |
| API end to end (upload → edit → download, 15+ prompts) | integration/test_e2e_api |
| Bad inputs, retries, API key, queue | integration/test_failures |
| Mobile: studio, coach card, live activity panel, chips, voice states | mobile/__tests__ (Jest, `maxWorkers: 25%`) |

The mandatory E2E (new upload → Hinglish → coach → LangGraph → live UI → render → review → playable file) was run
by hand in the browser on the user's own 4K uploads; results in TEST_REPORT.md.
