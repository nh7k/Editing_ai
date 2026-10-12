# BUG-3 — "shake hatao lekin colour rehne do" changes nothing; "flash hata do" adds a flash

- **Prompts:** "shake hatao lekin colour rehne do" (lab R25, on a velocity edit), "shake hatao", "flash hata do".
- **Seen:** R25 "Nothing changed" (beat_shake still there); "shake hatao" → `stabilize` added; "flash hata do" →
  `flash` applied again.
- **Root cause (3 parts):**
  1. With no time said, the chat context (`context_from_plan(t=None)`) listed only whole-video effects — per-shot
     effects (flash, beat_shake, pulse) were invisible, so "hatao" had nothing to remove and the named skill was ADDED.
  2. `beat_shake` was one word; "shake" did not match it.
  3. "colour rehne do" (= leave the colour) was read as an unknown request → "choose".
- **Fix:** `context_from_plan(t=None)` also lists per-shot effects (one entry per effect, its span); on-screen words
  split on "_"; an effect on the video named by the user's words decides the family and `only`; a KEEP clause
  ("X rehne do", "X mat chhedo", "leave the X") next to a removal is dropped from the request.
- **Check [RAN]:** saved R24 plan: R25 → only beat_shake removed (film_bw, flash, impact, pulse kept); "flash hata do" →
  flash removed; "video stable karo" still → stabilize.
