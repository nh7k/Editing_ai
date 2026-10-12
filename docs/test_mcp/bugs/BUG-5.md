# BUG-5 — a colour ask shortens the video

- **Prompt:** "colour ko cinematic teal orange karo aur vignette lagao" (lab R22, a fresh project).
- **Seen:** 16.3 s of footage → 9.1 s video, 1 cut.
- **Root cause:** the word "cinematic" selected the CINEMATIC genre and the "cinematic" concept → `slow_cinematic`
  pacing (4 s shots, calm music), although it only described the colour.
- **Fix:** `editorial.COLOUR_ADJ` — "colour ko cinematic", "cinematic colour / grade / look / teal…" are taken out
  before genres and concepts are read. "isko cinematic bana do", "wedding ka cinematic video" still choose the genre.
- **Check [RAN]:** `classify` / `concepts_in` on 6 prompts.
