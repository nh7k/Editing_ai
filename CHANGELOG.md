# Changelog (commit-style checkpoints)

## 0.1.0 — 2026-10-03

1. **setup** — environment check; installed FFmpeg 9.0.1 and Ollama via winget, pulled `qwen2.5:3b`;
   Python venv + deps; `setup.bat` / `setup.sh`; pinned `numba<0.63` (Smart App Control blocked 0.68 DLLs).
2. **architecture** — `ARCHITECTURE.md`: agents write Edit Plan JSON only, deterministic renderer, REST contract.
3. **backend core** — config from env vars, SQLite schema (projects, clips, jobs, agents, runs, scores,
   lessons, feedback), FFmpeg/ffprobe wrappers with winget auto-discovery.
4. **edit plan** — Pydantic models + cross-field validation + `timeline()` (speed, speed ramps, transition overlaps).
5. **renderer** — per-segment trim/speed/reframe/grade/motion → xfade/acrossfade join → ASS text, music,
   sidechain ducking, voice cleanup, loudnorm. Fix: skip loudnorm on pure digital silence (it emitted NaNs).
6. **analyzer** — ffprobe, PySceneDetect, silencedetect, faster-whisper words, EBU R128, sharpness/motion,
   librosa beats, per-clip cache. Fixes: feed whisper samples instead of a path (PyAV API mismatch);
   treat a video tail without audio as silence.
7. **audio / cutter / color / effects** — rule mode + Ollama decision mode with validated JSON and fallback.
   Cutter never cuts inside a word; budgets transition overlaps; bounded duration correction on retry.
8. **reviewer + scoring** — checklist on the rendered file, weighted per-agent scores, ±points, lessons,
   retry only failing agents (+ dependents), keep best round.
9. **API** — FastAPI routes, uniform error shape, upload limits/type/corrupt checks, async jobs with
   per-agent progress & logs, feedback, scoreboard, temp cleanup. Fix: Ollama client now uses the app's
   settings (was reading globals).
10. **backend tests** — unit, integration (real renders, independent ffprobe/pixel checks), failure tests.
11. **mobile app** — Expo SDK 57 + TS: all screens, typed client, Skia timeline (web via CanvasKit), Jest tests.
12. **mobile ↔ backend run** — fixed Settings crash on the real `/health` shape, nested `<button>` on web,
    progress units (always 0–100), null average score.
13. **ollama quality pass** — first Ollama run: Color agent fell back to rules in 5/9 jobs (qwen2.5:3b copied
    the measured clip brightness 0.5 into the brightness setting) and Effects added transitions nobody asked
    for. Color decisions are now categorical (`lower/unchanged/higher`) mapped to numbers by code; the
    Reviewer now penalises unrequested effects/music.
    Fixes found while checking the e2e numbers: filler words ("Um,") were glued back in by the
    gap-merging step when silence removal was off; "beat sync cuts" now also turns on fast cuts
    (beat sync only changes the length of fast-cut segments).
14. **reviewer blind spot** — second Ollama run passed 12/15: the Director LLM read "1080p" as 720,
    "cinematic" as warm, "vintage" as vivid, and the Reviewer still said 100 % because it graded against
    the LLM's own intent. Reviewer now uses an independent keyword intent; a keyword guard corrects the
    LLM intent and penalises the Director (`llm_intent_correct`).
15. **Ollama removed → in-process Hugging Face model (2026-10-05)** — for production, the LLM now runs
    inside the backend with ONNX Runtime (Qwen2.5-1.5B-Instruct int4, Apache-2.0; 0.5B lite option), no
    separate server. Tried `llama-cpp-python` first: its DLL is blocked by Windows Smart App Control.
    Measured on this PC: 0.5B = 5/10 prompts fully right, 1.5B = 7/10 (13–33 s per call on CPU).
    Added lenient JSON validation, `LLM_AGENTS` (director-only by default), Hinglish keywords in the rule
    parser, optional API-key auth, configurable CORS, model warm-up, `cutmind.prefetch`, Dockerfile +
    docker-compose, PyAV-blocked fallback for faster-whisper.
16. **evidence gate** — first e2e with the 1.5B model: 13/15; failures were LLM "decorations" (1080p,
    black & white, 7–13 transitions nobody asked for). LLM-only fields now need supporting words in the prompt.
17. **auto model + duration bug** — `LLM_REPO=auto` (1.5B with ≥3.5 GB free RAM, else 0.5B). The first auto
    run passed 15/15 but the outputs showed a real bug the tests missed: the 0.5B model read "9:16" as 9 s and
    "1:1" as 1 s (a 1.1 s "square" video). Duration evidence now needs a time unit, the Reviewer has a new
    `no_unrequested_trim` check, and the e2e tests assert that prompts without a length aren't shortened.
18. **user's real footage felt "broken" (2026-10-05)** — nothing failed, but jobs took 3–7 min and a second
    job sat in the queue with no explanation. Cause: a 385 MB 1080p60 MJPEG `.avi` + a laptop with <1 GB free RAM.
    Renderer: drop to 30 fps before scaling, `ultrafast` intermediates, stream-copy join when there are no
    transitions (render of that edit 139 s → 55 s). Jobs now report `queue_position` / `started_at`; the app shows
    "waiting — 1 edit(s) ahead" and an elapsed-time hint.
19. **speed + more FFmpeg operations (2026-10-05)** — edit proxies (720p30 H.264, made at upload; render
    43 s → 22–25 s, analysis 118 s → 45 s on the user's 1080p60 MJPEG clip), whisper `temperature=0` + hallucination
    filters (50–60 s → 6–9 s; dropped "पादे पादे…" garbage on room noise), loudness measurement order bug fixed.
    New operations (feature list inspired by github.com/HariharanElancheliyan/ai-video-editor — no code copied,
    that repo has no license): rotate, flip, reverse playback, fps, gamma, sepia, vignette, sharpen, blur, mute,
    louder/quieter, audio fades, text watermark, idle/frozen-part removal, GIF + MP3 export
    (`/output?format=gif|mp3`). Bug found by the new e2e test: GIF/MP3 weren't copied next to the final output.
20. **studio editor + pro looks** — animated gradient graphic tracks (glow frame / wash / bar), three looks
    (Midnight Drift, Violet Authority, Cyan Kinetic), "edit like a pro" = 3 versions ranked best first with
    choose, filmstrip + waveform endpoints, desktop studio layout in the web app (inspired by a reference
    screenshot from the user; own name, copy and palette).
21. **FX catalogue + memory (2026-10-06)** — research (docs/RESEARCH_open_source_capcut.md): no same-to-same
    open-source CapCut exists (OpenCut is an early rewrite). Built a 112-item catalogue from FFmpeg + our own LUTs
    + libass text animations, Hinglish keywords, `GET /fx`, long-term memory (`GET /projects/{id}/memory`).
    Bugs found: "zoom" transition shadowed the zoom effect (effect silently did nothing) — split tables + a
    visible-change test for every effect; LUT presets crashed the Color agent; "pixelize transitions" and
    "film grain" mis-parsed.
22. **e2e + report** — mock and local-model end-to-end runs, `TEST_REPORT.md`.
23. **web build fix (2026-10-06)** — OneDrive cloud placeholders show up as symlinks to Node, so Metro could not
    find `MediaPanel.tsx` and the other studio components. Rewrote them as plain files; build, typecheck and a live
    browser run pass. One flaky renderer test was seen once (see TEST_REPORT.md).
24. **auto edit + smart arrange + voice prompts + speed (2026-10-06)** — "mast sa edit kar do" lets the Director
    choose the whole edit from the analysis; messy uploads are put in filming order with a hook shot first; the
    studio mic records a spoken prompt and `/transcribe` turns it into English with the local Whisper model.
    Bugs found: "no music" used to ADD music (the word "music" matched); the first auto edit on the user's footage
    took 13 min — 36 cross-fades between 1 s cuts × 3 versions. Now: hard cuts on montages, parallel segment
    rendering, one version by default → 45 s for the same footage.
25. **prompt coach + timed effects + bass (2026-10-06)** — the user's own prompt "starting ki 3s me zoom ho phir zoom
    out, base ki tarah effect" had produced a 3-second video. Now: `/understand` turns desi wording into a clean
    English prompt (shown as "Samajh gaya 👌" in the chat; round-trip tested), effects can be limited to a time window,
    "bass" = +6 dB low end + a zoom punch on every music beat. Also fixed: silent audio tracks broke analysis of the
    user's 4K upload, 20 Mbit/s proxies, "zoom out" also zooming in.
26. **LangGraph + MCP + live events + router (2026-10-06)** — the Director loop is now a checkpointed LangGraph
    workflow (colour in parallel; interrupted jobs resume on server start), 169-role specialist registry with an
    AgentRouter (speech-to-text skipped when unused), CapabilityManager (`/capabilities`), SSE `/jobs/{id}/events`
    feeding a live activity panel, MCP server with 13 tools. Found on the user's footage: useless retries for
    unfixable checks, a global zoom stacked on a timed one, glow masks blurred every frame (14.7 s → 0.2 s), music
    beats recomputed every job, Jest timeouts from too many workers. Hinglish 30 s reel: 243 s → 60 s.
27. **person tracking + text + manual editing (2026-10-06)** — YOLOX-nano (Apache-2.0) person / YuNet (MIT) face
    tracking on CPU, follow-cam / zoom-on-person / spotlight / labels that follow a person; 18 open-source fonts,
    18 text presets, 23 text animations, B&W for part of the video; manual editing (`/manual`, no AI) with a cached
    cut so text-only changes render in ~4 s; Text / Captions / Templates panels and "Apply now" effects in the studio.
28. **editorial brain (2026-10-06)** — research of 15 public repos (docs/RESEARCHED_VIDEO_SKILLS.md), knowledge base of
    31 skills, 21 content types, 5 platforms, Hinglish concepts, taste.yaml, 22 pro templates; ProfessionalEditSpec
    (explicit / inferred-with-reason / unknown), decisions stored in the plan, editorial reviewer checks, conversation
    adjustments ("thoda dark", "captions hata de"), 30 ms audio fades at every cut, benchmark 62 % → 100 %.
29. **fan edits like the reference videos (2026-10-07)** — the user's two reference clips ("make a Max Verstappen
    edit", "snowboarding edit with nice animations"): new `fan_edit` content type and skills `fan_edit_style`,
    `colour_pass` (B&W / negative B&W / silhouette on some beat segments, never two in a row, never first/last),
    `kinetic_words` (the subject's name in big "liquid glass" letters on the beat), `beat_punch`, `music_bed`, and
    `velocity_moves` read off the reference timelines: a STUTTER (one moment 3x, "Triple"), a half-speed TAKEOFF RAMP
    that snaps to 2x, and IMPACT hits (zoom blur + RGB split) on the stutter, the ramp and a few strong cuts — every
    move keeps its beat length. 36 skills, 22 content types, 23 templates. Bug found on the way: the leftover end of
    each clip (and budget-trimmed pieces) pushed every later cut off the beat; pieces are now rounded to whole beats. The app now sends the user's own words (the coach's English summary is shown, not sent, so
    no style words are lost). Manual changes show only the steps that really run in the live panel.
30. **edits that move with YOUR song (2026-10-07)** — upload your own song (or a video's sound) in the new Sounds panel
    (`/projects/{id}/music`); the Audio agent measures it (`cutmind/song.py`: tempo, loudness every 0.5 s, drum density,
    the drop snapped to the beat, slow / medium / fast feel). Song-driven cutting: each cut is whole beats long, short on
    loud parts and long (slow-motion if needed) on quiet parts; the drop always starts a new shot; the strongest footage
    goes to the loudest moments; the song starts later when its drop would fall after the end. Beat punches follow the
    loudness of each part (none on quiet parts, slow drift there); text animations come from a calm / medium / fast set by
    the energy at that moment, vary per edit and never repeat back to back; a word lands on the drop. Sound requests in
    Hinglish ("video ki music hata ke dusra gaana lagao", "voice tej karo, background me music", "music halka"), manual
    `set_audio` (song, levels, original sound on/off, song start). Text BEHIND the person (PP-HumanSeg, Apache-2.0, 6 MB,
    inside YOLOX person boxes; mask cached with the picture). Lyrics as text (faster-whisper "base" on the song, words at
    their sung time, worked out right after upload). Tested on the user's phonk song: 16.3 s edit, drop cut at 10.75 s.
31. **what NOT to do, focus on a person, old-movie B&W, reference edits, learning, noise (2026-10-07)** — the user's
    own sentences, run through the app's agent, found 10 misunderstandings (e.g. "black and white screen mat karo" made
    it black and white; "blue shirt wale pe focus, baaki blur" blurred everything). Now: negations for any effect / look /
    text, text in front of / behind the person (captions too), "starting me bahut zoom" = strong zoom in the first 3 s,
    focus on a person picked by clothes colour (YOLOX + PP-HumanSeg, rest blurred / dimmed), colour pass = old-movie
    B&W (grain, flicker, vignette) instead of negative / silhouette, "edit like this video" (reference style recipe +
    its song), taste learning (Thompson-sampling bandit over 5 knobs, rewards from ratings / next prompt / hand edits),
    RNNoise voice cleanup (+16 dB speech-to-noise), "jahan main nahi bol raha cut karo". Docs: LEARNING_AND_REAL_AGENT.md.
32. **the agent learns your words (2026-10-07)** — a prompt part the rules understand nothing from is no longer silently
    turned into "auto edit": the coach card asks "Ye samajh nahi aaya" with up to 3 guesses (multilingual MiniLM
    embeddings, Apache-2.0, CPU); one tap teaches the phrase (`/phrasebook`) and its Hinglish forms / spellings
    (thoda/thode, aawaz/awaaz) are understood from then on; misses are logged. Measured honestly: guesses are right first
    6/12, top-3 8/12 on held-out Hinglish — so they are asked, never applied alone. The local Qwen2.5-1.5B was tried as a
    fallback interpreter and rejected (10–26 s, wrong on 6/7). Browser-tested: ask → tap "remove noise" → the variant is
    understood without asking.
33. **trained Hinglish translator (2026-10-07)** — tried untrained small models from Hugging Face on 20 Hinglish edit
    requests (Gemma-3-1B 6/20, Qwen3-1.7B 7/20, Qwen2.5-1.5B 1/20); added the user's Hinglish to the rules (20/20, new
    sentences 11/15); generated 8,580 training pairs (`training/make_hinglish_dataset.py`) and a Colab notebook; the user
    trained Qwen2.5-1.5B on a free T4. Trained model: 12/15 alone and 15/15 together with the rules on sentences it never
    saw, 4.3 s each on CPU. It only fills gaps the rules leave and its answer must consist of taught sentences.

34. **noob-prompt test on the Ronaldo footage (2026-10-07)** — 8 beginner Hinglish prompts ("bhai mast sa bana do",
    "video boring hai kuch karo", "blue wale player pe focus karo baaki blur", …) sent to the app agent and checked:
    8/8 pass, review 100% each, every one shows a professional "Pro editor brief". Fixed on the way: "emotional / yaadgaar"
    gave upbeat music (now calm); "end me slow motion" slowed the whole video (now only the last shot); slow motion
    doubled the length; a reference video's soundtrack became the default song; travel "4 s shots" were not cut (now
    ~4 s shots, best ~30 s); the reviewer failed that chosen length as "unrequested trim"; a 0.43 s sliver between
    4 s shots; xfade after a hard cut failed on mismatched timebases (`settb=AVTB`); ffmpeg errors kept only the last line.
35. **watch the agent edit · Copy an Edit · Templates · a conversation of changes (2026-10-07)** — while an edit runs
    the app shows the agents' thoughts one by one and a timeline that fills up (video shots with pictures, text, FX,
    music, colour), like invideo's AI editor (`live.py`, SSE `thought` / `timeline` events, `GET …/clips/{id}/frame`).
    **Copy an Edit** (separate screen): upload a reel you like; the agent watches it shot by shot (`blueprint.py`:
    cuts, B&W, flashes, zooms by optical flow, on-screen text by RapidOCR — Apache-2.0, CPU — and its soundtrack) and
    rebuilds the same edit from your clips: same shot lengths in the same order, effects and texts at the same moments.
    It can be saved as **My template**. **Templates** tab: 17 ready-made edits (`templates.yaml`) + yours.
    Follow-up messages now change the current edit instead of starting over ("thoda slow karo", "text bhi daal do
    'RONALDO'", "black and white hata do, warm karo", "pichla wala dobara"): tested 7/7 in a row. Fixed on the way:
    "trailer" added a Ghost Trail effect; "some shots black and white" made the whole video B&W; a colour after
    "X hata do" was ignored; "thoda slow" changed nothing in beat-cut edits; follow-ups invented crossfades that
    shortened the edit; a film-grain edit was 234 MB (bitrate now capped: 6 Mbit/s at 720p); the reference / liked
    video's soundtrack was used by unrelated edits.
36. **camera moves copied, sound complaints understood, live edit in the main timeline (2026-10-07)** — Copy an Edit
    now measures each shot's camera move in the liked video (`camera_move.py`: tracked corners → similarity
    transform per frame → path of zoom / slide / roll + shake; thresholds after ReelMimic, MIT) and replays it on the
    user's shot (rotate → zoompan, never showing an edge; crash zooms capped at 1.6x). Round trip on a test clip:
    zoom 1.30 → 1.29, slide 0.10 → 0.097, roll 0.06 → 0.061; on the liked reel the copy's push-in measured 1.36 vs
    1.31. The old "zoom in" effect drifted 5 % towards a corner (per-frame scale + crop keeps the first frame size):
    now zoompan, centred. "Audio sunai nahi de raha / pehle jaisa audio la do" was not understood — the translator
    turned it into "Mute the original sound"; now the rules read it as a complaint: unmute, normal level, and if the
    clips have no sound of their own, the song of the earlier edit comes back (the user's clip has no audio track; a
    caption-chip edit had dropped the song). Destructive translator output (mute / remove / no) is only accepted when
    the user's words take something away. The translator loads at server start (its first use took ~13 s and the
    app gave up after 15 s; edit requests now wait 90 s). While an edit runs, the studio's bottom timeline fills up
    shot by shot (thumbnails, text, FX lanes, music, a build cursor) and the agents' thoughts stream into the chat.
    Repos checked: Microsoft kernel-memory / Memora / typeagent (need OpenAI/Azure keys or archived C# — not used),
    HeyGen HyperFrames (Apache-2.0, needs Node + Chrome — optional later), Drift NLE (GPL desktop app — not used).

37. **the agent does what you type — tested by talking to it (2026-10-07)** — a message the rules understand
    nothing from is no longer turned into a silent "default clean edit": the app says "Ye samajh nahi aaya … Edit
    nahi kiya" with suggestions. New everyday phrasings, found with a 73-message Hinglish test
    (`tests/unit/test_noob_messages.py`): "video me awaaz hi nahi hai", "gaane ki awaaz kam karo", "gaana hata do"
    (also removes the remembered song), "thoda chhota / lamba karo" (× the current length), "text bada karo",
    "boring part kaat do", "best part pehle dikhao", "instagram ke liye" (9:16), "1080p me". "rang tez karo" was
    read as fast cuts (now stronger colours; "gaana / awaaz tez" = louder). A real 12-message chat on the user's
    project, checked on the rendered files (length, saturation, LUFS, titles): 11/12 — "text bada karo" changed
    nothing because the title was already the biggest size; the agent now says so.
38. **the chat answers, quickly (2026-10-08)** — the user's message now shows in the chat at once ("Agent aapki baat
    samajh raha hai…"); the chat scrolls to the newest message; the "remembers" card starts folded; a finished
    edit answers in plain words ("✅ Ho gaya · 0:11 • warm color", or "⚠ … Captions nahi bane — is video me koi
    bolta nahi") with the step log folded; "samajh nahi aaya" appears as the agent's answer in the chat. Speed: the
    rules' ~2000 regexes were recompiled on every message (Python caches 512) → 1 ms per parse instead of ~250;
    person cut-outs (text behind people) are cached per cut geometry, not per colour (a colour change was 55-77 s,
    now ~13 s); example sentences for suggestions are embedded once (5-22 s → 0.2 s); the translator runs in the
    background with a 3 s wait (on this RAM-tight laptop one translation took 5-20 s) and loads at start. Bugs:
    "color wapas lao" added black-and-white shots (a colour-reveal pattern) — now restores the original colours;
    "audio wapas lao" was repeated by every later message from memory.
39. **tested as a noob user in the app (2026-10-08)** — raw trip clips (church drone, sailboat, dragonfly; no
    sound) in a new project, then a chat typed like someone who can't edit. Found and fixed: "accha sa bana do insta
    pe" cut calm drone footage every 0.5 s and ping-ponged between places (60 cuts) — the autopilot now tells
    action footage (many scene changes, or "josh / fan edit / sports" words) from scenic footage, which gets ~2.5 s
    shots, each place together, calm music, a 20 s reel; the "best shot first" move left 0.5 s scraps; the opening
    title was small (now 150 px with outline + shadow); new asks: "start me Goa Trip likh do", "last me The End likh
    do" (also inside "end me slow motion aur last me …"), "zoom thoda kam karo", "music thoda kam karo" (same song),
    "thoda smooth karo", "pehla / last clip hata do"; the translator turned "boat wala part zyada dikhao" into
    "Boost the voice" — its answer must now be about something the user's words mention (held-out Hinglish still
    15/15); asking about things IN the picture gets an honest answer + "clip number se bolo". The 8-message chat:
    every message did what was asked, except "boat wala part" (not supported, now says so).
40. **the pro brief tells the truth (2026-10-08)** — checked what the chat's "Pro editor brief" says for noob
    messages: for a new edit it promised "1 s beat cuts, upbeat music" while the agents (seeing calm footage) made
    2.5 s shots with calm music; for a follow-up ("gaana thoda shaant wala lagao") it described a whole new edit
    although only the song changes; "last wala video nikal do" had an empty brief and "The End" was missing. Now:
    a new edit's brief runs the same footage-aware autopilot the agents run; a follow-up's brief reads "Change to
    your current edit: … Everything else stays as it is."; clip removal, closing text, colour back, bigger text,
    shorter / longer, no music are in the brief. "accha sa bana do" / "full josh wala edit" on a project that has an
    edit start a NEW edit (the agents decide again) instead of being merged as a small change.
41. **checkpoint: non-destructive follow-ups, versions, the 2-second playback stop (2026-10-08)** — see TEST_REPORT.md.
    Follow-ups are patches of the current edit by default (a long message or "make it a reel" started over and
    dropped the song); hand-made changes are replayed on every follow-up; versions with undo / redo / restore /
    compare (no re-render) and the ↶ ↷ buttons; explain-back after every edit with a ±2 % duration warning; an
    inaudible noise floor so silent edits play in Chrome (they stopped at 2.3 s); "player nahi chal raha" gets a
    player answer instead of "samajh nahi aaya"; the studio timeline shows raw footage → animated cut → effects one
    by one → render ✓ per shot → review sweep, with a ticker of what the agent is doing (`render_step` events).
42. **vlog stickers, timeline comments, Hindi speech, lyric poster (2026-10-08)** — said things pop up as emoji
    stickers; a comment at a second of the timeline edits only that moment (effect / text / sticker / cut / restyle
    the text there); Hindi speech read by the 45 MB Vosk model (whisper looped on a real podcast) and romanised to
    Hinglish; "Lyric Poster" template; fixes: the video stopping halfway after an effect (the output URL served the
    latest file under an old version id), the play button out of sync with the player, true peaks above 0 dBFS.
43. **checkpoint: provider-agnostic planner LLM (2026-10-08)** — `llm_provider.py` (LLMProvider: llamacpp
    in-process / llamaserver HTTP / rules / mock; bounded queue, per-request deadline that stops generation, token
    cap, warm-up of the system prompt, health stats), `llm_router.py` (rules → small model → big model →
    translator → "samajh nahi aaya"; rejects answers that contradict a negation or remove what was not removed),
    `commands.yaml` (67 commands the model may choose, each parsed by the rules), `prenormalize.py` (Devanagari →
    Hinglish, typo fixes, coverage → half-understood clauses go to the model), GGUF download script with SHA-256,
    `models.json`, eval harness (`eval/cases.yaml`, 67 cases; `eval/run_eval.py`), `scripts/bench_llm.py`,
    `recipes.yaml` (26 numeric style recipes + JSON schema), `/prompts`, API: `GET /projects/{id}/explain`,
    `POST /reference-style`, `GET|DELETE /taste`, `GET /llm/health`, per-client edit rate limit; the chat card shows
    what was understood, next-tweak chips and a 👍/👎 row; docker-compose with llama-server. No Ollama anywhere.
44. **checkpoint: skill library (2026-10-09)** — `skills/registry/*.yaml` (220 skills, JSON-schema validated:
    Tier 1 = 40, Tier 2 = 52, Tier 3 = 93 built + 34 planned + 1 blocked), `skill_registry.py` (synonym matcher,
    negation, `understand`, `covers`, `named_later`), `skill_apply.py` (typed skill calls → Intent patch, time
    windows, refusals), `engines/motion.py` (8 easings incl. spring / bounce as Python + FFmpeg expressions, motion
    presets, new "keyframes" effect), `engines/stack.py` (effect order + merge + conflicts, notes in the explain
    card), `prompt_enhancer.py` (Desi → Pro brief with listed assumptions; asks we cannot do are named as "not
    available yet" with 3 suggestions), API `GET /skills`, `POST /projects/{id}/skills`, `POST /enhance`.
    Tests: `tests/unit/test_skill_library.py`, `tests/integration/test_skill_renders.py` (150 real renders),
    `tests/integration/test_skill_pipeline.py` (35 skills through the whole workflow), `eval/skill_prompts.yaml`
    (320 held-out prompts) + `eval/run_skill_eval.py`, `eval/perf_probe.py`. Tools: `skills/tools/update_status.py`,
    `write_catalog_doc.py` (→ docs/SKILL_CATALOG.md). Fixes found by these tests: zoom / pan / drift / camera moves
    crashed (UnboundLocalError from my own easing change — fixed the same day); spring / elastic easings broken (the
    "P" in "PI" was substituted); speed_ramp skill default was a no-op (1.0 → 2.0); the Reviewer failed muted edits
    ("-99 LUFS") and "best part pehle" / "reverse the video" edits (clip order); final limiter 0.85 → 0.79 (a loud
    voice+music mix decoded at 0.0 dBFS); "4k upscale" quietly became a 1080p auto edit; the catalog generator
    would have emptied its own files on a re-run; registry-named clauses no longer go to the planner LLM
    (55 % → 21.6 % of held-out prompts). Open: "make it louder" reaches ~-14.6 LUFS, not the -11 target (one-pass
    loudnorm); see TEST_REPORT.md checkpoint 3.
45. **Tier 1 checkpoint A + G (cutting, layout) (2026-10-09)** — tool engine `backend/cutmind/tools/` (spec loader +
    `skills/tier1.schema.json`, `engine.run`: params → time window → builder → invariants → stack → explain-back with
    assumed defaults and adjust options; atomic), `timeline.py` (split / isolate / remove / keep / remap — every index and
    every timed item follows), `timewin.py` (whole, segment, between_times, intermittent — "beech beech me" = 1 s every
    4 s, said back —, at_time, at_beats, on_words, on_scene_change), `parse.py` (token matcher with Hindi verb stems,
    spelling variants, gaps, negation, quoted text kept as typed, magnitude / direction words, ~30 extractors),
    `generated.py` (title cards, whoosh), plan fields: `graphics` track (layers / censor / shapes / progress / light
    leak / logo), `audio_edits` (J / L cuts), `hold` (freeze), 4:5, effect `params`. 27 skills. **Renderer bugs found
    and fixed:** every hard cut had a 21-50 ms silent gap (AAC priming + input `-t`) — intermediates are now PCM and
    trimmed exactly; the finish pass made a 3 s jump in the sound at cuts (loudnorm + mixed A/V scheduling) — the sound
    is now its own pass; an extra `-i` input that ends early stalled FFmpeg 9 for good — B-roll / pieces / effects are
    read with movie= / amovie=; `amovie` seeks gave broken timestamps — pieces are pre-extracted.
46. **Tier 1 checkpoint D (colour)** — one parametric `grade` effect per shot (eq + colour temperature + a look LUT
    at a strength: `luts.ensure_look`), merged per shot by the stack resolver; auto enhance from measured exposure;
    colour pop with any colour. 16 skills. Test media `soft` (camera-like) — testsrc2's pure primaries cannot show a
    saturation / look change.
47. **Tier 1 checkpoint C (motion / time)** — keyframed moves with easings, punch at instants, Ken Burns, pan, shake,
    speed / slow / ramp (timed items rescaled), reverse (≤ 10 s pieces, whole = last shot first), freeze frame
    (silent hold). 11 skills.
48. **Tier 1 checkpoint B (transitions)** — 9 transitions; whip pan = slide + horizontal motion blur over the overlap
    + a whoosh; glitch transition = pixelize + RGB tear; transitions keep captions inside their shots (remap). Found:
    the generated whoosh was ~-41 dB (inaudible) — now normalised; `apad,atrim` after `adelay` silenced the whole
    effect track — `apad=whole_dur` instead.
49. **Tier 1 checkpoint H (audio)** — exact dB volume (measured 2-pass correction), LUFS target, mute / volume
    ranges, ducking, afftdn + a gate set from the clip's measured noise floor (pink-noise gaps -40.6 → -68.9 dB),
    speech EQ, echo, beat sync (cuts moved onto beats), whoosh, replace audio, mp3 / wav / m4a export. 13 skills.
50. **Tier 1 checkpoint E (text / captions)** — captions, karaoke (separate highlight colour — before, every word was
    the highlight colour), caption / text restyle, title card, lower third, text animations, neon (near-white core +
    coloured tube — a coloured fill vanished on colourful video), logo watermark, progress bar. **Devanagari:** the
    typewriter / wave / cascade animations split text by code point and broke conjuncts and matras — they now split
    by akshara (`renderer.letters`); checked by eye on saved frames. 12 skills.
51. **Tier 1 checkpoint F (stylize / overlays)** — glitch, VHS, RGB split, flash at instants, light leak, mirror
    (h / v / four-way), pixelate / blur censor boxes (a face box from tracking), highlight shapes, emoji stickers,
    countdown. Found: pixelating in yuv420p lost the colour (yellow came out white) — done in RGB now. 11 skills.
52. **Tier 1 checkpoint I + added (delivery)** — scene detection, platform export presets (specs checked
    2026-10-09), stabilise (deshake — vid.stab is GPL), boomerang, thumbnail, .srt. 6 skills.
53. **Tier 1 API + tests** — `GET /tools`, `POST /tools/parse`, `POST /projects/{id}/tools` (calls or a prompt; a
    new version; a refusal says "not available yet" + the 3 closest skills); `tests/unit/test_tier1_engine.py`,
    `tests/integration/test_tier1.py` (every skill rendered and measured), `test_tier1_api.py` (versions, undo,
    rollback, 30 edits in a row), `eval/run_tier1_lang.py` (840 YAML examples + a held-out set), docs
    `TIER1_REVIEW.md`, `TIER1_STATUS.md`, `SYNONYMS_FOR_HUMAN_REVIEW.md`, `CATALOG_REVIEW.md`, `COVERAGE_MATRIX.md`
    (FFmpeg filters part), LICENSES (Tier 1 table; `eq` and `boxblur` are GPL-only FFmpeg filters — server only).
54. **Tier 1 fixes from the combined runs** — (a) a cut next to a transition no longer shortens the transition (that
    made the video LONGER; found by the 30-edit run at "glitch 5 se 6 sec"): `split_at` refuses, `isolate` widens
    the window to the nearest cut, the length never changes. (b) Light leak: FFmpeg `gradients` used a random seed
    (the test passed alone, failed in the full run) and the screen blend ran in YUV (cooler, darker); now a fixed
    corner position, a pinned seed everywhere `gradients` is used, and the blend in RGB. (c) `eval/perf_probe.py`
    reported 0 MB for Python (the 64-bit process handle was truncated); fixed.
55. **Long videos could never export** — every FFmpeg step had a flat 15-minute limit, so a 20-minute 1080p edit
    (about an hour of encoding on this laptop) was always killed (found by `eval/perf_probe.py 20`). Now there
    is no fixed limit; FFmpeg is stopped only when it prints no progress for 5 minutes (a hung graph). The
    decode check's limit grows with the video's length. Catalog: `tests/integration/test_catalog_variants.py`
    (each variant rendered and compared with its siblings) and `catalog/build_catalog.py` (catalog.jsonl / csv,
    docs/SKILL_CATALOG.md).
56. **Ducking depth was not what was asked** (found by the catalog difference test: "duck 6 / 12 / 20 dB" sounded
    almost the same). The sidechain's depth followed the speaker's loudness (3-18 dB measured). Now the sidechain is
    gated, boosted and limited to a fixed level, so the music drops by the asked dB at any voice level (6 / 12 /
    20 asked → 6.2 / 12.2 / 20.2 measured at -29, -23 and -13 dBFS speech; `tests/integration/test_ducking_depth.py`).
    The default (12 dB) is now really 12 dB. Catalog: 105 bases + the variants that passed the difference test
    (docs/SKILL_CATALOG.md); the test also found its own measuring limits (small text, 0.4 s slide-ins) — fixed.
57. **Old render tests `strobe` / `echo`** failed in the full regression after the exact-trim timing change: their
    sample frames fell between strobe flashes and the clip part used barely moves (echo blends motion). The
    effects were fine; the test now puts them on the moving shot and checks a frame every 0.04 s (150/150).
58. **Intent: never a dead end** (docs/INTENT_FAILURE_REVIEW.md, docs/INTENT_EVAL.md) — "yaha screen white kar do
    nomal jasia tha" at a marker got "samajh nahi aaya" + a fixed unrelated list; in the chat the same words
    started an automatic re-edit. Root causes: the old `nearest()` let filler words ("kar") tie with meaning words;
    no spelling variants / phonetic key; no restore skill; the comment path never tried the Tier 1 skills. Now:
    `tools/fuzzy.py` + `tools/resolve.py` (exact matcher first, weighted token scorer, marker / playhead and the
    effects on screen as context, apply / up to 3 chips), skills restore_normal, brighten_to_white,
    white_screen_card, chips in the app, local unmet-request log + review script. Held-out top-1 71.8 → 85.9 %,
    top-3 75.3 → 91.8 %, silent wrong edits 8 → 3; previous eval unchanged.
59. **The chat no longer waits 20-40 s on unusual words** — `/understand` waited for the local planner LLM
    (21-28 s per phrase on this CPU) and, after a restart, for the phrase-embedding model (~32 s). Now a message
    shares one 2 s model budget (`CUTMIND_LLM_WAIT`), the model keeps working in the background and its answer is
    cached; requests never wait for the embedding model to load. Measured after warm-up: ~2 s (was 21-28 s).
    "yaha …" in the chat now means the player's position.
