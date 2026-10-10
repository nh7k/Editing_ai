# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `npm run build:web`: "Unable to resolve module ../components/studio/MediaPanel" (file exists) | the project is in OneDrive; "Files On-Demand" placeholders look like symlinks to Node and Metro skips them | keep the folder outside OneDrive, or right-click → *Always keep on this device*, then re-save the files (`node -e` rewrite used here, see PROJECT_AUDIT #14) |
| Jest tests time out at random | too many workers for the free RAM | `maxWorkers: 25%` is set in package.json; close other apps |
| "Clip analysis failed: loudness.lufs …" | silent audio track (fixed in this version) | update; old caches are read correctly |
| Captions check fails: "nobody speaks in these clips" | the footage has no speech | expected — nothing to caption; not retried |
| Hindi captions are poor | Whisper `tiny` is weak at Hindi | `WHISPER_MODEL=small` (slower) |
| 🎤 says "Microphone permission was denied." | browser blocked the mic | allow the mic for localhost (Chrome: lock icon → Microphone) |
| A job was running when the PC restarted | — | it resumes from its last finished step on the next server start |
| Smart App Control blocks a DLL (numba, llama-cpp, PyAV) | Windows policy on unsigned DLLs | already worked around (pinned numba, ONNX Runtime instead of llama-cpp, PyAV stub) |
| Edits are slow | 4K sources, low free RAM | proxies are made at upload — wait for them; one version instead of 3; close the preview while rendering |
| `GET /capabilities` shows `gpu: false` | no NVIDIA/DirectML GPU | normal; everything except AI generation works on CPU |
