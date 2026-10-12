# BUG-2 — "black and white hata do" also removes the warm colour

- **Prompt:** "black and white hata do" on an edit with warm colour + black and white at 2-4 s (lab R05).
- **Seen:** `colour: warm → none`; measured warmth 48 → 23.
- **Root cause:** the resolver narrowed the restore to the colour FAMILY (`what=color`), and `restore_normal` took off
  every colour effect and the whole-video preset.
- **Fix:** new `restore_normal.only` (named skills / words seen on the video). `b_restore._named` matches a plan
  effect by its type and what it does (`versions._fx_name`: a grayscale grade = "black and white"). The resolver passes
  `only` and the time read on the named skill ("2 se 4 sec black and white hata do" → 2-4 s only). "colour hata do"
  (the family word itself) → colour only, not zoom / shake. The chip says what really goes ("Poori video se black
  and white hatao (baaki waisa hi)").
- **Check [RAN]:** on the saved R04 plan: b/w removed, warm kept; "warm colour hata do" → warm grade AND warm preset
  off, b/w kept; "colour hata do" → colour only; "zoom hata do" → zoom only; "2 se 4 sec …" → time 2-4 s.
