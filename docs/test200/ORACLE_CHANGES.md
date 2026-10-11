# test200 — oracle changes (every change to cases.yaml after it was first frozen)

| # | when | cases | change | why (evidence) |
|---|---|---|---|---|
| 1 | 2026-10-11, before Wave 1 (only a 1-case runner smoke run had happened) | the 7 clip-transition cases (crossfade, glitch_transition, iris_circle, slide, whip_pan, wipe, zoom_transition) | `changed at 5.85 s` → `blend_at_cut` (≥ 2 in-between frames between the dark and the bright clip, 4.0-7.5 s) | the old check also passed a plain hard cut: a transition overlap moves the cut earlier, so the frame at 5.85 s is the other clip either way (whip pan smoke run: "changed by 105"). Measured: the hard-cut base video has 0 in-between frames, the whip-pan output has 2 (5.8, 5.9 s). Stricter, not looser. |
