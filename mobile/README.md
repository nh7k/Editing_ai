# CutMind mobile

Expo (SDK 57) + React Native + TypeScript client for the CutMind multi-agent video editor.
It is UI only: it uploads clips, sends prompts, polls agent jobs and plays the rendered output.
All video processing happens on the backend (`../backend`). The REST contract is in `../ARCHITECTURE.md`.

## Screens

| Screen | What it does |
|--------|--------------|
| Projects (tab) | List (`GET /projects`), create (`POST /projects`), pull to refresh |
| Import | Gallery picker (`expo-image-picker`, videos, multi-select), upload with progress (`POST /projects/{id}/clips`, field `files`), thumbnails, delete clip |
| Editor | `expo-video` preview of `/projects/{id}/output`, Skia + Reanimated timeline (from `/plan`, or clip durations), draggable playhead, prompt chips, mic placeholder, send → `POST /projects/{id}/edit` |
| Agent Activity (sheet) | Polls `GET /jobs/{id}` every 1.5 s until done or failed: progress, per-agent status/score/attempts, review checks, match %, live log, error |
| Export | Resolution 480/720/1080 and aspect 9:16/1:1/16:9 → re-runs the last prompt; Save / Share; thumbs up/down + comment → `POST /jobs/{id}/feedback` |
| Scoreboard (tab) | `GET /agents/scoreboard`, ranked by points, avg score, last delta (mint +, coral −), recent lessons |
| Settings (tab) | Backend URL + optional API key (persisted with AsyncStorage), "Test connection" (`GET /health`: ffmpeg, whisper, AI model status, auth required/off) |

## Setup

```bash
cd mobile
npm install          # postinstall copies canvaskit.wasm into public/ (needed for Skia on web)
```

npm 11 asks before running install scripts. `package.json` already allows the
`@shopify/react-native-skia` script, which copies the prebuilt native Skia libraries
from `node_modules`. If you see an `allow-scripts` warning, run
`npm approve-scripts @shopify/react-native-skia` and then `npm install` again.

## Run

### Web (quickest way to try it, no emulator needed)

```bash
npm run web          # expo start --web, then open the printed URL
npm run build:web    # static build into dist/ (expo export --platform web)
```

The backend must allow CORS from the web origin (for example `http://localhost:8081`).
Otherwise browser requests fail with "Cannot reach the backend".

### Android: development build (Expo Go is NOT supported)

The app uses native modules that Expo Go doesn't include (`@shopify/react-native-skia`,
`expo-dev-client`, `expo-video`, and others). You need a development build:

1. Install Android Studio with the Android SDK, platform tools and an emulator (or plug in a phone with USB debugging),
   and set `ANDROID_HOME`. Use JDK 17.
2. `npm run android`. This runs `expo run:android`, which generates `android/`, builds the debug APK and installs it.
3. After that, `npm start` (`expo start --dev-client`) serves JS to the installed dev build.

You can also build in the cloud with `npx eas-cli@latest build --profile development --platform android`.

## Backend URL

Open **Settings**, enter the URL, tap **Test connection**, then **Save**. The URL is stored on the device.

| Where the app runs | URL to use |
|--------------------|------------|
| Web on the same PC | `http://localhost:8000` (the default) |
| Android emulator | `http://10.0.2.2:8000` (the emulator's alias for the host PC) |
| Real phone on the same Wi-Fi | `http://<PC LAN IP>:8000`, e.g. `http://192.168.1.20:8000` (start the backend with `--host 0.0.0.0` and allow port 8000 through the firewall) |

Cleartext HTTP is enabled for Android (`expo-build-properties` → `usesCleartextTraffic`) so the app can reach a local backend.

**Test connection** shows the backend's `GET /health`: ffmpeg and whisper availability, the planner's
**AI model** (the backend runs a small Hugging Face model in-process; Ollama is no longer used):

| `llm.available` | Shown as |
|-----------------|----------|
| `null` | `rules only (mock planner)` |
| `true` | `ready · <model>` |
| `false` | `downloading / not cached · <model>` (the backend is still fetching the model) |

and **auth**: `required` when the backend has `CUTMIND_API_KEY` set, otherwise `off`.

## API key (optional)

If the backend is started with `CUTMIND_API_KEY=<key>`, every request except `/health` and `/docs`
must carry that key. Enter it under **Settings → API key (optional)** and tap **Save API key**
(leave it empty when the backend has no key). It is stored on the device next to the backend URL.

- API calls and clip uploads send it as the `X-API-Key` header.
- The output video and clip thumbnails are loaded by `<video>`/`<Image>`, which cannot send headers,
  so those URLs get `api_key=<key>` as a query parameter instead.
- A missing or wrong key gives a 401; the app shows "Missing or wrong API key." with a hint to set it in Settings.
- The key is never logged. Note that on web, **Share** copies/shares the video link, which then includes the key.

## Quality checks

```bash
npm run typecheck    # tsc --noEmit (strict)
npm run lint         # expo lint (eslint-config-expo, flat config)
npm test             # jest (jest-expo preset + @testing-library/react-native)
npm run build:web    # web compile check
```

The Jest tests mock native-only pieces in `jest.setup.ts`: the Skia `Timeline` component (its
layout math is tested in `timelineModel.test.ts`), `expo-video`, AsyncStorage, safe-area,
`expo-media-library` and `expo-sharing`.

## Layout

```
App.tsx                      fonts (Inter), gesture root, settings bootstrap, navigation
src/api/types.ts             contract types (Project, Clip, Job, AgentStat, EditPlan, ...)
src/api/client.ts            typed client: one function per endpoint, timeouts, ApiError
src/store/settings.ts        backend URL + API key store (AsyncStorage + useSyncExternalStore)
src/navigation/              root native-stack + bottom tabs
src/screens/                 Projects, Import, Editor, Export, Scoreboard, Settings
src/components/              Card, Button, Chip, ProgressBar, StatusPill, Empty/Error/Loading states,
                             ChatInput, VideoPreview, AgentActivitySheet
src/components/timeline/     SkiaTimeline (Skia + Reanimated + Gesture Handler),
                             Timeline.tsx (native) / Timeline.web.tsx (lazy CanvasKit via WithSkiaWeb)
src/utils/media(.web).ts     save/share: file-system + media-library + sharing on native; <a download> / Web Share / clipboard on web
__tests__/                   Jest tests
```
