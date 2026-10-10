# Reviewer

`backend/cutmind/agents/reviewer.py`. Runs on the **rendered file**, against an independent keyword reading of the
prompt (plus what the editorial brain decided), never against the planner's own output.

| Area | Checks |
|---|---|
| technical | file plays (full decode), audio stream, render matches plan duration, aspect, resolution, frame rate, extras exported |
| instruction | duration / no unrequested trim, captions visible (box colour or letter colour sampled from frames), title, watermark, transitions, colour applied (measured vs source), orientation, reverse, mute, music present, silence removed, fillers, idle removed, timed effects on the right segments, bass boost + beat punches, person tracked, label follows the person, text style applied |
| restraint | no unrequested effects / music / transitions; editorial limits (max transitions) |
| editorial | pacing fits (fast edits), opening shot energetic (hook), closing shot in the top quarter (ending) |
| audio | loudness near the target, true peak |
| words | no cut inside a transcribed word |

Each check has an owner agent and a weight; scores are per agent, 0–100. An agent below `SCORE_THRESHOLD` with a
**fixable** failure is re-run with the failed checks as feedback. Footage limits (nobody speaks, no person found) are
`fixable: false`: reported, never retried, never turned into lessons. The loop stops early when a retry changes
nothing, and never runs more than `MAX_AGENT_RETRIES` rounds.
