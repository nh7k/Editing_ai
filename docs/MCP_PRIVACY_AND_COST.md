# cutmind-mcp — what leaves your machine, and what it costs

## Stays on your laptop

- Your videos, songs, renders, the CutMind database: never uploaded by these tools. Rendering is local FFmpeg.
- The server listens on no port (stdio); its tools have no network access except the local CutMind API
  (`CUTMIND_URL`) — in TEST MODE not even that (in-process).
- Tool logs: `~/CutMind/mcp_logs` — time, correlation id, tool name, argument NAMES, duration, result size. No prompt
  text, no transcript, no file contents.

## Goes to Anthropic (because Claude reads tool results)

Everything a tool RETURNS is sent to Claude as part of the conversation: project / clip names, plan summaries,
skill names, the app's messages, measurements, version lists, and — only if you switch them on — small frames
(`CUTMIND_MCP_FRAMES=1`, at most 480 px wide). Transcript-derived text (captions, notes) is returned only inside
`{"data": …}` and only in short pieces. Turn frames off (the default) if a video is private.

## Cost

The tools themselves are free. Every call adds tokens to your Claude conversation and counts against your Claude
plan's limits. Results are kept compact (lists capped, summaries instead of full plans). The token measurements for
10 typical EDIT MODE edits will be added here after the campaign (NOT MEASURED yet).
