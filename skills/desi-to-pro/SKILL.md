---
name: desi-to-pro
description: Turn a casual Hindi / Hinglish / English video-editing request (slang, typos, Devanagari) into a precise professional edit brief using CutMind's skill registry. Use when you need to understand what a creator wants from an edit prompt, or to write the brief CutMind will execute.
---

# Desi → Pro (prompt enhancer rules)

The code is `backend/cutmind/prompt_enhancer.py` (`enhance(text)`), `backend/cutmind/prenormalize.py` and
`backend/cutmind/skill_registry.py`. Use it directly when you can:

```python
from cutmind.prompt_enhancer import enhance
enhance("ek filmy reel bana de")["pro_prompt"]
```

If you must apply the rules by hand, follow these steps in order.

## 1. Normalize (deterministic)
- Devanagari → Hinglish (rule-based romaniser, schwa deletion: "रहता" → "rahta"); English words written in
  Devanagari back to English ("सेकंड" → second, "कैप्शन" → captions, "ब्लैक एंड व्हाइट" → black and white).
- Spelling variants → one form: bohot / boht / bht → bahut; nhi → nahi; krdo → kar do; jyada → zyada; vdo → video.
- Number words → digits ONLY before a time unit: "das second" → 10 second, "pandrah sec" → 15 sec, "aadha minute"
  → 30 second, "dedh minute" → 90 second. ("do" alone is "do it", never 2.)
- Typos of the editor's own words → that word ("captins" → captions, "blak and wite" → black and white). Never
  "correct" a real English or Hinglish word ("cute" stays cute, "peele" stays peele).

## 2. Map concepts to registry skills
- Look the words up in `skills/registry/*.yaml` synonyms (English, Hindi, Hinglish, slang, typos), longest first:
  "zoom transition" is the transition, not the zoom effect.
- Negation applies to the thing just before it: "zoom mat lagao" = do NOT zoom; "glitch effect mat daalna" = no glitch.
- Magnitude: thoda / slightly = small (pace x1.5, length x0.7); bahut / very = large (pace x2, length x0.5).
- "X to Y" colour changes use the LAST colour: "text colour black to white" = white.
- Music LEVEL words (gaane ki awaaz dheemi / kam / tez) change the volume, never the cut.
- A complaint is the opposite ask: "bahut dheema lag raha hai" = make it faster.
- Only Tier 1/2 skills with status other than planned/blocked may be used for an edit.

## 3. Expand into a Pro Brief
Pick one style recipe (`video_editing_knowledge/recipes.yaml`): a style word wins (podcast, wedding/shaadi, gym,
filmy/cinematic, travel/trip, food, fan edit, lyric poster, …), else the detected genre, else a reel defaults to
"Daily vlog". Fill only what the user did not say, and LIST every filled field as an assumption:

`goal · platform · duration · aspect · pacing (shot length, cut on) · hook · look · captions · music (mood, BPM,
ducking) · transitions`

Example: "ek filmy reel bana de" →
`aspect: 9:16; goal: Cinematic short; platform: Instagram Reels / YouTube Shorts; duration: 45 s (assumed);
pacing: 3-7 s shots, cuts on action (assumed); hook: the most striking frame (assumed); look: cinematic (assumed);
captions: off (assumed); music: calm (60-95 bpm) (assumed); transitions: none / fade (assumed)`

## 4. When unsure
- Nothing understood → say so and offer the 3 closest skills (`suggestions()`), never a silent default edit.
- A clause only half understood (most words are not the editor's own) → the optional planner LLM may pick among
  registry commands; its answer is rejected if it contradicts a negation, removes something not asked, changes the
  whole style for a small ask, or talks about a topic the user did not mention.
- Ask at most one short question, only when a wrong guess would delete or redo a lot.
