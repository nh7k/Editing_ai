# Driftspace

An original 3D avatar social-chat web app — same genre and mechanics as a 3D
avatar hangout (3D rooms, movable avatars, live text chat, dress-up, and
room-location privacy), but **entirely original**: original brand, original
avatar designs, original room geometry, and original code. No third-party
assets, models, textures, sounds, or branding are used or copied.

It is a real, runnable multiplayer app: an authoritative Node server holds all
state, clients talk to it over WebSocket, and the browser renders the 3D world
with Three.js.

## Run it

```bash
node social-app/server.js
```

Then open <http://localhost:8790> in two browser tabs (or two machines on the
same network). Pick a name, join the same room, and you'll see each other move
and chat in real time.

It's also wired into the repo's launch config as **`driftspace`** (port 8790),
so the Claude Code preview / `launch.json` runners can start it directly.

- **Zero dependencies.** The WebSocket server is implemented from scratch on
  Node's `http`/`net`/`crypto` (RFC 6455). Three.js is vendored at
  `public/vendor/three.module.js`, so the app also runs fully offline.
- **Node 18+** (developed on Node 24).

## What's implemented

1. **Rooms** — a lobby with a live room list and four original 3D rooms
   (Neon Plaza, Driftwood Lounge, Skylight Garden, Mono Studio). Each is an
   original space: floor, walls, accent trim, a central table with seats, and
   corner pillars, themed with its own palette and environment lighting.
2. **Avatars + movement** — every connected user is an **original rigged
   humanoid** (see below). Click-to-move or `WASD`/arrows; positions are
   authoritative on the server and synced to everyone in the room over
   WebSocket, with client-side interpolation for smoothness.
3. **Text chat** — per-room real-time chat with a chat log and floating 3D
   speech bubbles above avatars.
4. **Avatar customization** — a dress-up panel for skin tone, hair color,
   outfit style (tee / tank / hoodie / jacket / dress — the outfit changes the
   silhouette) and outfit color. Saved per user and **persisted to disk**
   (`data/profiles.json`), broadcast live to others in the room.
5. **Room-location privacy — server-enforced** — set *who can see which room
   you're in*: **Everyone / Friends only / Nobody**. The decision is made on
   the **server, per recipient**: a hidden user's room id is **never sent** to
   a client that isn't allowed to see it (verified at the wire level — the
   `presence` and `whereis` messages carry `roomId: null` for a hidden user).
   There is deliberately **no** endpoint that unmasks a hidden user.
6. **Friends** — mutual friends system (both must add each other), backing the
   "Friends only" visibility.

## Avatars: bring your own realistic / anime character

The "robot-free" high-quality path. Each user can use a real rigged character,
and it gets the room's PBR lighting + shadows, walks/idles/runs with the
movement sync, and (for VRM) its own hair/skirt **spring-bone physics**. Set it
in **Appearance → Custom 3D avatar**:

- **Upload your own `.vrm` or `.glb`** — the best option. It's uploaded to your
  own server (`/avatars/…`), so it persists and other players see it too. Works
  offline.
- **Anime (VRoid):** make a character in **[VRoid Studio](https://vroid.com/en/studio)**
  (free) — pick the body, face, hair, outfit/dress you want — then
  *Export → VRM* and upload it. This is how you get the anime look (pink hair,
  frilly dress, etc.) as **your own original character**.
- **Realistic (Ready Player Me):** the "✨ Create a realistic avatar" button
  opens the RPM creator; finish it and the photoreal avatar loads automatically.
- **Paste a `.vrm` / `.glb` URL** (Advanced) for an already-hosted avatar.

If no custom avatar is set, or it can't load (offline / bad file), the app falls
back to the original procedural avatar below so it never breaks.

**Rigs & animation.** `.vrm` uses the VRM normalized humanoid; `.glb` uses its
own embedded clips when present (idle/walk/run via `AnimationMixer`), otherwise
an original procedural idle/walk/run cycle mapped onto the standard humanoid
bones. `three` + `GLTFLoader` + `@pixiv/three-vrm` are all vendored locally.

> **On copyrighted characters:** make or import your *own* character. The app
> deliberately doesn't ship or clone copyrighted game/anime characters (e.g. a
> specific Genshin character). VRoid Studio lets you build a character in that
> same style that is genuinely yours.

## The original procedural avatar (fallback)

`public/avatar.js` builds the humanoid procedurally — no external models:

- A ~19-bone skeleton with human proportions, driving a **`THREE.SkinnedMesh`**.
  Because the geometry is generated in code, skin weights are authored exactly,
  with **cross-joint blending** so elbows/knees/hips deform smoothly.
- Separate **PBR materials** (`MeshStandardMaterial`) for skin, outfit, hair
  and shoes.
- Hand-authored **idle** and **walk** animation clips (quaternion keyframe
  tracks + a hips bob), cross-faded by an `AnimationMixer` based on movement.
- Rendered with **ACES filmic tone mapping**, an **image-based-lighting**
  environment (PMREM from a per-theme gradient), a shadow-casting key light with
  **soft PCF shadows**, plus hemisphere + accent fill lights.

All avatars are generic, original humans. No real or copyrighted character is
modeled.

## Architecture

```
social-app/
  server.js            Authoritative state: HTTP static server + hand-rolled
                       WebSocket server. Owns rooms, positions, chat, profiles,
                       friends, and all privacy decisions.
  public/
    index.html         UI shell (lobby, HUD, chat, panels)
    style.css
    app.js             Scene, camera, input, networking, interpolation, UI
    avatar.js          Procedural rigged humanoid + animations
    vendor/three.module.js   Vendored Three.js (r160)
  data/profiles.json   Runtime persistence (gitignored)
```

### Protocol (client → server)
`hello`, `joinRoom`, `leaveRoom`, `move`, `chat`, `customize`,
`setVisibility`, `addFriend`, `whereis`.

### Protocol (server → client)
`welcome`, `rooms`, `roomState`, `joined`, `left`, `moved`, `chat`,
`appearance`, `profileUpdated`, `presence`, `whereisResult`, `friendResult`.

The server validates and clamps every input (room bounds, string lengths,
color formats) and prunes stale state on disconnect/reconnect.

## Privacy guarantee

The server computes `visibleRoomFor(target, viewer)` for **every** place a room
location could leak (the `presence` broadcast is built per-recipient, and the
`whereis` lookup is resolved the same way). If the owner's setting doesn't allow
the viewer, the room id is replaced with `null` before anything is sent — the
real room never leaves the server. This project will not add any feature that
reveals or de-anonymizes a user who has hidden their location.
