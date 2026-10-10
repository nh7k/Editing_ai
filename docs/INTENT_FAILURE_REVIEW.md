# Intent failure review — "yaha screen white kar do nomal jasia tha" (2026-10-10)

The user put a marker at 4.3 s on an edit that already had a black-and-white effect and graphics, and wrote
**"yaha screen white kar do nomal jasia tha"**. The app said it did not understand and printed five fixed
examples (zoom, WOW likh do, rose ka sticker, black and white, ye part hata do), none related to the sentence.

Research note: everything below was found by reading and running CutMind's own code. The "how production
assistants do it" part (top-k with a margin, disambiguation chips, phonetic keys for romanised Hindi) is from my
own knowledge, not from a web search in this session.

## 1. Reproduction (real trace, run on 2026-10-10)

```
normalize()            -> "yaha screen white kar do nomal jasia tha"   (nothing unified: nomal, jasia stay)
moment.read_comment()  -> effects [], text None, emoji None, cut False, understood []   -> ValueError
tools.parse()          -> calls [], unknown: nearest = replace_audio, stabilize, hook_first
intent.parse_intent()  -> NOT empty: "auto edit (the agents choose effects, music, captions and order)"
```

`nearest()` per-word best match (difflib ratio, max over synonym words):

| skill | score | user word | synonym word |
|---|---|---|---|
| replace_audio, stabilize, hook_first, duck_music, thumbnail, picture_in_picture, export_preset, audio_fade | 1.00 | **kar** | kar |
| fade_white, flash | 1.00 | white | white |

All tie at 1.00; the first ones in dictionary order win. The informative word ("white") counts exactly as much as
the filler verb ("kar").

## 2. Root causes (each checked; my guesses vs the brief's guesses)

| # | brief's guess | verdict | evidence |
|---|---|---|---|
| 1 | Missing white synonyms | **Partly.** fade_white and flash have "white flash", "safed chamak", "white fade"… but not "screen white", "white kar do", "safed kar do", "wite", "whight" | skills/tier1/fade_white.yaml, flash.yaml |
| 2 | No tolerance for spelling variants (nomal, jasia, yhn, krdo) | **True.** `prenormalize.normalize` leaves them as they are; there is no phonetic key | trace above |
| 3 | Long sentences matched as a whole, noise words lower the score | **Different from guessed:** the exact matcher fails because no synonym phrase appears; the fallback (`nearest`) is the real bug: it is per-word max with **no weighting**, so filler words ("kar", "tha", "yaha") tie with the meaning word | tools/parse.py `nearest()` lines 726-738 |
| 4 | Marker time not bound to "yaha / here" | **True for the Tier 1 path; half-true for comments.** A comment already carries `at`, but `moment.py` only understands effects from the old `parse_intent`; the Tier 1 tools are never tried for a comment | moment.py `read_comment`, `moment_options` |
| 5 | No "restore / normal jaisa tha" skill | **True.** Nothing removes an effect at a moment; "normal / pehle jaisa / original / wapas" have no meaning anywhere | grep: no restore skill in skills/tier1 |
| 6 | Fallback suggestions not from the user's words | **True, two places:** moment.py line 102 prints a fixed list; `nearest()` is from the words but broken (#3) | moment.py:102 |
| 7 | Thresholds too strict / uncalibrated | **Not the cause here:** there is no score threshold at all — matching is yes/no. There is nothing to calibrate yet | tools/parse.py |
| 8 | (not in the brief) **A silent wrong edit in chat** | **True and worse than the dead-end:** the same sentence typed in the chat (no marker) passes `_must_understand` because `parse_intent` reads "kar do" as "auto edit", so it would start a full automatic re-edit nobody asked for | api.py `_must_understand`, trace above |
| 9 | (not in the brief) Two matchers that disagree | The comment path uses the old `intent.parse_intent`; the chat Tier 1 path uses `tools.parse`. A word taught to one is unknown to the other | moment.py vs tools/parse.py |

## 3. What I will build (and where I disagree with the brief)

- **Agree:** context object, marker binding, a restore skill, chips instead of dead-ends, suggestions from the
  user's own words, logging unmet requests for human review, calibrated thresholds.
- **Disagree — no new duplicate skills.** `white_flash` already exists as `flash` (white by default) and
  `fade_to_white` as `fade_white`. Two ids for one effect split the synonyms and confuse the ranking. I add the
  new names as synonyms and labels, and add only what is really missing: `restore_normal`, `brighten_to_white`,
  `white_screen_card`.
- **Disagree — embedding model and tiny LLM fallback come last, maybe never.** The failure is a scoring bug, not a
  "needs AI" problem. A weighted token matcher with a phonetic key fixes this class of failure on CPU in
  milliseconds. An embedding model adds 100+ MB and a licence check; I will measure whether the token matcher
  leaves enough misses to justify it, and say so with numbers.
- **Disagree — 'restore' must not touch speed by default.** Undoing a speed change changes the video's length;
  that only happens when the user says so ("speed normal karo").

Order: failing tests → fuzzy normalisation + weighted token scorer → context resolver + restore skill → API
(`/tools/resolve`, comment fallback, chat guard) → chips in the app → unmet-request log + review script → corpus
(400+) and calibration → renders → eval before/after (docs/INTENT_EVAL.md).
