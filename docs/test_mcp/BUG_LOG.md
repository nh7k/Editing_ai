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
| — | real ronaldo project | "thoda contrast badhao" | 19 min in the final encode (segments took 10 s); the same encode took 54 s on the next edit and 109 s in the lab — cause NOT found (other load on the laptop?) | OPEN (watch) |

Re-run after the fixes [RAN] (`--seq`, 11 prompts in one project): all done; "black and white hata do" keeps warm,
fade 15.7-16.3 s with a black last frame, "10 second ka karo" → 9.7 s, "make it brighter" → "effects tuned:
warm colour (brightness 0 → 0.12)", "flash hata do" removes the flash. Found in that run and fixed: "shake hatao"
with NO shake on the video removed zoom + pulse (the family) — now a named effect that is not there is said and
nothing else is removed; with no shake effect "shake hatao" stabilizes the footage.

## 2026-10-19 (manual test through the public https URL, the full suite, photos)

| # | found by | prompt / test | what went wrong | status |
|---|---|---|---|---|
| BUG-9 | manual MCP test | "original quality me export karo" on an edited video | every effect taken off ("original" read as "like the original") | FIXED |
| BUG-10 | manual MCP test | "flash hata do" with no flash | job failed correctly but said "Maine ye kiya: flash hatao" (MCP + web chat) | FIXED |
| BUG-11 | manual MCP test | "isko normal edit kar do" on a new project | "back to normal" ran with nothing to take off → failed | FIXED |
| BUG-12 | resolver | any ranked reading | the parser's settings were dropped (`params: {}`) → original-quality export became an Instagram export | FIXED |
| BUG-13 | full suite (test_mind_api) | "8 second ka edit, warm color" | read as a fan edit of "8 second": black and white, speed ramps, flashes, "SECOND" on screen | FIXED |
| BUG-14 | photos | "in photos se … edit banao" | the auto edit cut both photos away as idle ("nothing to keep") | FIXED |
| BUG-15 | quality | any export | 1080p/4K and 60 fps sources came out 720p/30 fps from proxies; no original-quality export | FIXED |
| — | full suite | test_tier1 beat_edit / talking_head_reel | beat_edit's check was never written; talking_head ran on silent media | FIXED (tests) |
| — | full suite | voice_clean pipeline, auto_captions variants | failed only under load; pass alone | FLAKY (watch) |
| BUG-16 | full suite (voice_clean / voice_louder) | voice clean-up | FFmpeg 9.0.1's `arnndn` segfaults at random (8 of 20 runs of one command on one file, measured; not our graph — `arnndn` alone does it). Fixed in the app: a crash (not an ffmpeg error) is run again twice; if it keeps crashing the voice is cleaned with `afftdn`. 20 of 20 calls succeed (6 crashes recovered) | FIXED (workaround) |
| BUG-17 | user: "kitna bekar edit" | photo edit v1 | two wide frames repeating, small moves, calm song — v2: 4 framings per photo from the object detector, energy-driven beat cuts, punches | FIXED |
