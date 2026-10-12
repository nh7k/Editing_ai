# Bug log — MCP campaign

How these are found: prompts sent through `cutmind-mcp` TEST MODE (`run_prompt` only, exactly as typed), the rendered
file measured by the judge's own code (`tools/test200/measure.py`), the plan read directly. Ronaldo lab:
`tools/ronaldo_lab.py` on a COPY of the user's ronaldo clip + song (`~/CutMind/test_fixtures/ronaldo`), 25 prompts
(results `~/CutMind/ronaldo_lab/results.jsonl`). Never the real project.

Status: FIXED = root cause fixed + checked by re-running the prompt; OPEN = found, not fixed.

| # | found by | prompt | what went wrong | status |
|---|---|---|---|---|
| [BUG-1](bugs/BUG-1.md) | ronaldo lab R12 | "video ko 10 second ka karo" (after an end fade) | job FAILED: "invalid edit" (fade longer than the last shot) | FIXED |
| [BUG-2](bugs/BUG-2.md) | ronaldo lab R05 | "black and white hata do" | the warm colour went too (whole colour family removed) | FIXED |
| [BUG-3](bugs/BUG-3.md) | ronaldo lab R25 | "shake hatao lekin colour rehne do" | "Nothing changed"; "shake hatao" = stabilize; "flash hata do" ADDED a flash | FIXED |
| [BUG-4](bugs/BUG-4.md) | ronaldo lab R17 | "make it brighter" | video 23 % brighter, app said "Changed: nothing visible" | FIXED |
| [BUG-5](bugs/BUG-5.md) | ronaldo lab R22 | "colour ko cinematic teal orange karo aur vignette lagao" | video cut from 16.3 s to 9.1 s, nobody asked | FIXED |
| [BUG-6](bugs/BUG-6.md) | ronaldo lab R06 | "end me fade to black karo" | said "13.3-16.3s", the fade was 0.6 s | FIXED |
| [BUG-7](bugs/BUG-7.md) | ronaldo lab R20 (frames) | "make it look like a pro football edit with flash on beats" | IT / LOOK / LIKE / PRO / FOOTBALL as on-screen text; ~40 % of frames washed white | FIXED |
| [BUG-8](bugs/BUG-8.md) | user screenshot | web app on the wrong backend | "Could not load projects — Not Found"; API root showed a bare Not Found | FIXED |
| — | ronaldo lab R11 | "sab effects hata do normal kar do" | slow motion stays (speed is part of the cut, not an effect; the length shown is honest) | OPEN (by design?) |
| — | ronaldo lab R15 | "captions laga do" on a clip with no voice | job "failed" with the honest reason; could offer song-lyric captions | OPEN (minor) |
