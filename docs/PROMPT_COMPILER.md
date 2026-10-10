# Prompt compiler

Two layers, both instant (no model call):

1. **Coach** (`cutmind/coach.py`, `POST /understand`): rough words → one clean English prompt that means *exactly*
   the same edit, plus the list of what was understood. Shown in the chat as "Samajh gaya 👌", then sent instead of
   the raw text. Round-trip tested for 22+ prompts, every FX, every LUT look, every text style / colour / animation
   (`tests/unit/test_coach.py`): parsing the clean prompt again gives the same Intent.
2. **Editorial spec** (`cutmind/editorial.py`): for vague / creative requests, the ProfessionalEditSpec — explicit /
   inferred-with-reasons / unknown (see EDITORIAL_ENGINE.md). `/understand` returns it too (`spec`); pass `project_id`
   and the cached footage analysis helps classify the video.

## Hard cases the parser handles (each has a regression test)

| You say | It means |
|---|---|
| starting ki 3s me zoom ho, phir zoom out | zoom in 0–3 s, zoom out 3 s → end (NOT a 3-second video) |
| last 5 sec black and white | black & white only for the last 5 s |
| base ki tarah effect, sound beat kare | +6 dB bass, zoom punch on every music beat, music |
| zoom in text / spinning title / neon text style | text animations / presets — the video itself is not zoomed or recoloured |
| uske upar "Riya" likha aaye, ladki ko track karo | label "Riya" follows the tracked person |
| zyada dark ho gaya | brighter |
| captions hata de / transitions bakwas hai | remove them from the current edit |
| no music / music mat daalo | no music (the word "music" no longer adds it) |
| 9:16 reel | aspect ratio, never "9 seconds" |

## The LLM

With `PLANNER_MODE=local`, the in-process Qwen model reads the prompt first; the keyword guard + evidence gate
correct it (explicit keywords win; anything the model adds needs a supporting word). The editorial brain runs after,
on the merged intent.
