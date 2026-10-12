# BUG-4 — "make it brighter" says "nothing visible"

- **Prompt:** "make it brighter" (lab R17, on a vintage look).
- **Seen:** measured luma 112 → 138, message "Changed: nothing visible".
- **Root cause:** the brightness went into the existing whole-video vintage grade (same effect, new param);
  `versions.diff` compared effect NAMES only.
- **Fix:** `versions.diff` — same effects at the same places with other settings → "effects tuned: vintage look
  (brightness 0 → 0.12)".
- **Check [RAN]:** diff of the saved R16 → R17 plans.
