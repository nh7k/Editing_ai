# Catalog review — is "16,000 variants from 1,000 base skills" the right target? (2026-10-09)

Short answer: **no, not as a target.** A catalog of distinct, rendered, tested variants is a great asset, but
the number should be an OUTPUT of the difference test, not an input. Below: the evidence, what I would do
instead, and what this brief forgot.

## 1. Evidence: how many distinct BASE skills exist?

| source | count | note |
|---|---|---|
| FFmpeg 9.0.1 on this laptop (`ffmpeg -filters`) | 527 filters: 264 video→video, 108 audio→audio, 30 two-input video, 27 sources, … | many are plumbing (format, setpts, split, null, hwupload) or analysis (cropdetect, ebur128), not user effects |
| CutMind today | 51 video effects, 58 transitions, 23 text animations, 10 LUT looks, ~40 parser skills | 220 registry skills |
| A pro NLE's effect browser (Premiere / Resolve / Final Cut) | a few hundred effects + transitions; Resolve's OpenFX list is in the low hundreds | their feature lists are public; exact counts differ by version (to be filled in COVERAGE_MATRIX.md with dated sources) |

A realistic ceiling of user-meaningful base skills is **about 400–600**, not 1,000. Getting to 1,000 bases means
splitting one engine into many ids (e.g. "zoom 10 %", "zoom 20 %" as bases). That is exactly the padding the
brief itself forbids.

## 2. Variants: which axes make a VISIBLE difference

| axis | meaningful steps | why not more |
|---|---|---|
| intensity / amount | 3 (halka / normal / bahut) | the difference test will merge 5 % steps: below ~3 mean-abs-diff on a test clip nobody can see it |
| direction | 2–8 (left / right / up / down / diagonals) | only for directional skills |
| easing | 4–5 visibly different (linear, ease-in-out, back, spring, bounce) | ease_in vs ease_out on a 0.3 s move are near-duplicates |
| duration | 3 (fast 0.3 s / normal 0.6 s / slow 1.2 s) | for transitions and moves only |
| style (text / looks) | as many as are designed | real design work, the biggest honest source of variants |
| platform | 5 (Reels, Shorts, Status, YT long, LinkedIn) | for export / aspect / templates only |
| time mode | 7 | a time mode is WHERE an effect applies, not a different look. **Counting it as a variant would multiply the catalog ×7 with zero visual difference on any one frame.** I do not count it. |

An honest estimate: 400–600 bases × an average 4–8 visibly distinct variants ≈ **2,000–4,000 distinct
variants.** 16,000 needs about 27 per base. Only text styles, looks and templates can honestly reach that.

## 3. What I propose instead

1. **Same machinery, honest number.** The generator, axes, stable ids, the automated difference test and the
   ready / planned promotion are built as you asked. The headline number is "variants that passed the
   difference test", and the rejected near-duplicates are reported.
2. **Target by coverage, not by count.** Every feature in the coverage matrix (Premiere / Resolve / CapCut /
   Kdenlive / …) maps to a skill id or a decision (build / defer / reject + reason). That is what makes a
   professional say "it has everything I need".
3. **Ready means rendered.** The status of every variant is `ready`, `generated-untested`, `planned` or
   `rejected-duplicate`. Only `ready` appears to the planner; the rest are searchable and answer "not
   available yet".
4. **Sequence.** Tier 1 (the 100 MVP skills, separate brief) comes first, because the catalog's base skills are
   built on the Tier 1 engines. The catalog generator comes after Tier 1 is green.

## 4. What the brief forgot

- **Undo and compare are the most-used "skills".** They exist (`/undo`, `/redo`, `/versions/compare`) but are
  not in any skill list. The catalog should expose them so "pichla wala wapas lao" maps to them.
- **Keyframes on any parameter** (not just zoom) is the professional standard. One base skill with a keyframe
  track replaces hundreds of "X starting at Y" variants.
- **Audio standards:** dialogue at -16 LUFS (mobile) / -14 (YouTube), true peak ≤ -1 dBTP, and music ducking
  depth in dB are numbers, not adjectives. The previous checkpoint found that "louder" misses its LUFS target,
  so loudness is a correctness problem first.
- **Accessibility:** caption safe area (not under the Reels UI), minimum size, contrast, an .srt sidecar.
  Coverage needs the UI-overlay safe zones per platform.
- **India-specific:** Indic fonts beyond Devanagari (Bengali, Tamil, Telugu, Gujarati, Gurmukhi: Noto has OFL
  fonts for all), festival templates, wedding highlight structure, WhatsApp Status 60 s splits.
- **Phone size:** 16k variants as JSON is ~10–20 MB. The phone must ship only Tier 1 ids + names (~100 KB),
  with the rest fetched from the server on search.
- **Licences of assets, not just code:** LUTs, fonts, SFX and stickers must be generated or OFL / CC0, and each
  one must be recorded.

## 5. Plainly

16,000 is a marketing number. I will build the pipeline that could produce it, but I will report the number
the difference test allows. If that is 3,000, I report 3,000.
