# Project audit — 2026-10-06

What was inspected, run and found while adding LangGraph, MCP, the prompt coach, live events and the specialist
router. Every item below was observed on this machine (Windows 11, 12 CPU threads, 7.7 GB RAM with ~0.9 GB free
during testing, no GPU).

## Hardware (GET /capabilities)

| | |
|---|---|
| CPU | 12 threads |
| RAM | 7.7 GB total, 0.9–1.7 GB free while testing (other apps open) |
| GPU / CUDA | none (`nvidia-smi` absent; ONNX Runtime providers: CPU, Azure) |
| Disk | 288 GB free |
| FFmpeg | 9.0.1 (winget) |
| Speech-to-text | faster-whisper `tiny`, CPU int8 |
| LLM | in-process ONNX Runtime Qwen2.5 1.5B/0.5B int4 (`PLANNER_MODE=local`); the running demo uses the rules planner |

## Bugs found by running the real app on the user's uploads (all fixed, all with regression tests)

| # | Symptom (observed) | Root cause | Fix |
|---|---|---|---|
| 1 | User prompt "starting ki 3s me zoom ho … phir zoom out" produced a **3-second video** | duration parser took any "N s" as the target length | timed-effect parser runs first; numbers used for timing (`first/last/se…tak/3s me <effect>`) are never the length |
| 2 | Same prompt: zoom-in and zoom-out on the whole video at once | no notion of "effect for part of the video" | `Intent.timed_effects`; Cutter splits the timeline at those seconds (seamless), Effects puts each effect only on its window; Reviewer `timed_effects` check |
| 3 | "base ki tarah effect, sound beat kare" ignored | no bass / beat-punch vocabulary | `bass_boost` (+6 dB low shelf) + zoom punch on every **real** music beat (`pulse` with beat times) |
| 4 | User's new 4K upload: every job failed "Clip analysis failed: loudness.lufs Input should be a valid number" | a silent audio track measures −inf LUFS; JSON cache stored `null` | non-finite loudness → −99 dB; cache loader tolerates old `null` |
| 5 | 4K uploads made 20 Mbit/s "light" proxies (58 MB for 25 s) | proxy encode had CRF only, no rate cap | `-maxrate 6M -bufsize 12M` |
| 6 | "zoom out" also switched the zoom-IN effect on | missing `(?! out)` in one pattern | fixed (found through the MCP stdio check) |
| 7 | "no music" ADDED music | the word "music" matched | negation patterns (`no / without / bina … music`, `music mat`) |
| 8 | Auto edit on the user's footage took **13 min** | 36 cross-fades between 1 s cuts × 3 styled versions | montages use hard cuts on the beat; parallel segment rendering; 1 version by default → 45 s |
| 9 | Hinglish E2E took 243 s, 2 of 3 renders wasted | fix loop retried checks no edit can fix ("nobody speaks" → captions) and kept retrying with no improvement | `fixable` flag on checks; no retry for unfixable failures; stop when a retry changes nothing → 60 s |
| 10 | same E2E: `timed_effects` failed every round | autopilot added a whole-video zoom on top of the timed one | autopilot never adds a global motion when the user timed one |
| 11 | Style glow frames: final encode ~15 s per 30 s per layer | static blurred mask was redrawn + blurred every frame | draw once, `loop` it (measured 14.7 s → 0.2 s) |
| 12 | Music beat grid recomputed in every job (22–54 s) | no cache | per-track beat cache in `data/cache/` |
| 13 | Lessons were written for "nobody speaks in these clips" | lessons for every failure | no lesson for footage limits |
| 14 | `npm run build:web` "Unable to resolve module …/MediaPanel" | OneDrive cloud placeholders look like symlinks to Node; Metro skips them | files rewritten as plain files (see TROUBLESHOOTING.md) |
| 15 | Jest: random timeouts in suites nobody touched | ~11 parallel workers on a machine with <1 GB free RAM → swapping | `maxWorkers: 25%` → 122/122 in 46 s (was 95 s and flaky) |

## Architecture decisions taken in this pass

* **LangGraph** replaces the hand-written Director loop (same agents, now nodes; checkpoints; parallel colour).
* **No Ollama.** The user asked earlier not to use it; the LLM runs in-process (ONNX Runtime), so there is one
  service to deploy. The MASTER BUILD prompt lists Ollama as a candidate — evaluated and not chosen (extra server,
  and the user's own instruction).
* **150 roles, not 150 LLM calls.** On this CPU an LLM call costs 10–30 s; 150 of them would take an hour.
  The registry has 195 roles (169 at first; tracking, text and editorial roles were added later), each backed by real code; the router runs 17–35 of them per request; LLM calls stay
  limited to the Director (configurable with `LLM_AGENTS`).
* **No generative video / image models.** Wan, LTX-Video, HunyuanVideo, FramePack, SD/Flux, RIFE, Real-ESRGAN all
  need a GPU to be usable; they are listed as unavailable with the reason, and FFmpeg fallbacks are used
  (speed change for slow motion, lanczos scaling for resolution).

## Not done / limits (honest list)

* Hindi **speech recognition** quality not measured (no Hindi TTS voice on this PC to make test audio).
* Browser **mic recording** not tested here (the test browser blocks the microphone).
* Docker image not built (Docker not installed).
* Incremental rendering is per job, not per changed segment: a caption-only change still re-renders the cut
  (analysis, transcripts, music beats and proxies ARE reused from caches).
* Native (Android/iOS) app not run (no SDK/emulator); the web build is tested.

## Round 3 (2026-10-06): tracking, text, manual editing, editorial brain

Found while building and testing on the user's footage and the benchmark — all fixed, all with tests:

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 16 | 9:16 + spotlight + name label: the person was half out of frame, label stuck at the edge | centre crop ignored the person | subject-aware reframe comes with spotlight / labels (crop follows the tracked person) |
| 17 | "zoom in text", "neon text style", "flickering text" changed the VIDEO (zoom, cyan look, old-film) | text phrases were also read by the effect / look parsers | text-look phrases are extracted first and blanked out; 63-phrase round-trip test |
| 18 | "pehle 3 sec black and white" made the whole video B&W | "and" split the phrase into two clauses | "black and white" kept as one token; timed `mono` effect |
| 19 | manual change after a fade transition / speed change → invalid plan | text ended after the (now shorter) video | text fitted to the new length; captions re-timed from the transcript |
| 20 | "boring hata de" did nothing | the router skipped speech-to-text before the editorial brain could see that people talk | the brain always gets the words |
| 21 | "jab important baat bole tab zoom" zoomed the whole video, punch-ins never fired | generic zoom keyword; emphasis rules couldn't see pauses after silence removal | punch replaces the generic zoom; "first content word of a new segment" counts as a new thought |
| 22 | jump-cut cover never applied | gap test `< 3.0 s` and odd-index rule | alternate on every jump cut (gap < 8 s) |
| 23 | reviewer said styled captions were "not visible" | it only looked for the purple box colour | boxless captions are found by their letter colour |
| 24 | reviewer flagged editorial punches/flashes as "unrequested" | not told about editorial effects | counted as requested when the brain decided them (each has a logged reason) |

Benchmark (docs/VIDEO_EDITOR_BENCHMARK.md): professional-criteria score 62 % → 100 % on 6 desi prompts.

Still not done: J/L cuts, SFX accents, b-roll, Silero VAD, beat-snapped captions, Ken Burns on still images,
real-footage benchmark with human ratings, Hindi ASR accuracy measurement, Docker build, native app.

## Round 4 (2026-10-07): fan edits from the user's reference videos

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 25 | "make a X edit" in 9:16 crashed the effects step | big kinetic text (170) was above the `TextStyle.size` limit (160) | limit 320; size is computed from the frame width; test uses 9:16 |
| 26 | genre/style words ("fan edit", "nice animations") were lost | the app sent the coach's English summary instead of the user's words | the user's words are sent; the summary is only shown (MCP returns it as `understood_as`) |
| 27 | kinetic words were small and appeared only twice | fixed size, no repetition | ~85 % of frame width, repeated on the beat through the edit |
| 29 | beat-synced cuts drifted off the beat after the first clip (5.4 s instead of 5.5 s, then every cut after it) | the leftover end of a clip and budget-trimmed pieces were not whole beats | `beat_quantize`: such pieces are rounded to whole beats (never through a word, never into footage used elsewhere); unit test checks every cut |
| 30 | the 3 repeats of a stutter got different looks (one B&W + flash) — it no longer read as one moment | colour pass / flash picked by index only | stutter repeats are skipped by colour pass and flash |
| 31 | "make a ronaldo edit that is cool" gave a blue (cool) colour grade | the word "cool" alone picked the cool preset | only colour words make it a grade ("cool tone/colour/look", "colour thoda cool"); unit test |
| 32 | on footage that is already edited (10 shots in 16 s) one 1-beat cut showed two shots, and a shot change was taken for "motion" when choosing the opening | fast cuts ignored scene cuts | pieces are split at scene cuts before chunking; rounding / ramps never grow into the next shot; unit test |
| 33 | the Ronaldo edit came out 7.8 s instead of ~10 s | pieces were rounded to whole beats AFTER the length budget was filled; short shots under-filled it | rounded before choosing; the remaining pieces fill the budget → 10.2 s, every cut on the beat |
| 34 | the fast half of a speed ramp showed footage that the next cut showed again | the ramp took footage after the piece without checking | ramps skip pieces whose extension is used elsewhere or crosses a shot change |
| 35 | reviewer failed "ending" by 0.2 on a stutter edit | the 3 stutter repeats were counted 3 times, and a 0.25 s slice measures above its whole piece | repeats counted once; 5 % tolerance for the 0.5 s motion sampling |
| 28 | manual edit: live panel showed AI steps as "pending" forever | one row list for both job kinds | manual jobs show apply → render → quality check only |

Still not done for this style: text **behind** the person (needs segmentation), song-lyric captions, SFX whooshes.

## Round 5 (2026-10-07): the user's own song

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 36 | song edit came out 10 s and the drop (10.5 s) fell after the end | empty beat slots were dropped when footage ran out; "half the footage" rule | strongest shots reused instead of empty slots; song mode keeps all footage; song starts later when the drop would be outside |
| 37 | the drop cut was 0.25 s off | drop measured on a 0.5 s grid | snapped to the beat with the biggest 50 ms loudness jump |
| 38 | first shot 0.3 s long | the song's first beat came early | first cut at least ~one beat |
| 39 | no cuts for 9 s in a drum-less intro | beat tracker finds no beats there | regular beat grid fills gaps, continues to the end; drop always on it |
| 40 | edit stopped at 12 s of a 16 s song | the tracker stopped 2 s before the song's end | same grid |
| 41 | punches as weak after the drop as before it | strength from the whole song's feel ("slow") | strength from the loudness of that part |
| 42 | song list timed out (15 s) in the app | every song re-measured on every listing | listing shows cached results; measuring runs in the background / at upload |
| 43 | music volume change took 36 s | the person mask for text-behind was recomputed | mask cached next to the cached picture → 8 s |
| 44 | that cache broke rendering (`scale=720:796af5e889`) | the cache key variable shadowed the frame height `h` | renamed; caught by a live run |
| 45 | "song feel" / "lyrics" decisions vanished | the cutter cleared all decisions, the audio agent runs before it | audio decisions kept |

## Round 6 (2026-10-07): the user's own sentences through the app's agent

| # | Sentence | Wrong result | Fix |
|---|---|---|---|
| 46 | black and white screen mat karo | made it black and white | negation per clause (mat / nahi / no / bina / hata…) removes effects, looks, text; the editorial brain respects it |
| 47 | caption person ke peeche lagao / … aage lao | "follow cam + captions" | text / captions in front of or behind the person; "peeche" no longer means follow-cam in text sentences |
| 48 | starting me bahut zoom karo | zoom over the whole video | "starting me" = first 3 s; "bahut" = strength 1.8 |
| 49 | blue shirt wale pe focus, baaki blur | the whole video blurred | person picked by shirt colour every frame, cut out, the rest blurred |
| 50 | (focus) Ronaldo's white shirt counted as blue | colour grade tint | coloured targets need real saturation; threshold from measured jerseys |
| 51 | colour pass looked like a negative | harsh inverted / silhouette shots | old-movie B&W by default; harsh ones only when asked |
| 52 | jaha me nahi bol raha us part ko cut kar do | read as "auto edit" | silence phrases ("nahi bol raha", "not talking") |
| 53 | awaaz saaf kar do, hawa ki noise | read as "voice louder" | noise / wind / saaf → RNNoise cleanup; "hum" (we) no longer = humming |
| 54 | Remove filler words (coach sentence) | "no text on screen" | text negation only for on-screen text words |
| 55 | reference edit used one clip of three | energy-only assignment | every clip gets a calm slot |
