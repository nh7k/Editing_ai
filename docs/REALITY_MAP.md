# REALITY_MAP — what CutMind really does (2026-10-11)

Read-only check. Tags: [RAN] executed · [READ] code only · [CLAIMED] docs/result files only · [BROKEN] ran and failed. Sections 2-3 were gathered by two read-only sub-agents (code reading + read-only Python); their runs are tagged [RAN by sub-agent].

## 1. The "Use this / violet authority / midnight_drift" bug — reproduced

### What really happened in your project (prj_7c02987dd04b) — from the database [RAN]

| time (UTC) | job | prompt | what the director did |
|---|---|---|---|
| 10-10 | job_3e065cb914cb | "jump-cut cover" + **3 variations** button | 3 looks, cyan_kinetic chosen |
| 10-10 10:10 | job_de3590730098 | "beat pulse" | plan style **midnight_drift**, colour preset **bw** |
| 10-11 03:08 | job_2cfeb191e620 | **"purple video ko normal kar do"** | intent = "violet authority look", 3 versions again; Midnight Drift 95.7 % ranked first and became the edit; message: "Changed: nothing visible … Already in your edit: violet authority look"; check `style_applied` FAILED "look 'midnight_drift' … (asked violet_authority)" |
| 10-11 03:31 | job_d9f63c7eabbf | "cyan kinetic look lagao, violet authority hata do" | intent = violet_authority AGAIN, 3 versions, Midnight Drift 91.3 % chosen, same "nothing changed" message |

- The message in your screenshot belongs to the CHAT message "purple video ko normal kar do", not to the "Use this" button. [RAN — job state + logs]
- In both jobs, the variation marked `chosen` is index 0 (Midnight Drift). The backend log of this server run has **no** `POST /jobs/…/choose` request, so "Use this" on Cyan Kinetic either was not pressed in this server run or did not reach the server. Which one: unknown. [RAN — preview log search]

### Reproduced on a fresh test project, live server (deleted afterwards) [RAN]

1. `/edit` "make a 9:16 reel" + variations 3 → 3 versions, all 100 %, cyan_kinetic first; plan style cyan_kinetic.
2. "Use this" on version 3 (`POST /jobs/{id}/choose {"variant":2}`) → 200 OK; the main video file became v2 (md5 equal to `_v2.mp4`), **but the saved plan stayed cyan_kinetic**. [BROKEN]
3. Chat "purple video ko normal kar do" → director job; **3 versions rendered again** (not asked); violet_authority became the edit; plan changed cyan_kinetic → violet_authority; yet the message said **"Changed: nothing visible … Already in your edit: violet authority look"**. [BROKEN]
4. The 3 variations are really different videos: different md5, mean RGB at 3 s (99.9/116.7/140.4 vs 105.1/105.5/141.1 vs 85.2/86.8/103.4) and different frame-border colours (the glow frame). [RAN] They differ only in the look (grade, overlays, caption box, a zoom for 2 of them); the cut is the same. [READ styles.apply_style]

### Where the three names diverge — root causes

1. **"purple" → violet_authority** — `intent.py:1082` `_parse_style`: any "purple" / "violet" in the prompt sets `style = violet_authority`. There is no negation ("violet authority **hata do**" still selects it), no "normal" handling, and the `elif` order means "violet" wins over "cyan" in the same sentence. [READ + RAN: both prompts gave violet]
2. **Chat routing** — `api.py` `/edit`: after a director edit, a chat message goes to the director, not to the new understanding engine; and the engine itself, in the chat, got no plan context, so it saw "purple video" as unexplained and only offered choices (fit_to_duration first, 0.899). [READ + RAN `/tools/resolve`]
3. **"3 variations" never switches off** — `memory.py:80-82` `merge_with_last` copies every remembered intent field the new message did not set, including `variations: 3` and `style`. The edit_memory rows for both later jobs contain `"variations": 3`. So every follow-up chat message renders 3 looks again. [READ + RAN DB]
4. **The asked look can lose** — `agents/director.py:436-486` `_variations` renders the asked style first but ranks all looks by match % only; Midnight Drift (95.7) beat the asked Violet Authority (87.0), so the edit got a look the user did not ask for. Reviewer `style_applied` correctly failed, but the result was still shipped. [READ + RAN]
5. **"Use this" changes only the video file** — `jobs.py:525-545` `choose()` copies `_v{n}.mp4` over the main output and records the choice in memory; it never writes that variation's plan (variation plans are not stored). Timeline, next edits and undo keep the rank-0 plan. [READ + RAN step 2]
6. **The "nothing changed" message is not a comparison with the video** — `versions.py:118-159` `diff()` compares the colour **preset name**, cut, music, effects, text… but not `style`, `overlays` or grade numbers, so a look change counts as "nothing visible". Then `versions.py:175` `_already()` simply re-parses the prompt and claims "Already in your edit: violet authority look" — it never checks the plan. [READ + RAN step 3]

So the three names: **cyan kinetic** = what the user picked (only the mp4 changed); **violet_authority** = what the parser read from "purple" (and from "violet … hata do"); **midnight_drift** = what the ranker shipped because it scored higher.

## 2. Every user path, end to end

How `/edit` decides [READ api.py:1053-1137]: the PhraseBook expands the prompt; the new resolver (`tools/resolve.py`) reads it; the message goes to the resolver → skills (`jobs.submit_tools`) only if (a) the current version was made by the skills and no options are sent, (b) it is a greeting/question, undo, or "aur thoda / kam karo", (c) "yaha" + playhead, (d) a timeline comment, (e) the old parser understood nothing. Everything else goes to the **director** (LangGraph, `intent.py` keywords + memory). The director never calls the skills (`@tool` builders). [READ]
Note: this branch adds (f) "normal karo / pehle jaisa" always goes to the restore skill (see section 5).

Verification differs [READ]: director jobs get the full Reviewer (~30 checks, match %). Skill jobs and manual jobs only get a gate (file decodes, duration, audio present) plus `tools/invariants`. `tier1_checks.py` runs only in tests, never in production.

| Path | Status | Handler → API | Understanding | Real API test |
|---|---|---|---|---|
| Chat (wide screen) | WIRED [READ] | ChatPanel `send` → StudioEditor `startEdit` → `POST /edit` | resolver OR director (rule above) | test_intent_api, test_understanding_e2e [RAN earlier today: 48 passed] |
| Chat (narrow < 1024 px) | PARTLY [READ] | EditorScreen `send` → `/edit` | same | a 422 "choose" shows only error text — choice chips are dropped (EditorScreen.tsx:76-80) |
| Answer-card chips ("captions laga do"…) | WIRED, director jobs only [READ] | → `/edit` | as chat | Jest only |
| "Trim to 15s", "Remove silence" chips | WIRED, narrow only [READ] | fill the input | as chat | test_e2e_api |
| "3 variations" toggle | PARTLY — risky [READ+RAN] | adds `variations: 3` | any options → always director, 3 renders | test_e2e_api three_versions |
| "Use this" on a variation | **BROKEN** [RAN] | `POST /jobs/{id}/choose {variant}` | none | e2e test only checks the file bytes, not the plan |
| ✨ Auto edit / ↕ Arrange clips | WIRED [READ] | `/edit` fixed prompt | director | test_e2e_auto |
| ㏄ Captions button | WIRED [READ] | `/edit` "add captions of what I say" | resolver or director | test_e2e_api (other wording) |
| Text / captions rail | WIRED [READ] | `POST /manual` | manual.py, no AI | test_manual |
| Timeline comment (marker) | WIRED [READ+RAN earlier] | `/edit` with `at` | resolver first, old moment reader fallback | test_intent_api, test_stickers_comments |
| Effects panel "Apply now" | WIRED, some silent no-ops [READ] | `/manual` | none | test_manual |
| Effects panel "Add to prompt" | PARTLY [RAN by sub-agent] | draft → `/edit` | 48/61 transition phrases and 11/23 text-animation phrases mis-parse | Jest only |
| Undo / redo | WIRED [READ] | `/undo`, `/redo` (copy, no render) | n/a | test_nondestructive, test_tier1_api |
| Export (studio) | WIRED [READ] | `GET /output` | n/a | test_nondestructive |
| Export screen re-render | PARTLY [READ] | resends last prompt + options to `/edit` | director re-reads "Manual: …" / chip text instead of re-encoding | Jest only |
| Templates | WIRED [READ] | `/templates/{id}/apply` | director | none at API level |
| Copy an Edit | WIRED [READ] | `/copy-edit/run` | director | none at API level |
| Mic (wide, web) | WIRED [READ] | `/transcribe` → fills the draft | as chat | test_voice |
| Mic (narrow / native) | NOT WIRED [READ] | "Voice input coming soon" | — | none |
| Resolver choice chips | WIRED [READ+RAN earlier] | `/tools` + `/tools/resolve/pick` | resolver | test_intent_api |
| Project Delete button (new today) | WIRED [RAN in browser] | `DELETE /projects/{id}` | — | none automated |

Other findings [READ]: tool-job `explain.summary` is a list but the app renders it as one string (words run together); `?v=jobId` output URLs are served `immutable`, but "Use this" changes the bytes under the same URL, so a browser cache can show the old version; `Style.transition` (crossfade / wipe) is never applied — variations do not differ in transitions.

## 3. Skill reachability (summary — full per-skill table below)

- 109 skill specs, 109 builders, no mismatch. [RAN by sub-agent: `engine.builder_names()` vs specs]
- **Last render:** `skills/tier1_results.json` says PASS for all 109 [CLAIMED — the file merges results across runs, so this is not one clean run]. Older `data/skill_renders.log` (Oct 9) recorded 28 failed motion/effect renders in the separate fx registry; `skills/test_results.json` (Oct 10) says all 184 ok [CLAIMED; conflicting records].
- **Reachability:** no button sends a skill id. Skills are reached only through (a) chat routed to the resolver, (b) resolver choice chips. On a fresh or director-made version, about 4-6 of each skill's 8 examples go to the director instead (column D). [RAN by sub-agent, simulated routing — approximate]
- **Weak chat accuracy on own examples:** blur_background_fill 5/9, speed_ramp 5/9, blur_box_censor 6/9, punch_in 6/9. tilt not in the baseline. [CLAIMED eval file]
- **Unreachable or silent:** `punch`, `punch_static` (fx panel) — blocked in the app and their phrases do not parse; `keyframes`, `camera_move`, `grade` added from the panel render nothing (no params); presets `cinematic` / `sepia` have no button; styles and variations are not reachable on narrow screens (no panel). [READ]
- **Stale lists:** `skills/registry/planned.yaml` still says 17 skills (freeze_frame, stabilize, split_screen, …) are "not available yet" although they work; TEST_REPORT / SKILL_CATALOG still say 105. [READ]
- **Not available by design:** video / image / B-roll generation, frame interpolation, AI upscale (GPU only). [READ agent_registry.py:141-151]
- **Styles** midnight_drift / violet_authority / cyan_kinetic: reachable from the Overlays panel (wide only), the 3-variations toggle and chat keywords. The 3 renders really differ [RAN — md5 and colour]. Ranking can ship a look that was not asked [RAN].

### Full skill table

Columns: **Chat** = resolver top-1 on the skill's own examples [CLAIMED eval/results/per_skill_baseline.json]; **D** = how many of its 8 examples go to the director instead on a fresh/director-made version [RAN by sub-agent, simulated]; **Chips/buttons** = `chip:` a chip text the resolver maps here, `panel:` an Effects-panel card with an equivalent manual engine (NOT this skill's builder) [READ]; **E2E** = real API + FFmpeg tests including it: S/A test_tier1_api, U test_understanding_e2e, I test_intent_api, RS test_restore_style [READ]; every skill also has test_tier1.py (engine + real render, not via the API). **Last render** = skills/tier1_results.json [CLAIMED].

| id | Chat; D | Chips / buttons | E2E | Last render |
|---|---|---|---|---|
| add_music | 19/19; 5 | chip "Mute + calm music" | S,U | PASS |
| aspect_16_9 | 9/9; 5 | - | - | PASS |
| aspect_1_1 | 15/17; 5 | - | S | PASS |
| aspect_4_5 | 9/9; 3 | - | - | PASS |
| aspect_9_16 | 16/19; 5 | chip "9:16 reel with warm color" | S,U | PASS |
| audio_fade | 14/17; 4 | - | S | PASS |
| auto_captions | 19/19; 4 | chip "Add captions", ㏄ button | U | PASS |
| auto_enhance | 9/9; 1 | (Auto edit goes to director) | - | PASS |
| auto_reframe | 7/9; 2 | - | - | PASS (box path only) |
| beat_sync | 8/9; 6 | - | - | PASS |
| blur | 16/18; 5 | panel blur | - | PASS |
| blur_background_fill | **5/9**; 5 | - | - | PASS |
| blur_box_censor | 6/9; 5 | - | - | PASS |
| brighten_to_white | 11/15; 4 | - | U | PASS |
| brightness | 16/17; 5 | - | S | PASS |
| caption_style | 16/17; 6 | Text rail (equiv) | S | PASS |
| cinematic_look | 17/19; 3 | - | - | PASS |
| color_pop | 9/9; 3 | panel color_pop | - | PASS |
| contrast | 17/18; 1 | - | S,U | PASS |
| cool | 17/18; 3 | - | - | PASS |
| countdown_timer | 9/9; 2 | - | S | PASS |
| crop | 7/9; 5 | panel crop | - | PASS |
| crossfade | 18/18; 6 | panel crossfade | S | PASS |
| delete_segment | 15/17; 1 | chip "Remove idle parts" | - | PASS |
| denoise | 18/18; 6 | - | - | PASS |
| duck_music | 13/18; 6 | - | - | PASS |
| echo_reverb | 7/9; 3 | - | S | PASS |
| export_preset | 13/17; 6 | - | S,U | PASS |
| extract_audio | 8/9; 4 | chip "Export GIF & MP3" | - | PASS |
| extract_highlights | 8/9; 3 | - | - | PASS |
| fade_black | 16/18; 4 | chip "Add fade transitions" (ranks saturation first!), panel fade | S | PASS |
| fade_white | 12/17; 6 | panel fadewhite | - | PASS |
| film_grain | 8/9; 6 | panel film_grain | S | PASS |
| fit_to_duration | 15/17; 5 | - | - | PASS |
| flash | 19/19; 5 | panel flash, resolver chip | I,U | PASS |
| freeze_frame | 9/9; 4 | - | - | PASS |
| glitch | 17/17; 5 | panel glitch | S | PASS |
| glitch_transition | 7/9; 5 | panel glitch_cut | - | PASS |
| grayscale | 17/18; 5 | panel mono (equiv) | U,I,A | PASS |
| hook_first | 9/9; 5 | - | - | PASS |
| insert_broll | 9/9; 4 | - | - | PASS |
| intro_outro | 9/9; 4 | - | - | PASS |
| iris_circle | 7/9; 7 | panel circleopen | - | PASS |
| j_cut | 8/9; 2 | - | - | PASS |
| jump_cut_tighten | 9/9; 3 | - | - | PASS |
| karaoke_captions | 9/9; 7 | panel text-anim (equiv) | - | PASS |
| ken_burns | 9/9; 4 | panel zoom (equiv) | - | PASS |
| l_cut | 9/9; 1 | - | - | PASS |
| letterbox | 9/9; 4 | panel letterbox | S | PASS |
| light_leak | 8/9; 4 | - | S | PASS |
| loop_boomerang | 8/9; 3 | - | - | PASS |
| lower_third | 9/9; 4 | - | S | PASS |
| merge_clips | 9/9; 2 | - | A | PASS |
| mirror_effect | 8/9; 4 | panel mirror | - | PASS |
| montage_builder | 9/9; 4 | - | - | PASS |
| mute | 18/18; 5 | chip "Mute + calm music" | U | PASS |
| normalize_loudness | 9/9; 3 | - | - | PASS |
| pan | 9/9; 4 | panel pan_* | S | PASS |
| picture_in_picture | 7/9; 2 | - | - | PASS |
| pixelate_censor | 9/9; 2 | panel pixelate | - | PASS |
| progress_bar | 9/9; 1 | - | S | PASS |
| punch_in | 6/9; 7 | (panel punch blocked) | - | PASS |
| remove_fillers | 9/9; 4 | - | - | PASS |
| remove_silence | 17/18; 6 | chip "Remove silence" | - | PASS |
| reorder_clips | 9/9; 2 | chip "Arrange clips" (director) | - | PASS |
| replace_audio | 9/9; 6 | - | - | PASS |
| restore_normal | 17/20; always resolver (this branch) | - | U,I,RS | PASS |
| reverse | 9/9; 3 | chip "Play backwards" | - | PASS |
| rgb_split | 8/9; 4 | panel rgb_split | S | PASS |
| rotate_flip | 8/9; 5 | chip "Rotate 90° & mirror" | - | PASS |
| saturation | 15/18; 5 | - | S | PASS |
| scene_detect | 8/9; 2 | - | - | PASS |
| sepia | 17/18; 5 | chip "Sepia + vignette" | S,U | PASS |
| sfx_whoosh | 9/9; 4 | - | S | PASS |
| shake | 17/17; 5 | panel shake | S | PASS |
| shape_highlight | 8/9; 3 | - | - | PASS |
| sharpen | 9/9; 2 | chip "Louder + sharpen", panel | - | PASS |
| slide | 8/9; 5 | panel slide* | - | PASS |
| slow_motion | 15/18; 5 | - | U | PASS |
| speed_ramp | **5/9**; 5 | - | - | PASS |
| speed_up | 18/19; 2 | chip "Fast cuts with music" | U | PASS |
| split | 9/9; 6 | - | - | PASS |
| split_screen | 8/9; 1 | - | - | PASS |
| srt_export | 9/9; 5 | - | - | PASS |
| stabilize | 8/10; 3 | panel stabilize | - | PASS |
| sticker_lottie | 9/9; 5 | - | S | PASS |
| teal_orange | 8/9; 5 | panel LUT (equiv) | S | PASS |
| text_glow_neon | 8/9; 6 | - | - | PASS |
| text_overlay | 17/17; 5 | Text rail (equiv) | S | PASS |
| text_pop_in | 9/9; 6 | panel text-anim | - | PASS |
| text_slide | 9/9; 6 | panel text-anim | - | PASS |
| text_typewriter | 8/9; 3 | panel text-anim | - | PASS |
| thumbnail | 9/9; 3 | - | - | PASS |
| tilt | not in baseline; 5 | panel tilt | U | PASS |
| title_card | 14/17; 6 | - | - | PASS |
| trim | 13/17; 1 | chip "Trim to 15s" | A | PASS |
| vhs_retro | 15/17; 5 | panel vhs | - | PASS |
| vignette | 7/9; 5 | chip "Sepia + vignette", panel | S,U | PASS |
| vintage_faded | 15/18; 5 | - | - | PASS |
| voice_clarity | 8/9; 3 | - | - | PASS |
| volume | 16/17; 5 | chip "Louder + sharpen" | S,U | PASS |
| warm | 17/19; 6 | chips "9:16 reel with warm color", travel | U,A | PASS |
| watermark_logo | 18/18; 0 | - | - | PASS |
| whip_pan | 8/9; 7 | panel whip | - | PASS |
| white_screen_card | 11/16; 3 | - | U | PASS |
| wipe | 8/9; 5 | panel wipe | - | PASS |
| zoom_in | 18/19; 6 | panel zoom | S,I | PASS |
| zoom_out | 15/17; 4 | panel zoom_out | - | PASS |
| zoom_transition | 8/9; 7 | panel zoom | - | PASS |

## 4. HANDOFF (paste to another AI)

**CutMind** — prompt-driven video editor. FastAPI + LangGraph backend (`backend/cutmind`), Expo app (`mobile/src`), FFmpeg server-side render. Laptop: 8 GB RAM, no GPU. Rules: free / licence-safe only, no paid APIs, Hinglish users.

**Two editors exist side by side.**
1. **Director** (old, main path): `intent.py` regex keywords → LangGraph agents (cutter, color, audio, effects) → render → Reviewer (~30 checks, match %). It re-thinks the whole edit, merges the new message with the remembered last intent (`memory.merge_with_last`). It never calls the skills.
2. **Skills** (new): 109 YAML specs (`skills/tier1`) + builders (`tools/b_*.py`), chosen by the understanding engine `tools/resolve.py` (exact parse → ranked synonyms → apply / act / choose / undo / non-edit). Skill jobs change exactly one thing on the current plan; verification is only a decode/duration gate plus invariants.

`POST /projects/{id}/edit` (`api.py` ~1053) decides who gets a chat message: skills only when the current version was made by the skills, for greetings/undo/"aur thoda", "yaha" + playhead, timeline comments, restore ("normal karo", new), or when the old parser understands nothing. Otherwise the director.

**What works for real (run today):** skill renders (109 PASS in tier1_results, merged across runs); understanding eval held-out top-3 93.8 %, 0 dead ends; 30-message real-API test; restore / white screen / tilt renders; undo/redo; timeline comments; manual effects panel; project delete button; 3 variations really render 3 different looks; Jest 251/251.

**Only listed, not real:** video / image / B-roll generation, AI upscale, frame interpolation (GPU). Phone Media3 render path: not tested. `planned.yaml` still calls 17 working skills "not available yet".

**Broken (reproduced on the live server):**
- "Use this" on a variation swaps only the mp4; the saved plan stays the first-ranked look, so the timeline, the next edit and undo silently use the wrong look (`jobs.py choose`).
- "3 variations" never switches off: memory carries `variations: 3` into every later chat message (`memory.merge_with_last`), so each message renders 3 looks again (slow, and the ranker may pick a look nobody asked for).
- The ranker ships the highest match %, not the asked look (`director._variations`): asked violet, shipped midnight_drift.
- `intent._parse_style`: any "purple/violet" = violet_authority; negation ("violet hata do") ignored; "violet" beats "cyan" in one sentence.
- The "what changed" message ignores style / overlays / grade numbers (`versions.diff`), and `_already()` claims "Already in your edit: X" by re-parsing the prompt without checking the plan — a false statement.

**The 10 failures a normal user hits first**
1. Picks a variation with "Use this", next edit reverts the look.
2. Any chat message after using "3 variations" renders 3 versions again (minutes).
3. "purple / violet hata do / normal karo" adds the violet look instead of removing it (normal fixed in this branch).
4. Message says "Changed: nothing visible … Already in your edit" while the look did change, or was never there.
5. The asked look is replaced by a higher-scoring one.
6. On a phone-width screen (< 1024 px): no effects/styles/text/sounds panels, no choice chips (422 shows only an error), mic says "coming soon".
7. Right after a director edit, "aur thoda" only offers chips instead of acting.
8. Effects panel "Add to prompt" for most transitions/text animations becomes a plain crossfade/other effect; keyframes/camera_move/grade "Apply now" render nothing.
9. Export-screen re-render re-sends the last prompt to the director (re-interprets "Manual: …" text) instead of re-encoding.
10. Skill-job summaries display as run-together text (list rendered as a string); the browser can cache the old video after "Use this" (immutable URL).

**Top 5 fixes, in order**
1. **"Use this" must switch the plan**: store each variation's plan; `choose()` writes it as the job's plan (and as a new version so undo works); remember the chosen style in edit memory's intent.
2. **Variations are one-time**: never merge `variations` from memory; pin the asked style as rank 0 (rank only the others).
3. **One brain for chat**: route clear single-change messages to the skills even after a director edit (with a map from director plan changes to skills so "aur thoda" works); keep the director for whole new edits. Add negation + "remove/normal" to style parsing.
4. **Honest change report**: `versions.diff` must compare style, overlays and grade numbers; `_already()` must check the plan, not the prompt; run `tier1_checks` (or a light version) on skill jobs in production.
5. **Narrow-screen parity**: render choice chips from 422 details in EditorScreen, add the panels or a "More" sheet, fix tool-job summary rendering, drop `immutable` caching for swapped outputs.

## 5. Code state when this was written

- Read-only check: nothing changed for sections 1-4. One fix written **before** the check started (for the screenshot) is in this branch: "normal karo / pehle jaisa" in the chat now always goes to the restore skill, which also takes off a style's grade numbers, colour wash, graphic tracks and the style name; partial restore moves the whole-video saturation to the other shots. Tests: `tests/integration/test_restore_style.py` 2 passed (real render, colour back, undo exact) [RAN]; intent / understanding / gate / 30-message e2e 48 passed [RAN]. The full regression run had started before this fix, so it does not cover it. [RAN]
- Not fixed: items 1-5 above.
