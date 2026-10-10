# Skill system

Files (`backend/video_editing_knowledge/`, plain YAML — editors can extend without touching code):

| File | Content |
|---|---|
| `skills.yaml` | 36 skills: pacing, story, cuts, transitions, colour, audio, captions, motion, quality. Each: triggers / concepts, when_to_use, when_not_to_use, why, rules, avoid, qc, `apply` (executable), `limits` (restraint) |
| `genres.yaml` | 22 content types (fan edit, party, travel, vlog, talking head, podcast, wedding, documentary, cinematic, reel, YouTube, music video, product, sports, gaming, meme, fashion, food, drone, montage, tutorial, event): prompt hints, footage signature, skill pack, structure |
| `platforms.yaml` | Reels, TikTok, Shorts, YouTube, LinkedIn: aspect, duration range, caption safe zones, loudness, hook seconds |
| `language.yaml` | Hinglish / creator slang → concepts (22 groups), and "adjustment" phrases for conversation context |
| `prompt_library.yaml` | 23 ready-made professional briefs (the app's Templates panel, `GET /prompts`) |
| `taste.yaml` | default editing taste (philosophy, transition and effect budgets, caption and audio defaults) |

## Adding a skill

```yaml
- id: smash_cut_comedy
  name: Smash cut for comedy
  category: cuts
  concepts: [comedy]
  triggers: ['smash cut']
  when_to_use: …
  when_not_to_use: …
  why: …
  rules: [...]
  avoid: [...]
  apply: {fast_cuts: true}      # only keys listed in editorial.APPLYABLE are executed
  qc: [...]
```

Then reference it from a genre's `skills:` list. `tests/unit/test_editorial.py` checks that every genre points to
existing skills and every skill has the judgement fields.

## Composition

Styles compose: "party + reel + Instagram" retrieves the party pack, the reel pack and the platform rules; scores
decide conflicts (direct trigger 3 > concept 2 > genre pack 1) and the first decision for a field wins. Explicit user
fields are never touched.
