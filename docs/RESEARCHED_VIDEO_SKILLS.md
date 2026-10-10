# Researched video-editing skills (2026-10-06)

Fifteen public repositories the user pointed to were read (README, skill/rule files, key scripts) through the
GitHub API. Nothing was copied into CutMind: the rules in `backend/video_editing_knowledge/` are our own wording of
principles that several sources agree on. Repos without a licence were used for ideas only.

## Summary table

| Repo | License | Stars / last push | What it is | Adopted (as our own implementation) | Not adopted |
|---|---|---|---|---|---|
| browser-use/video-use | MIT | 28k / 2026-10 | agent skill: transcript → EDL → render → self-check | cut on word boundaries with padding; 30 ms audio fades at every segment edge (renderer); **EDL entries carry a reason** (→ `plan.decisions`); bounded "no grade by default"; self-check loop capped at 3 (→ reviewer + fix loop) | ElevenLabs transcription (paid), Remotion/HyperFrames, parallel cloud sub-agents |
| Monet-AI-Editor/Monet | MIT | 116 / 2026-07 | Electron editor, deterministic timeline commands via CLI/HTTP/MCP | **every timeline change is a deterministic command** (→ `/manual` ops + MCP `manual_edit`); timeline-continuity checks | Electron/macOS, Remotion, paid AI SDKs, telemetry |
| EverythingAI-Pro/ai-video-editor | MIT (+MIT vendor) | 19 / 2026-06 | talking-head editor driven by `taste.yaml` | **taste file** (→ `taste.yaml`); b-roll / cut cadence numbers; hook rubric ideas | ElevenLabs/Anthropic/Buffer, yt-dlp b-roll scraping (copyright) |
| half-1999/AI-Video-Editor | MIT | fork | older snapshot of video-use | — (use upstream) | — |
| Rajbharti06/Ultimate-Video-Editing-Skills | none found | 2 / 2026-06 | big markdown "veteran editor" skill | ideas only: mood → shot length table, "~90 % hard cuts", emotion → grade, QC/pitfall lists | any text (no licence, mixed provenance), GPU/paid routes |
| danielnguyenfinhub/video-editor | none found | 0 / 2026-06 | MoviePy reels editor | ideas only: keyword-triggered punch-ins with a budget, smoothed face reframe, caption-to-beat snapping | code (no licence; several files are one-line `\n` blobs), MoviePy |
| gracech0322-cmd/seedance-2-prompt-library | none found | 47 / 2026-08 | prompts for a generative model | idea only: time-coded segment plans, "state what stays the same" | generative/paid content |
| jordantobyll/video-editing-skills | none found | 0 / 2026-06 | VAD jump cuts + Remotion montage | ideas: VAD silence defaults, teaser-of-the-payoff hook, montage ordering | code (no licence), torch, Remotion |
| manalkaff/remotion-prompts | MIT | 42 / 2026-02 | community prompts for Remotion | image-animation recipe: blur-in → tiny push → highlight; ~5 % zoom over 5 s | Remotion, Mapbox (paid), the ~$700 token workflow |
| remotion-dev/skills | none found (likely Remotion licence) | 4.8k / 2026-10 | official Remotion agent skills | reading only: clamp everything, expo-out entrances, transitions shorten the timeline, log-scale zoom | any text; Remotion itself |
| haidrrrry/claude-remotion-skill | MIT | 265 / 2026-08 | motion-graphics rules with numbers | multi-property entrances, stagger tables, exits faster than entrances, hold/hit rhythm, one hero colour | "Ken Burns on every still", background mesh everywhere |
| imtamiliniyan/claude-video-skills | MIT | 1 / 2026-07 | Remotion templates + Python helpers | **zoom-punch scorer** (numbers / pivot words / after a pause, budget per 6.5 s, ≥ 3.5 s apart, ~6–8 %) → `emphasis_points`; every jump cut covered → `jumpcut_cover` | cloud transcription defaults, b-roll generation APIs |
| genchebur90-debug/video-editor-skill | MIT | 0 / 2026-08 | FFmpeg + libass skill (closest to our stack) | chained `\t` overshoot captions, platform caption safe zones (→ `platforms.yaml`), smoothed slew-limited reframe (→ tracking smoothing), readability limits | optional Remotion folder, yt-dlp, Edge-TTS |
| JJenglert1/remotion-claude-video | none found | 49 / 2026-02 | tutorial starter kit | spring preset table (ideas) | vendored third-party skills, paid APIs |

## Remotion: not in the product

Remotion is source-available, free only for teams of ≤ 3 people; a video editor / prompt-to-video product is
"Automators" use — **$0.01 per render, $100/month minimum** — and it renders through headless Chrome, which is slow
on a CPU-only machine. Every motion principle we needed maps onto libass (`\t`, `\fad`, `\move`, `\fscx`, `\blur`)
and FFmpeg (`crop`/`scale` expressions, `vignette`, `xfade`), which CutMind already uses.

## Principles that made it into the knowledge base (our wording)

* Every cut needs a reason; most cuts are hard cuts; transitions only when they mean something.
* Cut on word boundaries; prefer silences ≥ 0.4 s; keep a little air; never trim a laugh or punchline.
* Cover jump cuts (alternate a ~8 % tighter crop) or punch in on the key word (numbers, "but/lekin", after a pause).
* Vary shot length; fast pacing for energy, long holds for scenery and emotion.
* Open on the most eye-catching moment (hook); end on a strong one.
* No grade unless asked or the genre calls for it; protect skin tones; consistency beats perfection.
* Duck music 12–18 dB under speech; −14 LUFS for social; fades on music in/out.
* Captions: 2–3 words for short-form, keep above the platform UI (Reels 24 %, TikTok 22 %, Shorts 18 %).
* Motion: no linear easing, exits faster than entrances, one hero element at a time.
* Restraint: effects only with a reason; professional editing is often what you don't do.

## Not implemented yet (honest)

J/L cuts (audio leading the picture), SFX accents, b-roll, VAD-based (Silero) silence detection, beat-snapped caption
timing, image (Ken Burns on stills) workflows — listed in PROJECT_AUDIT.md.
