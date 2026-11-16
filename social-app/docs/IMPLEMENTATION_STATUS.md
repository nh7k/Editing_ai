# Driftspace Interaction Engine — Implementation Status

Honest, per-phase status against the interaction-engine spec. Labels:
**COMPLETE** (implemented & tested) · **PARTIAL** (implemented, not fully
verified) · **BLOCKED** (needs a missing asset/dep) · **NOT STARTED**.

_Last updated: Milestone 1 (audit + character validation)._

## Scope note — excluded by project rule
The spec's Phase-Four **"Romantic: consensual kissing, cuddling"** intimate
paired interactions are **intentionally excluded** (standing project rule: paired
interactions stay non-sexual). The social set — hug, hold hands, dance, wave,
handshake, high five, help-stand/carry, sit-together — is in scope.

## Milestone / phase status

| Phase | Status | Notes / evidence |
|---|---|---|
| 0 Repository audit | **COMPLETE** | `docs/DRIFTSPACE_ARCHITECTURE_AUDIT.md` |
| 1 Character validation & "black patch" repair | **COMPLETE** | `public/characterValidator.js`; ran on `Athletic_male.fbx` in-browser — raw asset passes mesh/skeleton(69 bones)/skinning(1/1)/all 13 humanoid bones/root+hips/Idle·Walk·Run/height; the only failing check on the **raw** asset is black-patch risk (4 transparent cards w/o alphaTest). **After the app's `loadFBX` material upgrade → `ready:true`, black-patch risk gone, scaled to 1.8 m.** The black-patch fix is already shipped (no flat material used). |
| 2 Free movement engine | **COMPLETE (browser-verified)** | See the M2 verification block below. Velocity accel/decel, speed-driven idle/walk/run, camera-relative WASD, Shift-run, smooth turn, floor alignment, click-to-move — all verified live in Neon Plaza, no console errors. **Still out of M2 scope:** distinct crouch state, gravity/jump. |
| 3 Advanced animation engine | **PARTIAL** | `AnimationMixer` (embedded Idle/Walk/Run) + original procedural driver (VRM/procedural) + crossfade weights. **Missing:** metadata registry, retargeting layer, priorities. Bone-name normalization (`norm()`) is in place (data-driven foundation). |
| 4 Two-character interaction framework | **PARTIAL** | hug / slow dance / hold hands / high five with invite→accept + server positioning + sync + cancel. **Missing:** JSON `InteractionDefinition` registry, carry/lift, approach/align phases. Intimacy items **excluded**. |
| 5 Synchronized interaction system | **PARTIAL** | initiator→target→server-positions-both→broadcast→cancel-on-move/leave/disconnect. **Missing:** walk-**approach** (currently server-positions), formal phase SM (IDLE…COMPLETED), shared **timeline** markers. |
| 6 Inverse kinematics | **NOT STARTED** | planned: lightweight CCD / two-bone for hands/feet/look-at, gated by a per-rig capability check (disable + report if bones missing). |
| 7 Physics & body collision | **PARTIAL** | room bounds + penthouse furniture circular colliders (push-out, sit-safe). **Missing:** capsule colliders, generic surface/interaction-point system, gravity. |
| 8 AI command controller | **NOT STARTED** | planned: local deterministic parser → validated structured action request (no paid API, no data leaves the server). |
| 9 Interaction discovery & UI | **PARTIAL** | emote bar, pair bar (nearby-target), atmosphere bar, accept/decline banner, chat. **Missing:** structured selection/menu/feedback states. |
| 10 Multiplayer | **PARTIAL** | authoritative WS, position/rotation/emote sync, paired invite/accept, authority & reconnect handling. **Missing:** shared timeline + formal duplicate/stale rejection. |
| 11 Animation/asset library | **PARTIAL** | ad-hoc presets (readyAvatars, furniture, paired poses). **Missing:** data-driven registry by category. |
| 12 Performance optimization | **PARTIAL** | WebGL2, ≤4 point lights/room (shader-uniform fix), interpolation. **Missing:** LOD, distance throttling, pooling; FBX ~148k tris + ~6 s load. |
| 13 Testing | **PARTIAL** | manual in-browser verification throughout; the validator is the first automated check. **Missing:** unit tests for SM/registry/parser. |

## M2 live browser verification (Neon Plaza, FBX Athletic_male, 2026-11-16)

**PASSED**
- WASD movement: W forward, S backward, A/D strafe — avatar moves in each case.
- Shift + W/A running: speed reaches the run cap (**5.0**); run pose confirmed
  in a screenshot (clear mid-stride).
- Smooth acceleration & deceleration: sampled speed ramped **0 → 1.8 → 2.39**
  (accel to walk cap) and **5.0 → 0.6 → 0** (decel) — gradual, not instant.
- Idle → Walk → Run → Idle: speed-driven; idle and run poses confirmed visually,
  walk cruise speed 2.39 confirmed numerically.
- Camera-relative movement: avatar travels along the camera's forward/strafe axes.
- Smooth character turning: heading interpolates (rot 2.43 → −0.71 → 1.15 as
  direction changed), no snapping.
- Floor alignment: feet on the floor, **no floating/sinking**.
- Click-to-move (existing): clicked a far floor point → avatar turned and walked
  ~6.3 m to it and stopped (ease-to-stop).
- Materials / black-patch: idle & run screenshots show clean tan PBR skin, **no
  black patches**.
- **No console errors.**

**FAILED**
- None observed in M2 scope.

**NOT TESTED (out of scope here / separate milestones)**
- Furniture collision: a **penthouse-only** feature — Neon Plaza has no
  furniture, so not exercised here; code path unchanged by M2.
- Sit / emotes / paired poses **on the FBX avatar**: these drive procedural/VRM
  avatars but **not** the embedded-clip FBX (pre-existing limitation, not an M2
  change) — see below.

**REMAINING LIMITATIONS**
- Foot-sliding is **reduced** via stride-rate sync (`setSpeed` scales the clip's
  timeScale with speed) but not root-motion-perfect; acceptable visually.
- The default FBX uses embedded Idle/Walk/Run, so emote/sit/paired poses don't
  animate it yet (bones are standard-named → fixable by layering a procedural
  override on the mixer in M3/M4).
- Crouch, gravity and jump are not in M2.

## Known limitations (honest)
- The default FBX character uses its **embedded** Idle/Walk/Run, so the
  procedural **emote bar and paired poses do not animate it** yet (they drive
  procedural/VRM avatars). Its bones are standard-named, so a procedural overlay
  on the mixer can add this (planned in M3/M4).
- `Athletic_male.fbx` is ~9.9 MB (~148k tris with furniture) — heavy for the
  i5/8 GB/iGPU target; perf work is Phase Twelve.
- No Blender is required to run the app (spec rule 12). The separate "City
  Street.blend" world is **BLOCKED** on Blender not being installed (flagged).

## Next milestone
**M2 — movement state machine** (additive over the existing controller):
idle/walk/back/strafe/run/turn/crouch/sit with acceleration/deceleration and
blend, no rewrite of existing camera/room navigation.
