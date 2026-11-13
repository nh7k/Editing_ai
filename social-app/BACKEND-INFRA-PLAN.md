# Driftspace — Backend & Infrastructure Plan

Pragmatic, runnable architecture for an original 3D avatar social app. The goal
is a real authoritative realtime backend with persistence, auth, and
server-enforced presence privacy — not enterprise overkill. It scales from a
single `node server.js` to multiple room servers behind a pub/sub bus without
rewrites.

## 1. Components

```
                         ┌──────────────┐
  Browser (Three.js) ──► │  HTTP + WS    │  authoritative realtime server
   - renders room        │  server.js    │  (rooms, movement, chat, emotes)
   - sends intents       └──────┬───────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                      ▼
   ┌────────────┐       ┌───────────────┐      ┌───────────────┐
   │  Database  │       │ Presence/Privacy│     │ Avatar/asset  │
   │  (SQLite → │       │   service       │     │ storage + CDN │
   │  Postgres) │       │ (server-enforced)│    │ (/avatars, S3)│
   └────────────┘       └───────────────┘      └───────────────┘
```

- **Realtime server** — the authoritative source of truth for live state
  (socket → user, positions, current room, current emote). Validates every
  client intent (bounds, lengths, formats). Today: one Node process with a
  hand-rolled WS server. Horizontally: many **room servers**, each owning a set
  of rooms; a **pub/sub bus** (Redis) relays presence + cross-room lookups.
- **Database** — durable state (users, avatars, friends, privacy settings,
  sessions). Start with **SQLite** (`node:sqlite`, zero external service);
  the data layer is a thin module so swapping to Postgres later is localized.
- **Presence / room-location privacy service** — decides, per viewer, whether a
  target user's room may be revealed (Everyone / Friends / Nobody). Pure
  server-side; a hidden location is never serialized to a disallowed client.
- **Avatar/asset storage + CDN** — user `.vrm`/`.glb` uploads. Today: stored on
  disk under `data/avatars/` and served from `/avatars/*`. Production: object
  storage (S3/R2) behind a CDN; the DB keeps the URL.
- **Auth/session** — a username (+ optional passphrase) maps to a user row; the
  server issues an opaque session token (httpOnly cookie) stored in the DB.

## 2. Data model

```
users(
  id TEXT PRIMARY KEY,            -- stable user id
  name TEXT,                      -- display name (unique, case-insensitive)
  pass_hash TEXT,                 -- nullable (guest) — scrypt hash if set
  created_at INTEGER
)
avatars(
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  body_color TEXT, hair_color TEXT, outfit TEXT, outfit_color TEXT,
  avatar_url TEXT                 -- '' = procedural; else .vrm/.glb URL
)
privacy(
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  visibility TEXT                 -- 'everyone' | 'friends' | 'nobody'
)
friends(                          -- one row per direction; mutual = both rows
  user_id TEXT, friend_id TEXT,
  PRIMARY KEY(user_id, friend_id)
)
sessions(
  token TEXT PRIMARY KEY, user_id TEXT, created_at INTEGER, expires_at INTEGER
)
-- rooms are static defs in code; live membership/positions stay in memory
-- (ephemeral by nature). Only durable facts live in the DB.
```

Live-only state (NOT in the DB): socket handles, x/z/rot, current room, current
emote, presence fan-out. This is the correct split — durable vs ephemeral.

## 3. Presence / room-location privacy (server-enforced)

The one invariant: **a user's current room id is only ever sent to a viewer the
owner's setting allows.** Implemented as `visibleRoomFor(targetId, viewerId)`:

- `everyone` → room; `nobody` → null; `friends` → room iff mutual friends.
- The online presence list is built **per recipient** (`presenceFor(viewerId)`),
  masking each target's room to `null` when not allowed.
- The explicit lookup (`whereis`) uses the same function.
- There is deliberately **no** endpoint that returns a hidden user's location,
  and none will be added.

At scale: the privacy decision stays on the server that owns the *target's*
presence; cross-server lookups go through the pub/sub bus and return only an
allowed/!allowed answer, never the raw room to the edge.

## 4. Scaling path (when one process isn't enough)

1. **Shard rooms across servers.** Each room server owns N rooms; a lightweight
   router/directory maps room→server. Clients connect to the server for their
   room.
2. **Pub/sub bus (Redis).** Presence changes and friend/privacy updates publish
   to the bus; servers subscribe to keep the online list and privacy-aware
   presence current across shards.
3. **Stateless auth.** Sessions live in the DB (or Redis), so any server can
   validate a token.
4. **Assets to a CDN.** Move `/avatars` to object storage; DB stores the URL.
5. **DB swap.** SQLite → Postgres by changing only the data-layer module.

## 5. Execution plan (incremental, each a working slice)

- [x] In-memory authoritative server (rooms, movement, chat, emotes).
- [x] Avatar upload + serving (`/api/upload-avatar`, `/avatars/*`).
- [x] Server-enforced Everyone/Friends/Nobody privacy + mutual friends.
- [ ] **Slice 1 — SQLite data layer.** Introduce `db.js` (node:sqlite) with the
      tables above; move profiles/avatars/privacy/friends off the JSON file.
      Keep the WS protocol unchanged.
- [ ] **Slice 2 — Auth/session.** Username (+ optional passphrase, scrypt),
      opaque session token in an httpOnly cookie, `sessions` table; the WS
      `hello` authenticates by token.
- [ ] **Slice 3 — Friends service** backing "Friends only" fully from the DB
      (requests/accepts persisted), already partly in place.
- [ ] **Slice 4 — Config for Redis pub/sub** (feature-flagged) so multiple room
      servers can run; no-op when unset (single-process default).

Each slice lands on the branch with its own commit and a short status note.
