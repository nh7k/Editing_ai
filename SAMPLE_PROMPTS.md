# CutMind — sample prompts

All of these are understood by the deterministic keyword planner (also Hinglish: "gaana daal do",
"thoda garam rang", "khamoshi hata do", "purane zamane wala look", "ulta"); the local LLM planner gets the same
prompts and helps with free-form phrasing. Phrases in **bold** are the keywords the mock parser reacts to.

| Prompt | What the agents do |
|---|---|
| Trim to **15 seconds** | Cutter fits 15 s, every clip represented, cuts snapped between words |
| **Remove silence** | Cutter drops pauses > 0.5 s (and the silent tail of clips) |
| Add **captions** | Analyzer transcribes (faster-whisper), Effects adds violet-box captions in output time |
| Make a **9:16 reel** with **warm** color | 720×1280 crop reframe, warm grade (+ exposure matching across clips) |
| **Fast cuts** with **upbeat music**, 20 seconds | ~1.2 s chunks, music from `backend/assets/music`, ducking under speech |
| Add **fade** transitions | fade-through-black between segments + fade in/out |
| make a 30 sec travel reel, fast cuts, warm color, add captions, remove silence | the full product example |
| **Square 1:1** **black and white** video with **zoom** effect and **title "Goa Trip"** | 720×720, B&W, slow zoom-in, centred title |
| **Cinematic** look, **crossfade** transitions, **1080p** | cinematic curves, dissolves, 1080 short side |
| **Vertical** **short**, **beat sync** cuts, **chill music**, **shake** | beat-snapped chunk lengths, calm track, handheld shake |
| **Highlights** only, **speed ramp**, **blur background** | best-quality clips first, ramp on a non-speech segment, blurred-pad reframe |
| **Clean up the audio**, remove **um**s, **landscape** | highpass + FFT denoise, filler words cut, 16:9 |
| **Reverse order**, **vintage**, **wipe** transitions | clips in reverse upload order, vintage curves, wipe-left |

Prompts that are empty, under 3 characters or over 1000 characters are rejected with
`422 bad_prompt`. Prompts with no recognisable instruction (e.g. "asdf qwerty") still produce a
clean default edit, but the Director logs a warning and loses points for `intent_understood`.


## CapCut-style effects (FX catalogue — `GET /fx` lists all 112)

| Prompt | Result |
|---|---|
| glitch effect, **vhs** look, **teal and orange**, **pixelize transitions**, **karaoke captions** | glitch + VHS, teal & orange LUT, pixelize xfade, word-highlight captions |
| **old film**, **pan left**, **circle** transitions | grain + flicker + vignette, slow pan, circle-open transitions |
| **cyberpunk** with **neon edges** and **kaleidoscope** | cyberpunk LUT, glowing outlines, 4-way mirror |
| **golden hour**, **ghost trail**, **door** transition | warm LUT, motion trails, vertical-open transition |
| thoda **glitch** aur **vhs** daal do | Hinglish works too |
| **typewriter** captions and **moody** look | letter-by-letter captions, moody blue LUT |

## Beginner mode — just say it

| Prompt | Result |
|---|---|
| **mast sa edit kar do** / **make it look amazing** / **badhiya reel bana do** / **edit kar do** | auto edit: the agents pick cuts, music, zoom, colour, captions (if someone speaks), a hook shot first |
| **ulti sidhi footage hai, arrange kar do** / **sort the clips** | clips in the order they were filmed (from file names / metadata) |
| **add captions of what I say** | subtitles of the speech (Hindi shows in Devanagari, English in Latin script) |
| mast sa edit kar do, **no music** | auto edit without music — anything you say yourself wins |
| 🎤 tap the mic in the studio and *say* the prompt | your voice → English prompt (local Whisper), then send |

## Memory

| Prompt | Result |
|---|---|
| **same as before** but add film grain / **pichli baar jaisa** | repeats the last edit's settings, adds the new ones |
| trim to 10 seconds **in my style** / **mera style** | applies the look you keep choosing |
