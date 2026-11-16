# Driftspace — Architecture Audit (Milestone 1)

Honest audit of the **existing** Driftspace app before building the interaction
engine. Nothing here is aspirational — it describes what is in the repo today.

## 1. Stack & entry points

- **Zero runtime npm deps.** No bundler, no React. Plain ES modules in the
  browser + a hand-rolled Node server. (So "package.json / Three.js version"
  from the spec: there is no package.json for the app; Three.js **r160** is
  **vendored** at `public/vendor/three.module.js`, loaded via an import map.)
- **Server:** `social-app/server.js` — Node `http` + a hand-written **RFC 6455
  WebSocket** server (no `ws` dep). Authoritative state. Static file server.
- **Persistence:** `social-app/db.js` — **SQLite** via Node's built-in
  `node:sqlite` (users, avatars, privacy, friends, rooms, sessions).
- **Client:** `public/index.html` + `public/app.js` (scene/camera/input/net/UI/
  rooms) + `public/style.css`.
- **Avatar layer:** `public/avatarController.js` (procedural ↔ custom swap +
  fallback), `public/avatar.js` (original procedural humanoid + emotes),
  `public/rpmAvatar.js` (loads **GLB / VRM / FBX**, material upgrade, animation
  drivers, emotes, paired-role poses).
- **Character Studio:** `public/studio.html` (neutral 3-point-light preview).
- **Vendored:** three r160, GLTFLoader (+BufferGeometryUtils), @pixiv/three-vrm,
  FBXLoader (+fflate, NURBSCurve/Utils).
- Launch: `.claude/launch.json` entry `driftspace` → `node social-app/server.js`
  (port 8790). Also `social-app/README.md`, `BACKEND-INFRA-PLAN.md`.

## 2. Existing features (what works today)

| Area | Status |
|---|---|
| Rooms: lobby + selectable rooms (Neon Plaza, Driftwood Lounge, Skylight Garden, Mono Studio, **Midnight Romance Penthouse**) + user-created rooms | working |
| Avatars: original procedural humanoid; upload/select **GLB/VRM/FBX**; first real character = **Athletic_male.fbx** (default) | working |
| Movement: click-to-move + **WASD/arrows**, **Shift = run**, camera-relative, third-person orbit camera, drag-to-look, server-authoritative + interpolation | working |
| Animation: idle/walk/run — embedded clips via `AnimationMixer` (FBX/Soldier) OR an original procedural driver (procedural/VRM) with crossfade weights | working |
| Text chat: per-room, 3D speech bubbles | working |
| Emotes/poses: wave, clap, dance, sit, hug, cheer, cool, think — broadcast to room | working (procedural/VRM; **not** on embedded-clip FBX) |
| Paired poses: hug, slow dance, hold hands, high five — invite→accept, server positioning, sync, cancel-on-move | working (non-sexual only) |
| Presence privacy: Everyone/Friends/Nobody, **server-enforced** (room id never sent when hidden) | working |
| Friends: mutual friends | working |
| Customization: body type (feminine/curvy/neutral/athletic/male), skin, hairstyle, outfit (+ swinging dress), colors — persisted | working |
| Penthouse furniture collision (circular footprints) + click-a-seat to sit | working |
| Character Studio preview (front/side/back/face/360, Idle/Walk/Run, bg swap) | working |

## 3. Character assets & skeleton compatibility

- `public/models/characters/Athletic_male.fbx` — Ara 3D Gen export, binary FBX
  7400, ~9.9 MB, **rigged** (92 deformers), **embedded textures** (PNG/JPG), and
  **embedded Idle/Walk/Run** clips. Skeleton bones normalize to standard
  humanoid names: hips, spine, spine1/2, neck, head, left/rightShoulder,
  left/rightArm, left/rightForeArm, left/rightHand, left/rightUpLeg,
  left/rightLeg, left/rightFoot — **Mixamo-compatible**, so retargeting and IK
  mapping are feasible.
- Furniture (CC-BY, Wayfair): `models/furniture/ChairDamaskPurplegold.glb`,
  `GlamVelvetSofa.glb` (see `CREDITS.md`).
- **Bone naming is NOT uniform across rigs:** procedural avatar uses its own
  names; VRM uses `leftUpperArm` etc.; FBX/Mixamo uses `LeftArm`. The code
  already normalizes names (`norm()` in rpmAvatar.js), which is the right
  foundation for a data-driven, non-hardcoded engine (spec rule 9/10).

## 4. "Missing skin / black patches" (spec Phase One) — already diagnosed & fixed

Root cause (diagnosed in-browser, not guessed): the FBX imported as
`MeshPhongMaterial`, and the transparent skin-detail/hair/brow/lash cards had
**sRGB-tagged `alphaMap`s with no `alphaTest`**, so dark areas drew as opaque
black over the skin. Fix (in `upgradeFBXMaterial`, rpmAvatar.js): convert to
`MeshStandardMaterial`, sRGB colour maps / **linear** normal & alpha maps,
`alphaTest` on the cards (hair 0.12 so it isn't clipped bald), realistic
per-material roughness, metalness 0, scene-environment IBL. **No flat material
was used to hide anything** (spec rule 7 respected). Verified in the Character
Studio under neutral lighting.

## 5. Multiplayer

- Authoritative Node WS server owns live state and validates every intent.
- Per-room broadcast; position/rotation/emote sync; client-side interpolation.
- Paired poses already follow **initiator requests → target accepts → server
  positions both → broadcasts shared pose**, with cancel on move/leave/disconnect
  and identity-checked reconnect handling. This is a solid base for the spec's
  authority rules; what's missing is a **shared interaction *timeline*** and the
  formal phase state machine (below).

## 6. Performance (target: i5 / 8 GB / iGPU)

- WebGL2; a few point lights per room (kept ≤4 after a shader-uniform fix in the
  penthouse). The FBX character is heavy (~148k tris incl. the velvet sofa).
- Concerns for the engine: FBX load ~6 s; no LOD; no distance-based update
  throttling; procedural emotes rebuild per frame. These are addressed in later
  milestones (Phase Twelve).

## 7. Gap analysis vs the interaction-engine spec

| Spec phase | Today | Gap |
|---|---|---|
| 0 Audit | — | **this doc** |
| 1 Character validation | ad-hoc material diagnosis | **formal validator util (this milestone)** |
| 2 Free movement engine | WASD+run+click-move, orbit cam | no formal **state machine**, no backward/strafe/crouch as distinct states, no gravity/jump |
| 3 Animation engine | mixer + procedural drivers + crossfade | no **metadata registry**, no retargeting layer, no priorities |
| 4 Two-char interaction | hug/dance/hold/high-five | no **registry schema**, no carry/lift, no approach/align phases; **intimacy items excluded** |
| 5 Synchronized interaction | invite→accept→position→sync | teleport-positions (no walk-approach), no **shared timeline / phase SM** |
| 6 IK | none | needs a lightweight CCD/two-bone solver |
| 7 Physics/collision | room bounds + penthouse furniture circles | no capsule engine; no generic surface/interaction-point system |
| 8 AI command controller | none | needs a **local deterministic parser** → structured action request |
| 9 Interaction UI | emote bar + pair bar + atmosphere bar | needs structured selection/menu/feedback |
| 10 Multiplayer sync | authoritative WS, paired invite/accept | needs shared timeline + stale/duplicate rejection formalized |
| 11 Asset/anim library | ad-hoc presets | needs a **data-driven registry** |
| 12 Performance | basic | LOD, throttling, pooling |
| 13 Testing | manual in-browser | add unit tests for SM/registry/parser |

## 8. Proposed implementation plan (milestones) & risks

- **M1 (this):** audit + character validation utility + honest status.
- **M2:** movement **state machine** (idle/walk/back/strafe/run/turn/crouch/sit),
  acceleration/deceleration, over the existing controller — additive, no rewrite.
- **M3:** **AnimationController** with per-clip metadata + a bone-name mapping
  table (data-driven) + crossfade/priority; wrap existing drivers.
- **M4/M5:** **InteractionRegistry** (JSON-driven) + a phase **state machine**
  (IDLE…COMPLETED/CANCELLED/FAILED) + **walk-approach & align** before pose +
  **shared timeline** over WS. Social/non-sexual set only.
- **M6:** lightweight **CCD/two-bone IK** for hands/feet/look-at, gated by a
  capability check (disable + report if bones missing — spec rule).
- **M7:** generalize collision to capsules + **environment interaction points**.
- **M8:** local **AI command parser** → validated structured action (no paid API,
  no data leaves the server).
- **M9:** UI, perf (LOD/throttle/pool), regression tests.

**Risks / backward-compat:** the FBX uses embedded clips → emotes/paired poses
don't drive it yet (known limitation); the engine must therefore also support a
procedural-override path on embedded-clip avatars. Everything is additive behind
new modules; existing rooms/chat/privacy/multiplayer stay untouched. No Blender
is required to run the app (spec rule 12). **Intimacy/kissing/cuddling paired
interactions are intentionally excluded** per the project's standing rule.
