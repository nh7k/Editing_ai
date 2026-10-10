# Tier 1 review — the 100 seed skills, read critically (2026-10-09)

Written before building, as asked. "Exists" means there is code in CutMind today. It does NOT mean the code is
tested as a Tier 1 skill; that status lives in `docs/TIER1_STATUS.md`, and only a measured render counts.

## 1. Where I disagree with the list (plainly)

1. **About 15 of the 100 are variants of another skill, not separate skills.** For a user they are good separate
   names, and I keep every id so the list you know stays the same. But I build each group as ONE engine with a
   parameter, and the docs say so. Counting them as 100 independent pieces of work would overstate what exists.
   - `aspect_9_16`, `aspect_1_1`, `aspect_16_9`, `aspect_4_5`: one reframe engine, 4 ratios.
   - `fade_black` / `fade_white`; `pixelate_censor` / `blur_box_censor`; `zoom_in` / `zoom_out` / `ken_burns`
     (same keyframed scale, different direction or speed).
   - `grayscale`, `sepia`, `warm`, `cool`, `cinematic_look`, `teal_orange`, `vintage_faded`: one colour engine
     (eq / colour matrix / generated LUT) with 7 presets.
   - `jump_cut_tighten` is `remove_silence` with a shorter gap and a smaller kept padding. `montage_builder` is
     `fit_to_duration` + a short shot length.
2. **`merge_clips` is not a skill a user asks for.** Every edit already joins clips in order. I keep it as an
   explicit op ("sab jod do" = use every clip, in order, hard cuts), because people do say it.
3. **`sticker_lottie` cannot be rendered on the server licence-safely today.** The Python Lottie renderer
   (python-lottie) is AGPL, so it is RED. rlottie (Samsung, MIT) needs a native build that I have not vetted.
   - Server: our own procedural animated stickers (emoji / SVG shapes drawn with FFmpeg, scale / bounce / spin
     keyframes).
   - Phone: Lottie playback with lottie-android (Apache-2.0) as a mapping only, marked NOT TESTED here (no device).
   - The id stays; the YAML says "Lottie = phone-only, server = procedural sticker".
4. **`extract_highlights` and `hook_first` are only as good as the "best moment" score.** Ours is motion +
   loudness + speech + face, with no learned model. Tests can prove "it picked the segment our score rates
   highest", not "a human agrees it is the best". I will say that in the status table rather than pretend.
5. **`auto_reframe` is not a phone feature.** It needs per-frame detection (MediaPipe / OpenCV DNN on the
   server). The phone gets the computed crop path as keyframes (Media3 Crop + MatrixTransformation per frame),
   marked NOT TESTED.
6. **`denoise` licence.** FFmpeg `afftdn` (LGPL, part of FFmpeg) is safe. Our current RNNoise model file
   (`assets/models/rnnoise_sh.rnnn`) is from a community model repo whose licence I have not verified yet. Until
   that is checked it is YELLOW, and `afftdn` is the default.
7. **`volume` vs `normalize_loudness` is a real gap, not just naming.** The previous checkpoint measured that
   "make it louder" (target -11 LUFS) reaches only about -14.6 LUFS: one-pass `loudnorm` undershoots. A
   professional asks for exact dB changes and for a measured LUFS target. Both need a two-pass measure-then-gain
   chain. I am building that here instead of shipping the known failure.

## 2. Missing (what a pro editor or a creator would add)

| proposed | why | cost | decision |
|---|---|---|---|
| `stabilize` | the #1 fix for phone footage | FFmpeg `deshake` (LGPL). `vidstab` is GPL (libvidstab) → never | **add** |
| `crop` | manual crop / punch a region; used under every reframe | trivial | **add** |
| `loop_boomerang` | very common on Reels / Status | `reverse` + concat | **add** |
| `thumbnail` | every YouTube / Reels upload needs a cover | one frame + title | **add** |
| `srt_export` | accessibility and uploads (YouTube accepts .srt) | captions already timed | **add** |
| `color_match` | shots from 2 phones look different; exists inside Color | — | already in the Color agent (exposure matching); not a separate Tier 1 id |
| `voiceover` (record) | phone feature (mic), not an edit op | phone UI | defer (phone) |
| `translate_captions` | Hindi ↔ English subtitles | needs a translation model | defer (heavy) |
| `remove_background` | asked a lot | RVM is GPL, BRIA RMBG is paid → no safe model yet | defer, BLOCKED: needs human decision |

So the build list is **105 = your 100 + 5**.

## 3. Too hard or too heavy for a phone (server-only, with the reason)

| skill | why server-only | phone fallback |
|---|---|---|
| auto_captions, karaoke_captions, remove_fillers, jump_cut_tighten | speech-to-text (Vosk / faster-whisper, 50 MB–1.5 GB models) | server; the phone shows "needs internet" |
| auto_reframe, face pixelate / blur | per-frame detection | crop path computed on the server, applied on the phone as keyframes |
| denoise, voice_clarity, normalize_loudness (2-pass) | FFmpeg audio filters; Media3 has no equivalent | server |
| extract_highlights, hook_first, scene_detect, beat_sync | analysis of the whole clip | server analysis → phone applies the cuts |
| stabilize | two passes over every frame | server |
| glitch, vhs, rgb_split, light_leak, iris and other custom transitions | need custom GlEffect shaders | server now, shader ports later (NOT TESTED) |

## 4. Dependencies

- **Needs speech words (ASR):** captions, karaoke, caption_style (needs captions), remove_fillers,
  jump_cut_tighten, duck_music ("music under speech"), on_words time mode.
- **Needs a voice-activity or silence map:** remove_silence (FFmpeg silencedetect, no model).
- **Needs a face or person path:** auto_reframe, face censor, shape_highlight on a person.
- **Needs music:** beat_sync, at_beats time mode, duck_music.
- **Needs ≥ 2 clips:** j_cut, l_cut, insert_broll, picture_in_picture, split_screen, reorder_clips, merge_clips,
  all transitions.
- **Needs a still image:** ken_burns (works on video too, but it is meant for photos).
- **Changes the duration** (the stability invariant must allow it): trim, delete_segment, fit_to_duration,
  remove_silence, remove_fillers, jump_cut_tighten, extract_highlights, speed_up, slow_motion, speed_ramp,
  freeze_frame, intro_outro, transitions (overlap), loop_boomerang.

## 5. Synonyms

Your seeds are a good start. Some are ambiguous and I will NOT map them blindly:

- "cut" means trim, split and delete all at once. A bare "cut karo" asks one short question; "yahan se kaato" =
  split.
- "chhota karo" is the length (fit / shorter), not text size; "text chhota karo" is the text size.
- "tez karo" can be speed or volume. "awaaz tez" = volume, "video tez" = speed, a bare "tez karo" = speed.
- "saaf karo" means sharpen (picture) or denoise (sound). "awaaz saaf" = denoise, a bare "saaf karo" = sharpen.
- "status" means WhatsApp Status (9:16, ≤ 60 s per status), not a progress bar.

Every Devanagari phrase I write or am unsure about goes to `docs/SYNONYMS_FOR_HUMAN_REVIEW.md`. I am not a
native speaker, and you should read them.

## 6. Order and checkpoints

The work order is as you asked: A cutting → G layout → D colour → C motion → B transitions → H audio → E text →
F stylize → I analysis / delivery. After each category the full suite runs and a CHANGELOG checkpoint is
written. If I run out of room, I stop at a clean checkpoint and write where to continue.
