# Editorial engine (prompt compiler + skill system)

Code: `backend/cutmind/editorial.py`, `coach.py`, `intent.py`. Knowledge: `backend/video_editing_knowledge/`.

```
"bhai isko mast bana de, boring hata aur thoda cinematic"
   │
   ├─ parse_intent ............ EXPLICIT fields (what the user really said): cinematic colour, …
   ├─ concepts_in (language.yaml) .. make_it_good, remove_low_value, cinematic
   ├─ classify (genres.yaml) ....... words ("party", "shaadi", "podcast") or, if not said, the footage:
   │                                 speech words/s, motion, clips → talking head / vlog / montage / travel
   ├─ platform_for (platforms.yaml)  Reels / TikTok / Shorts / YouTube / LinkedIn → aspect, safe zone, LUFS
   ├─ retrieve (skills.yaml) ....... only relevant skills: direct triggers (3) > concepts (2) > genre pack (1)
   └─ compile_spec ............... ProfessionalEditSpec
          explicit : fields the user set — never overridden
          inferred : [{field, value, reason, skill}] — every choice explains itself
          unknown  : what is not known (no platform, content type unclear, skills skipped and why)
          limits   : restraint (max transitions / effects)
          avoid    : anti-patterns from the skills
   → apply_spec → the Intent the agents execute (LangGraph `analyze` node)
```

## When it runs

Only for vague / creative requests (`wants_editorial`): a concept, a genre word, a platform, or "auto edit".
"trim to 15 seconds" is done exactly as said — no hidden extras. `EDITORIAL=0` turns it off (benchmark baseline).

## Guard rails

* Explicit > project memory > user taste > `taste.yaml` > skill defaults.
* Skills that would chop speech (fast reel, beat cuts) are skipped when the footage is people talking — written into
  `unknown` with the reason.
* "Over mat kar / simple / professional" → restraint skill: no inferred transitions, ≤ 2 inferred effects.
* Silence removal the brain inferred only touches clips where people talk (quiet scenery is not dead air).
* Decisions are stored in `plan.decisions` (whole-edit choices + per-moment ones such as "opening shot 4.1–5.1 s:
  most picture change with nobody talking", "punch-in at 1.48 s: emphasis on 'mountains'").

## Conversation context

`is_adjustment` ("thoda dark", "captions hata de", "zyada flashy hai simple kar") → the last edit's intent is
reused with the change on top; `REMOVALS` take captions / transitions / effects out; "zyada dark ho gaya" means
*brighter*.

## Executable knobs the skills drive

`cut_length`, `beat_sync`, `fast_cuts`, `hook_first`, `ending_peak`, `remove_silence/fillers/idle`, `jumpcut_cover`,
`emphasis_punch`, `flash_accents`, `color_preset`, `music/music_mood`, `target_lufs`, `caption_words`,
`text_style`, `text_animation`, `voice_cleanup`, `aspect_ratio` (platform), caption safe-zone margin (platform).

## Results

See `docs/VIDEO_EDITOR_BENCHMARK.md`: 6 desi prompts, professional criteria 62 % (parser only) → 100 % (with the
brain); reviewer match 90.5–100 → 100. Criteria are rules, not a human taste score.

## Fine-tuning

Not done, on purpose: there is no licensed dataset of (raw footage, professional edit) pairs, and the benchmark shows
the structured knowledge + retrieval already moves the measured criteria. Revisit when users' accepted / rejected
edits (feedback + choices, already stored) reach a few thousand examples.
