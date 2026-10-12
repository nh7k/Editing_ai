# BUG-1 — "10 second ka karo" fails after an end fade

- **Prompt:** "video ko 10 second ka karo" (ronaldo lab chain: … end fade to black … slow motion … R12)
- **Seen:** job failed — `Fit to a length: that change makes an invalid edit (fade is longer than the segment it applies to)`.
- **Root cause:** `fit_to_duration` shortens every shot (`split_at` → `remove_range`). `split_at` re-fits transitions
  between shots (`_fit_transitions`) but kept the fade-to-black (`after = -2`) as it was; the last shot became shorter
  than the fade and the plan was invalid.
- **Fix:** `tools/timeline.py::_fit_transitions` — a fade in / out is shortened to fit its first / last shot (dropped
  under 0.12 s); fades are left out of the "a split must not change the length" check (a fade never changes the
  length).
- **Check [RAN]:** the saved R11 plan + `fit_to_duration(10)` → 9.89 s, fade 0.24 s, no error.
