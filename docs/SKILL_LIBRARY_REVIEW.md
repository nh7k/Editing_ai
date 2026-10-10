# Skill library — design review before building (2026-10-09)

Sources: my own knowledge (to mid-2026), tests run on this machine today, and a licence audit done from the repos'
own pages (section 6; filled from the audit, each row says how it was verified). Where I disagree with the brief I
say so.

## 1. Where I disagree with the plan
1. **"150+ skills" is the wrong target; "the 40 things creators actually ask for, done right" is the right one.**
   Many items in the brief are the same skill with different words or parameters (Ken Burns = slow zoom + pan;
   punch-in = zoom with a short window; "bounce loop" = loop + reverse). Counting them separately inflates the
   number and splits the tests. I still build a registry of 150+ entries — but entries are honest: a synonym family
   is ONE skill with parameters, and every entry has a status (`tested`, `untested`, `planned`, `blocked`).
2. **We already have most of the engine.** CutMind ships 17 motion effects, 33 video effects, 58 transitions, 10
   generated LUT looks + 8 colour presets, 23 text animations, 22 text styles, captions, ducking, loudness, silence
   / filler removal, beat cuts, reframing, stickers and timeline comments — all rendered by FFmpeg and tested. The
   registry wraps these (synonyms, parameters, time modes, stacking order, tests) instead of rewriting them. A
   rewrite would throw away tested code for no user-visible gain.
3. **Media3 mappings cannot be verified here.** There is no Android device / emulator in this session. Every
   `media3` field is a design mapping (Media3 effect class + parameters) marked NOT TESTED. Custom GLSL ports
   (gl-transitions) are only worth doing after the Android renderer exists; until then the server renders them with
   xfade equivalents.
4. **The show-back "pro prompt" step must not add a click to every edit.** Founders love it, noob users skip it.
   Default: show the pro brief as chips WITH the result (already in the chat card); ask before rendering only when
   the brief changes the whole edit or the confidence is low.
5. **Do not ship FFmpeg's GPL build anywhere near the APK.** Measured here: our FFmpeg is
   `--enable-gpl --enable-version3 --enable-libx264` (GPLv3). Server-side as a separate process that we never
   distribute is fine; shipping it inside an app would force GPLv3 on the app. Android uses Media3 + MediaCodec.
6. **"Optional tiny LLM when rules are unsure" — keep it, but it is the weakest link.** Measured yesterday: Qwen3-0.6B
   once turned "gaane ki awaaz thodi dheemi" into "podcast clip" and rebuilt a user's edit; guards now block that.
   Every new skill must be reachable by the rules (synonyms) first; the model only picks among registry skills.
7. **Some brief items are risky for a family/creator app or simply heavy:** skin smoothing (beauty filters are a
   policy/ethics topic and need face parsing), face-tracked text on 4K (slow on CPU), stem separation and matting
   (models are 100–300 MB, minutes per minute of video on CPU). These are Tier 3, off by default.

## 2. What would break in real use (and what the design does about it)
| Risk | Evidence / reasoning | Design answer |
|---|---|---|
| Effect stacking order (colour after text recolours captions; blur after text blurs them; speed after a beat-timed effect moves it) | the renderer applies filters in a fixed per-segment order; a free-form list would not | `engines/stack.py`: fixed stages (geometry → time → colour → look → effects → overlays → text → audio), conflict rules, merge of duplicates |
| Two skills on the same moment (zoom + zoom, mono + color_pop) | seen: a timeline-comment zoom over a whole-video zoom changed nothing | resolver merges same-type effects (strongest wins) and rejects contradictions with a clear error |
| Long / 4K videos | person masks and per-frame effects are per-pixel; on this laptop a 33 s 720p edit with masks took ~2.5 min | proxy preview (360p) for every edit; 1080p final only on export; heavy skills flagged `cost: heavy` |
| Hindi text | tested today: Hind / Kalam render conjuncts (क्ष, त्र, श्रृं, द्व) correctly through libass + HarfBuzz; Latin-only fonts fall back via fontconfig | Devanagari text gets a Devanagari font automatically; tests check glyph shaping on real renders |
| Emoji inside captions | tested today: 🔥 in an ASS caption rendered as a monochrome outline and widened the box | emoji are rendered as image stickers (colour), never inside ASS text |
| Mobile limits | MediaCodec has per-device limits (resolution, concurrent codecs); GLSL effects cost battery | phone renders preview + simple stacks; heavy stacks render on the server |
| Licence drift | repos change licence; per-shader licences in gl-transitions differ | LICENSES.md row per asset with the URL checked and the date; CI test fails if a skill uses an asset without a row |

## 3. Better or additional open-source choices (my suggestions)
- **Word timestamps:** faster-whisper (MIT) already gives word times; stable-ts (MIT) only if needed —
  whisper-timestamped is AGPL (see section 6) and must not be used.
- **Hindi ASR:** the Vosk Hindi model (Apache-2.0 per its list) already works better than whisper base on real
  Hindi; AI4Bharat IndicConformer is the upgrade path.
- **Server-side Lottie:** rlottie (C++) rather than python-lottie (AGPL — see audit); on Android, lottie-android.
- **Transliteration:** our own rule-based Devanagari → Hinglish (0 MB, tested) first; IndicXlit only if its
  licence and the CT2 build's licence both check out.
- **Colour:** generate LUTs ourselves (we already do, `luts.py`); colour-science (BSD-3) for accurate transforms
  if needed.

## 4. Architecture I am building
```
user text ─► prompt-enhancer (normalize → concept map via registry synonyms → pro brief with assumptions)
          ─► skill matcher (rules; tiny LLM picks among registry ids only when unsure)
          ─► resolver (params + time mode → plan patch; stacking order; conflicts) ─► Edit Plan version
          ─► FFmpeg worker (proxy preview / final)  |  Media3 on the phone (mapping, NOT TESTED here)
```
Skills live in `skills/registry/*.yaml` (schema `skills/skill.schema.json`), one file per skill family.

## 5. What I will NOT claim
No Media3 / Android result, no GLSL shader result, no 20-minute 4K timing unless it was actually run. Each is listed
as NOT TESTED with the reason in TEST_REPORT.md.

## 6. Licence audit summary (verified 2026-10-09 from each repo / model card / PyPI / ffmpeg.org — full table in LICENSES.md)
- **GREEN (39 checked items):** MIT / BSD / Apache / ISC / OFL — cut-as-code, video-use, OpenCut, open-edit,
  MoneyPrinterTurbo, MoviePy, gl-transitions (all 125 shaders MIT except 2 BSD), revideo, motion-canvas,
  lottie-android, stable-ts, whisperX, colour-science, OpenColorIO, rnnoise, DeepFilterNet, demucs (adefossez fork),
  librosa, pyloudnorm, silero-vad, Real-ESRGAN, RIFE, IndicXlit, IndicTrans2, Noto fonts, Media3.
- **YELLOW:** FFmpeg (our build is GPLv3 → server-only), rlottie (ship attributions), rembg (only with MIT/Apache
  models, never its default BRIA model), FunClip (models), whisperX diarization (gated models), MediaPipe model cards.
- **RED (never in the product):** whisper-timestamped (AGPL), python-lottie (AGPL), Video2X (AGPL), glaxnimate,
  RobustVideoMatting, devhyper/open-video-editor, OpenVINO Audacity plugin (GPL-3.0), facebookresearch/denoiser
  (CC-BY-NC — **correction to the brief: there is no commercial option**), madmom models (CC-BY-NC-SA), Remotion
  (company licence that also forbids selling a derivative editor), BRIA RMBG models.
- **BLOCKED (needs your decision):** PyPI `color-fx` and `dhvani` (brand-new single-maintainer packages — not
  installed; we write the needed functions ourselves), HF `Singla0009/all-indic-transliteration` (new anonymous
  upload).
- Checked in our own code today: none of the RED items is imported anywhere; beats come from librosa (ISC), not
  madmom.
