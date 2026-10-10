# Song-driven editing

Upload a song in the studio's **Sounds** panel (any audio file, or a video — its sound is used). The next AI edit
cuts to it. Everything below runs on the CPU, no paid service.

## 1. Measuring the song — `cutmind/song.py`

| Measure | How | Used for |
|---|---|---|
| tempo, beats | librosa beat tracker | where cuts may fall |
| beat grid | tracked beats + gaps filled at the tempo (a drum-less intro has no tracked beats), continued to the end | every cut, punch and word |
| energy | loudness every 0.5 s, last 30 dB → 0..1 | cut length, punch strength, animation set |
| drums per second | librosa onsets | feel (tempo alone is often halved / doubled) |
| drop | biggest rise in energy, snapped to the beat with the biggest 50 ms loudness jump | always a new shot, a word, a flash + impact hit |
| feel | slow (< 95 bpm, few hits) / fast (≥ 115 bpm with drums, or very busy) / medium | default style |

Cached per file (`data/cache/song_*.json`); measured right after upload, so listing songs stays instant.

## 2. Cutting to it — `cutter.song_slots` / `song_cut`

* Each cut is a whole number of beats: energy ≥ 0.75 → ~0.5 s, ≥ 0.45 → ~1 s, quieter → ~2 s.
* The drop always starts a new cut. If the song's drop would come after the end of the edit, the song starts later
  (`audio.music_start`) so the drop lands ~40 % in.
* Footage → slots: the opening gets the best shot, the closing slot the next best, the rest by how loud the song is
  there (the most energetic footage on the loudest moments, calm footage on calm parts). Neighbouring cuts never show
  the next frames of the same shot. A shot shorter than its slot is slowed down (≥ 0.5x) instead of cutting off the
  beat. When the song is longer than the footage, the strongest shots come back.
* Stutter (one moment 3x) on a loud part; the speed ramp (0.5x → 2x) on the shot leading into the drop.

## 3. Motion and text — `effects`

* Beat punch strength from the loudness of that part; none on quiet parts (a slow drift push-in there).
* Kinetic words: animation set by the energy at that moment — calm (fade, blur, cascade, slide…, 4 beats on screen),
  medium (pop, drop, fly, flip…), fast (shake, flicker, bounce, heartbeat, spin…). Seeded per edit, so two edits don't
  look the same, and never the same animation twice in a row. Very short words (lyrics) only get quick animations.
* Lyrics (`cutmind/lyrics.py`): faster-whisper `base` (LYRICS_MODEL) on the song, confident words only, each shown
  while it is sung. Asked for with "lyrics" / "gaane ke bol"; in fan edits used automatically once known.
* Text behind the person (`cutmind/segmentation.py`): YOLOX-nano finds people, PP-HumanSeg cuts each one out inside
  its box; the text layer goes under the person. The mask is cached with the picture.

## 4. Sound requests

Hinglish and English: "video ki music hata ke dusra gaana lagao" (original off + new song), "video ki voice hata do",
"voice tej karo aur background me music daal do" (voice ×1.8, soft ducked music), "music halka / tej", "mere song pe",
"lyrics ko text bana do", "text person ke peeche". By hand (instant, no AI): `set_audio` — song, music level, voice
level, original sound on/off, song start. With your own song and nobody talking, the clip's own sound is kept low.

## Limits (honest)

* Lyrics from a speech model: clear sung English works (tested: TTS line over a beat; the user's phonk song: 29 words
  in the first 10 s); heavily processed / non-English vocals are often missed or misheard.
* Person cut-out is a 192x192 portrait model inside person boxes: good on mid / close shots, rough on far, tiny players.
* Separating a voice from music in the SAME track (keep the voice, drop the song) needs a source-separation model
  (Demucs, ~80 MB + PyTorch) — not included.
