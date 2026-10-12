# BUG-7 — prompt words as on-screen text; too much white flash

- **Prompt:** "make it look like a pro football edit with flash on beats" (lab R20, a fresh project).
- **Seen (frames):** kinetic text IT / LOOK / LIKE / PRO / FOOTBALL; about 8 of 33 sampled frames almost white.
- **Root cause:** (1) `kinetic_words_from` took "it look like a pro football" as the subject of "make … edit";
  (2) a whole-video flash is a 0.3 s white fade at the start of EVERY shot — 22 shots of ~0.7 s → ~40 % white.
- **Fix:** (1) kind-of-edit words (pro, football, look, like, velocity…) are never a name; no name and text only
  inferred → no kinetic text (said in `unknown`); text asked → "LET'S GO". (2) the per-shot flash is 0.15 s.
- **Check [RAN]:** "make a ronaldo edit" → RONALDO, "virat kohli ka edit bana do" → VIRAT KOHLI, R20 prompt → none.
