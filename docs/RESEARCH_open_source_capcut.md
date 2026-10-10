# Research: open-source CapCut alternatives & effects (2026-10-06)

Web research done for CutMind. Every licence was checked on the live repo/site (items marked *unverified* were not).

## 1. Is there a "same-to-same" open-source CapCut? — **No.**

| Project | What | Licence | State | vs CapCut |
|---|---|---|---|---|
| OpenCut (github.com/OpenCut-app/OpenCut) | "open-source CapCut alternative" | MIT | ~92.7k★, main branch is an early Rust rewrite; classic web version archived May 2026 | timeline, keyframes, masks, a few effects; tiny preset library; plans MCP/agent API |
| OpenReel Video (github.com/Augani/openreel-video) | browser editor (WebCodecs/WebGPU) | MIT | ~5.3k★, active | closest *working* web clone: multi-track, captions, LUTs, keyframes |
| Omniclip (github.com/omni-media/omniclip) | browser editor | MIT | ~1.5k★, 2.0 in development | trim/split, text, transitions, filters |
| editly (github.com/mifi/editly) | JSON spec → FFmpeg + gl-transitions | MIT | ~5.5k★ | closest *architecture* to CutMind |
| Shotcut / Kdenlive / Flowblade (MLT) | desktop NLEs | GPL-3.0 | mature | full NLEs, speech-to-text, no CapCut templates |
| OpenShot (libopenshot) | desktop | LGPL-3.0 | active | keyframes, chroma key, wipes |
| Motion Canvas / Revideo | code-driven animation | MIT | active | programmatic templates |
| Remotion | React → video | **special licence** (paid for companies > 3 people) | – | avoid bundling |
| designcombo react-video-editor, Twick, Diffusion Studio | web SDKs | source-available / watermark / custom | – | avoid bundling |
| Olive | desktop | GPL-3.0 | stalled since Dec 2024 | – |

Conclusion: nothing open source combines CapCut's preset libraries (effects, text animations, stickers, transitions),
styled auto-captions and AI in a polished web+mobile app. The building blocks exist, so CutMind assembles them.

## 2. What CutMind uses (all legal to ship)

| Category | Source | Licence | In CutMind |
|---|---|---|---|
| 58 transitions | FFmpeg `xfade` | FFmpeg LGPL/GPL, called as a separate process | `cutmind/fx_catalog.py` (all 58 + 4 classic names) |
| motion + 28 video effects | FFmpeg filters (`rgbashift`, `chromashift`, `noise`, `lagfun`, `tmix`, `lenscorrection`, `pseudocolor`, `colorhold`, `edgedetect`, `geq`, `pixelize`, …) | same | glitch, RGB split, VHS, film grain, old film, scanlines, flash, strobe, mirror, kaleidoscope, pixelate, posterize, negative, colour pop, ghost trail, echo, fisheye, dreamy glow, neon edges, sketch, thermal, night vision, cinema bars, duotones, vignette, sharpen, blur + zoom in/out, pans, shake, swing, beat pulse, slow spin |
| 10 colour looks | **our own** 33³ .cube LUTs generated from maths (`cutmind/luts.py`) | ours | teal & orange, golden hour, moody blue, cyberpunk, forest, faded film, pastel, noir, warm film, arctic |
| text animations | libass (ISC) ASS override tags | ISC | fade, pop, bounce, slide-up, typewriter, karaoke word highlight |
| gradients / glow / wash | FFmpeg `gradients` + `alphamerge` | – | style graphic tracks (`cutmind/styles.py`) |

## 3. Possible next additions (licence-safe)

* **gl-transitions** (MIT, ~100 GLSL transitions): port favourites to FFmpeg `xfade=custom` expressions, or render
  with moderngl + EGL; same shaders could power Skia previews.
* **Fonts**: Google Fonts (OFL/Apache) — Montserrat, Poppins, Bebas Neue, Anton, Noto Sans (Indic).
* **Stickers/emoji**: Fluent Emoji (MIT), Noto Emoji (Apache/OFL); Twemoji/OpenMoji only with attribution.
* **Lottie**: let users import their own (LottieFiles' licence forbids building a competing library); render with
  ThorVG (MIT).
* **SFX**: Kenney (CC0), Freesound CC0-only. Not Pixabay/Pexels/Mixkit (custom licences, no redistribution).
* **frei0r** (GPL-2.0) only via a separate GPL FFmpeg build — not in the gyan.dev build we use.

Avoid: Remotion/designcombo/Twick code, Animate.css (Hippocratic licence), "free" LUT packs without a licence,
python-lottie (AGPL), bulk LottieFiles packs.
