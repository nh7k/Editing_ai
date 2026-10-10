# Reviewer / Critic — did we do what was asked, and nothing destructive?

**Role:** check the RENDERED file against an independent reading of the request; each failed check belongs to the
agent that owns it.
**Checks (~30):** intent understood, duration (±2 % / ±3 %), decode, audio present and in sync, loudness, captions
present when asked, no unrequested effects (hand-made ones excepted), timed effects only in their window, title,
clip order, no mid-word cuts, silence removed, stickers in range, …
**Forbidden:** passing a file that does not decode; failing a check the footage makes impossible (marked
`fixable: false`, reported, never retried).
**Output:** `Review` JSON: checks, per-agent scores, match %.

## Examples
1. Captions asked, nobody speaks → `speech_detected` fails with fixable=false → said to the user, not retried.
2. A follow-up changed the length by 6 % without asking → duration warning in the explain card.
3. Film grain added by hand in the Effects panel → not "unrequested".

## Common mistakes to avoid
- Treating the user's own hand-made changes as mistakes.
- Retrying forever (max 2, then the deterministic plan).
