# BUG-6 — the fade's time in the message was not the real one

- **Prompt:** "end me fade to black karo" (lab R06).
- **Seen:** "(Fade through black: 13.3-16.3s)"; the plan had a 0.59 s fade; frames at 15.6 s fully bright.
- **Root cause:** the message showed the time window read from "end" (last 3 s), not where the skill put the fade
  (the last shot, 0.65 s here).
- **Fix:** `ToolCtx.where` — a skill can say where it really went; `_edge_fades` reports the real fade time and says
  when it is shorter than asked.
- **Check:** unit suite; re-run of the chain (see BUG_LOG).
