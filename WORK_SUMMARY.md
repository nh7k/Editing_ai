# CutMind — ab tak kya kya kiya (2026-10-03 se 2026-10-06)

Ye file simple Hinglish mein poora safar batati hai: kya banaya, kya badla, kya bugs mile, kya test hua aur kya
abhi baaki hai. Technical details: `ARCHITECTURE.md`, `SETUP.md`, `TEST_REPORT.md`, `CHANGELOG.md`.

---

## 1. Project kya hai

**CutMind** — prompt se chalne wala AI video editor. Aap clips upload karte ho, prompt likhte ho
("30 sec travel reel, fast cuts, warm color, captions, silence hatao"), aur agents ki ek team edit karti hai:

| Agent | Kaam |
|---|---|
| Director | prompt samajhna, plan banana, sabko chalana, retry, lessons |
| Analyzer | clip naapna: duration, scenes, silence, speech (whisper), loudness, beats, frozen/idle hisse |
| Cutter | kaatna, jodna, silence/filler hatana, length fit karna, word ke beech kabhi nahi kaatna |
| Audio | music, ducking, voice cleanup, mute, louder/quieter, audio fade |
| Color | grade/presets (warm, cool, cinematic, vintage, bw, vivid, sepia), gamma, clips ka exposure match |
| Effects | captions, title, watermark, transitions, zoom/shake/blur/vignette/sharpen, rotate/flip, aspect, GIF/MP3 |
| Reviewer | final video ko asli mein check karna (ffprobe + frames + audio) aur har agent ko +/- points dena |

Agents video ko kabhi seedha nahi chhoote — woh ek **Edit Plan JSON** likhte hain; ek deterministic **FFmpeg
renderer** usse video banata hai. Kam score wale agent ko feedback ke saath dobara chalaya jaata hai (max 2), aur
har galti ek "lesson" ban kar agle prompt mein jaati hai. User ka 👍/👎 bhi points deta hai. Scoreboard API hai.

---

## 2. Timeline — kya kab hua

### Din 1 (3 Oct) — poora MVP
- FFmpeg aur (us waqt) Ollama winget se install kiye, Python venv + packages, `setup.bat/sh`, `run-all.bat/sh`.
- Backend: FastAPI + SQLite, Edit Plan (Pydantic validation), renderer, 7 agents, scoring/lessons, retry loop, API
  (projects, upload, edit job, job status, plan, output, feedback, scoreboard), upload limits, saaf error messages.
- Test media FFmpeg + Windows ki free TTS (SAPI) se banaya — koi copyrighted file nahi.
- Mobile app (Expo + TypeScript): Projects, Import, Editor (Skia timeline), Agent Activity, Scoreboard, Export,
  Settings. Web pe asli backend ke saath chala ke 4 bugs pakde aur fix kiye.
- Windows **Smart App Control** ne kuch DLLs block ki (numba) — version pin karke solve kiya.

### Din 1–2 — quality fixes jo testing se mile
- Clip A ka audio video se chhota tha → woh hissa silence nahi gina ja raha tha → fix.
- "Um" filler wapas jud jaata tha → fix. "beat sync cuts" se fast cuts on.
- Reviewer ka andha spot: LLM ki galti ko LLM ke hi intent se check kar raha tha → ab independent keyword intent.
- Reviewer bina maange add ki gayi cheezon (transitions, music) pe bhi points kaatta hai.

### Din 3 (5 Oct) — Ollama hatao, production-ready
- Aapke kehne pe **Ollama poori tarah hataya**. AI model ab backend ke andar chalta hai: Hugging Face ka free
  **Qwen2.5 (Apache-2.0)**, ONNX Runtime pe, CPU pe — koi alag server, API key ya GPU nahi.
  - `llama-cpp-python` try kiya — Smart App Control ne block kiya, isliye Microsoft-signed ONNX Runtime.
  - 0.5B model: 10 mein 5 sahi; 1.5B: 10 mein 7 sahi. `LLM_REPO=auto` → RAM ≥3.5 GB free ho to 1.5B, warna 0.5B.
  - **Keyword guard** (model jo chhode, keywords bharte hain) + **evidence gate** (model jo bina saboot add kare,
    hata diya jaata hai). Example: 0.5B ne "9:16" ko 9 second samjha tha → 1.1 sec ka video bana tha → pakda, fix kiya.
  - Hinglish samajh: "gaana daal do", "garam rang", "khamoshi hata do", "ulta chalao", "ghuma do", "awaaz band karo".
- Production: Dockerfile + docker-compose (models image ke andar), optional **API key** auth, CORS config,
  model warm-up, `cutmind.prefetch`. Mobile app mein API key setting; share link se key kabhi leak nahi hoti.

### Din 3 — aapke asli videos pe test
- Aapne bataya "kaam nahi kar raha". Check kiya: kaam kar raha tha par **bahut slow** tha (3–7 min) aur screen pe
  queue/progress saaf nahi dikhta tha. Wajah: aapki clip 1080p 60fps MJPEG `.avi` (385 MB) + laptop pe <1 GB free RAM.
- Fix: render ka join bina re-encode, 60fps ko pehle 30 pe girana, ultrafast intermediates (render 139s → 55s);
  app mein "waiting — 1 edit(s) ahead", "Elapsed 1:05", "Took 1:21".

### Din 3–4 — aur tez + aapke diye repo ke saare FFmpeg operations
- **Proxy files**: upload hote hi halki 720p copy + analysis background mein. Render 43s → 22–25s, analysis 118s → 45s.
- **Whisper**: 50–60s → 6–9s; aapki clip ke shor pe "पादे पादे…" jaisa kachra likh raha tha — ab filter hota hai.
- **Bug**: audio peak level galat naapa ja raha tha (normalise ke baad) → fix.
- `HariharanElancheliyan/ai-video-editor` ke saare operations **apne code se** banaye (us repo ka license nahi hai, isliye
  code copy nahi kiya): rotate, flip/mirror, reverse playback, fps, gamma, sepia, vignette, sharpen, blur, mute,
  louder/quieter, audio fade, text watermark, idle/frozen hisse hatana, GIF + MP3 export.
  **Bug**: GIF/MP3 final output ke saath copy nahi ho rahe the → test ne pakda → fix.

### Din 4 (6 Oct) — Stanley jaisa studio
- Aapka Stanley link login ke peeche tha (password main nahi daal sakta); aapke **screenshot** se banaya.
  Unka naam/logo copy nahi kiya — layout aur kaam karne ka tareeka same, naam **CutMind Studio**.
- **Animated gradient "graphic tracks"** (FFmpeg `gradients` + mask): chamakti glow border, colour wash, lower bar.
- **3 looks**: Midnight Drift (dark blue drift), Violet Authority (blue-violet), Cyan Kinetic (cyan-indigo glow).
- **"edit like a pro" = 3 versions, ranked best first**; har version Reviewer se check; "Use this" se chuno.
- **Studio layout (web, ≥1024px)**: top bar (aspect, Fit, Share, Export MP4/GIF/MP3), icon rail (Media, Images, Sounds,
  Captions, Text, Overlays, More), media panel ("Ready" badges), glowing preview, agent chat (steps, failures,
  versions), multi-track timeline (text track, purple graphic tracks, filmstrip + waveform wala main track, playhead).
- Aapke "cat dog" project pe chala ke dekha: 3 versions (15.0s, 1280×720) bane, studio mein sab dikhe, "Use this" kaam kiya.

---

## 3. Abhi ke test results (asli, 6 Oct)

| Kya | Result |
|---|---|
| Backend pytest (unit + integration asli FFmpeg ke saath + failure tests) | **170 / 170 pass** |
| Mobile typecheck / lint | pass / pass |
| Mobile Jest | **16 suites, 93 / 93 pass** |
| Mobile web build | pass |
| Real model (1.5B) e2e, 15 prompts | 15/15 pass (5 Oct run) — LLM ne 14 mein 8 jobs mein galti ki, guards ne sudhaari |
| Real model auto/0.5B e2e | 15/15 pass (5 Oct run) |
| Live: aapke clips pe studio + 3 versions | chala, dekha (6 Oct) |

Har output video ko ffprobe se naapa jaata hai (duration, size, audio, poora decode) aur frames/audio se check:
captions sach mein dikhte hain, warm rang sach mein garam hai, silence sach mein hata, fade sach mein kaala se
shuru hota hai, rotate/flip/sepia/vignette/blur/sharpen/mute/fade/watermark/GIF/MP3 sab pixel/audio level pe verify.

---

## 4. NOT TESTED (sach)
- **Docker image** — Docker is PC pe installed nahi.
- **Android/iOS app** — Android SDK/emulator nahi.
- **Asli phone footage ki variety** (4K, HEVC, lambi clips) — sirf generated media + aapki 2 clips.
- **Bahut saare users ek saath** — ek waqt pe ek edit (queue).
- Real-model e2e (1.5B / auto) 5 Oct ke code pe chale the; uske baad ke features (proxy, naye ops, styles)
  mock planner ke saath test hue hain, real model ke saath poora e2e dobara nahi chala.

## 5. Known limitations
1. Is laptop pe RAM kam hai → 1.5B model slow (1–2 min/prompt); 0.5B tez par kam samajhdar. Server pe 4 GB+ RAM rakhein.
2. Akela AI model bharosemand nahi; sahi output keyword rules + guard + evidence gate se aata hai.
3. Aapki clip mein whisper ko saaf speech nahi milti → captions nahi bante (Reviewer isse sahi fail dikhata hai).
4. Studio mein split/duplicate/delete/undo/redo/mic abhi sirf dikhte hain (placeholder); dropdown bahar click se band nahi hota.
5. "Highlights" sirf clips ka order badalta hai; ek clip ke andar best moment nahi chunta.

## 6. Kaise chalayein
```bat
run-all.bat
```
App: http://localhost:8081 (badi window pe Studio layout) · API docs: http://localhost:8000/docs
Server pe: `cp .env.example .env` (API key daalo) → `docker compose up -d --build`.

## 7. Aapke PC pe maine kya install kiya
- FFmpeg (winget), Python packages (`backend/.venv`), npm packages (`mobile/node_modules`).
- Hugging Face models cache mein (~3.2 GB: Qwen2.5 1.5B q4 + 0.5B q4 + 0.5B int8 (testing ke waqt) + whisper tiny).
- **Ollama + qwen2.5:3b (~1.9 GB) abhi bhi installed hai** — ab use nahi hota; bolo to uninstall kar dunga.
