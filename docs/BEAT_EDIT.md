# Beat edit — how CutMind edits on the music (2026-10-11)

## What the user asked

"Beat aur music ke base pe edit kar — beat pe animation, motion, effects — kisi bhi gaane pe, hardcode nahi."

## What was wrong (measured with tools/beatcheck.py on real renders)

`tools/beatcheck.py out.mp4 [plain.mp4]` tracks the beats on the video's OWN audio (librosa) and the picture's
hits (peaks of frame-to-frame change: cuts, punches, flashes, shakes), and reports the share of beats that have a
hit within ±70 ms, against the chance level.

| problem | evidence | fix |
|---|---|---|
| the user's "beat edit" was not on the beat | 3 / 23 beats hit = chance (13 %) | all below |
| cuts drifted behind the music | every 0.65 s segment rendered 20 frames (0.667 s): +0.21 s late after 25 cuts | `renderer.render_segment`: frame-exact segments on the timeline's frame grid → every cut within ±1 frame |
| beat punches invisible | 7 % zoom as a 0.36 s triangle | `fx_catalog._pulse`: 1-frame snap a frame before the beat, exponential settle (τ 0.13 s), per-hit size |
| a punch on every beat, none in calm parts | — | `beatmap.plan_hits`: density follows the song's energy (calm 1/4, medium 1/2, loud and after the drop every beat), bar phase from the kick, the drop gets the biggest punch + flash + shake, min 0.22 s between hits |
| the beat tracker sat on the off-beat for some songs | a 100 bpm song half a beat off (punches between kicks) | `song.analyze_song` + `beatmap.kick_phase`: move the grid ¼ / ½ / ¾ beat when the kick (40-120 Hz) is clearly (> 1.25×) stronger there |
| "is gaane ki beat pe edit karo" did nothing | it only set `beat_sync`; song cuts need fast cuts, hits need "pulse" | `intent`: "beat / music / gaane ke base pe EDIT" = song-driven cuts + hits |
| the skill path ignored the user's song | add_music took a library track | `b_audio._track`: the picked / newest uploaded song first |
| "... animation and motion add karo" failed | `beat_edit changed the length 15.00 → 15.12 s` | `b_beat._keep_length` |

## Generality (no song is special-cased)

Everything comes from the song: librosa tempo + beats (ISC), RMS energy every 0.5 s, the drop (largest energy rise,
snapped to a beat), the kick band per beat (numpy FFT). Unit tests run the hit planner at 70, 92, 100, 120, 128, 150,
160 bpm (`tests/unit/test_beatmap.py`).

Live-app matrix (first message "is gaane ki beat pe edit karo" → director; 8 songs × 2 videos; see the final
numbers in the CHANGELOG / TEST_REPORT entry of this change).

## Research used (ideas only, no code copied — sub-agent report, sources checked 2026-10-11)

- Onset strength / spectral flux; Ellis (2007) DP beat tracking (in librosa); kick from low-band flux; energy-driven
  cut density (cut every bar / 2 beats / beat); drop = largest rise after a dip; land accents 0-1 frame before the
  beat (ITU-R BT.1359 tolerance: audio may lag video, not lead it); avoid fatigue with a per-bar budget.
- Licences: librosa ISC (used). beat_this MIT code + weights — a possible later upgrade for downbeats (needs torch;
  not added). BLOCKED: aubio (GPL-3), Essentia / TempoCNN / DeepRhythm (AGPL), madmom models (CC BY-NC-SA), Demucs
  weights (unclear). Not added: Spleeter (no Python 3.13), BeatNet / all-in-one (broken install / heavy).

## Not done / NOT TESTED

- Downbeats from a model (beat_this) — the bar phase is guessed from the kick.
- Speed ramps to the music, motion between hits beyond the existing drift / zoom.
- Phone (Media3) path — NOT TESTED.
