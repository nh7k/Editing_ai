'use strict';
/*
 * Driftspace — authoritative server for an original 3D avatar social-chat app.
 *
 * Zero runtime dependencies: a tiny static HTTP server + a hand-rolled
 * RFC 6455 WebSocket server. The server is the single source of truth for
 * room membership, avatar positions, chat, appearance and presence privacy.
 *
 * PRIVACY MODEL (server-enforced, see presenceFor / handleWhereis):
 *   Each user has visibility ∈ {everyone, friends, nobody} for their CURRENT
 *   ROOM LOCATION. The room id of a user is NEVER sent to a client that is not
 *   allowed to see it. This is decided on the server, per-recipient. There is
 *   deliberately no endpoint that unmasks a hidden user.
 */

const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 8790;
const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_DIR = path.join(__dirname, 'data');
const PROFILE_FILE = path.join(DATA_DIR, 'profiles.json');

// ---------------------------------------------------------------------------
// Original room designs (no third-party assets; just geometry parameters the
// client turns into an original 3D space).
// ---------------------------------------------------------------------------
const ROOM_DEFS = [
  { id: 'plaza',   name: 'Neon Plaza',    theme: 'neon',   floor: '#1b1033', accent: '#ff4fd8', w: 24, d: 24 },
  { id: 'lounge',  name: 'Driftwood Lounge', theme: 'warm',  floor: '#2a211a', accent: '#f0a94b', w: 20, d: 20 },
  { id: 'garden',  name: 'Skylight Garden', theme: 'nature', floor: '#15241a', accent: '#5ad17a', w: 26, d: 22 },
  { id: 'studio',  name: 'Mono Studio',   theme: 'mono',   floor: '#202024', accent: '#8f9bff', w: 18, d: 18 },
];

const AVATAR_PRESETS = {
  bodyColors: ['#f0c27b', '#c98b5f', '#8d5a3c', '#5c3a26', '#e8d5c0', '#b0b7c6'],
  hairColors: ['#2b2b2b', '#6b3e1d', '#c9a227', '#d94f4f', '#4f6fd9', '#a94fd9', '#eeeeee'],
  outfits:    ['tee', 'tank', 'hoodie', 'jacket', 'dress', 'shorts'],
  outfitColors: ['#ff4fd8', '#5ad17a', '#8f9bff', '#f0a94b', '#ff6b6b', '#38bdf8', '#ffffff', '#222222'],
  hairStyles: ['long', 'wavy', 'ponytail', 'bun', 'short'],
  bodies: ['feminine', 'neutral', 'athletic', 'male'],
  // Free ready-made rigged avatars (loaded from their public CDNs, not bundled).
  // The first is the pixiv three-vrm sample — a generic anime avatar for demos.
  readyAvatars: [
    { name: 'Aria (anime)', url: 'https://cdn.jsdelivr.net/gh/pixiv/three-vrm@v3.4.2/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm' },
  ],
};

// ---------------------------------------------------------------------------
// Persistent per-user profiles (appearance + privacy + friends) — SQLite.
// `profiles` is an in-memory cache; SQLite (db.js) is the durable source of
// truth. Writes are debounced and written through per changed user.
// ---------------------------------------------------------------------------
const db = require('./db');
// One-time migration: if an old profiles.json exists and the DB is empty, import it.
(function migrateLegacyJson() {
  try {
    if (Object.keys(db.loadProfiles()).length) return;
    const old = JSON.parse(fs.readFileSync(PROFILE_FILE, 'utf8'));
    for (const [id, p] of Object.entries(old)) db.saveProfile(id, p);
    console.log('Migrated', Object.keys(old).length, 'profiles from profiles.json into SQLite');
  } catch { /* no legacy file */ }
})();
const profiles = db.loadProfiles();

let saveTimer = null;
function saveProfiles() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    for (const [id, p] of Object.entries(profiles)) {
      try { db.saveProfile(id, p); } catch (e) { console.error('saveProfile', e.message); }
    }
  }, 300);
}

function defaultProfile(name) {
  return {
    name: name || 'Guest',
    bodyColor: AVATAR_PRESETS.bodyColors[0],
    hairColor: AVATAR_PRESETS.hairColors[0],
    hairStyle: 'long',
    body: 'feminine',
    outfit: 'tee',
    outfitColor: AVATAR_PRESETS.outfitColors[0],
    avatarUrl: '',                   // Ready Player Me .glb URL (empty => procedural avatar)
    visibility: 'everyone',          // everyone | friends | nobody
    friends: [],                     // array of userIds (mutual once both add)
  };
}

// ---------------------------------------------------------------------------
// Live state
// ---------------------------------------------------------------------------
// clients: userId -> { ws, id, roomId, x, z, rot, lastMove }
const clients = new Map();
// Theme presets for user-created rooms (original palettes).
const THEME_PRESETS = {
  neon:   { floor: '#1b1033', accent: '#ff4fd8' },
  warm:   { floor: '#2a211a', accent: '#f0a94b' },
  nature: { floor: '#15241a', accent: '#5ad17a' },
  mono:   { floor: '#202024', accent: '#8f9bff' },
  ocean:  { floor: '#0f2230', accent: '#38bdf8' },
  rose:   { floor: '#2a1420', accent: '#ff6b9d' },
};

const rooms = new Map(ROOM_DEFS.map(r => [r.id, { def: r, members: new Set(), owner: null }]));
// Load user-created rooms from the database.
try {
  for (const r of db.loadRooms()) {
    rooms.set(r.id, { def: { id: r.id, name: r.name, theme: r.theme, floor: r.floor, accent: r.accent, w: r.w, d: r.d }, members: new Set(), owner: r.owner || null });
  }
} catch (e) { /* db loaded later; rooms added on demand */ }

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
function sanitize(str, max) {
  return String(str == null ? '' : str).replace(/[\u0000-\u001f\u007f]/g, '').slice(0, max);
}
function validColor(c, fallback) {
  return (typeof c === 'string' && /^#[0-9a-fA-F]{6}$/.test(c)) ? c : fallback;
}
// Accept only an https URL to a .glb (Ready Player Me or any glb host); '' clears it.
function validAvatarUrl(u) {
  if (typeof u !== 'string') return null;
  if (u === '') return '';
  if (u.length > 300) return null;
  if (/^\/avatars\/[\w.-]+\.(glb|vrm)$/i.test(u)) return u;                 // uploaded to this server
  return /^https:\/\/[\w.-]+(:\d+)?\/[\w%@./+-]+\.(glb|vrm)(\?[\w=&%.@+-]*)?$/i.test(u) ? u : null;
}

// ---------------------------------------------------------------------------
// Privacy core — decide what room (if any) a viewer may learn about a target.
// Returns the roomId string, or null if hidden from this viewer.
// ---------------------------------------------------------------------------
function visibleRoomFor(targetId, viewerId) {
  const t = clients.get(targetId);
  if (!t) return null;                     // offline → no location
  const prof = profiles[targetId];
  const vis = prof ? prof.visibility : 'everyone';
  if (viewerId === targetId) return t.roomId;       // you always see yourself
  if (vis === 'nobody') return null;
  if (vis === 'everyone') return t.roomId;
  if (vis === 'friends') {
    const theirFriends = (prof && prof.friends) || [];
    const myFriends = (profiles[viewerId] && profiles[viewerId].friends) || [];
    // mutual friendship required
    if (theirFriends.includes(viewerId) && myFriends.includes(targetId)) return t.roomId;
    return null;
  }
  return null;
}

// Build the online-presence list AS SEEN BY one viewer. roomId is masked
// per-target by the privacy rule — a hidden location simply isn't included.
function presenceFor(viewerId) {
  const list = [];
  for (const [id, c] of clients) {
    const prof = profiles[id] || {};
    const room = visibleRoomFor(id, viewerId);
    const myFriends = (profiles[viewerId] && profiles[viewerId].friends) || [];
    list.push({
      id,
      name: prof.name || 'Guest',
      roomId: room,                                   // null => hidden
      roomName: room ? rooms.get(room).def.name : null,
      isFriend: myFriends.includes(id),
      hidden: room === null && id !== viewerId,       // online but location masked
    });
  }
  return list;
}

// ---------------------------------------------------------------------------
// WebSocket framing (RFC 6455, server side, text frames only, small messages)
// ---------------------------------------------------------------------------
const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

function acceptKey(key) {
  return crypto.createHash('sha1').update(key + GUID).digest('base64');
}

function encodeFrame(str) {
  const payload = Buffer.from(str, 'utf8');
  const len = payload.length;
  let header;
  if (len < 126) {
    header = Buffer.from([0x81, len]);
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81; header[1] = 126; header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81; header[1] = 127;
    header.writeUInt32BE(Math.floor(len / 2 ** 32), 2);
    header.writeUInt32BE(len >>> 0, 6);
  }
  return Buffer.concat([header, payload]);
}

// A per-socket parser that accumulates bytes and emits complete messages.
function makeParser(onMessage, onClose, socket) {
  let buf = Buffer.alloc(0);
  let frags = [];
  return function (chunk) {
    buf = Buffer.concat([buf, chunk]);
    while (buf.length >= 2) {
      const b0 = buf[0], b1 = buf[1];
      const fin = (b0 & 0x80) !== 0;
      const opcode = b0 & 0x0f;
      const masked = (b1 & 0x80) !== 0;
      let len = b1 & 0x7f;
      let offset = 2;
      if (len === 126) {
        if (buf.length < 4) return;
        len = buf.readUInt16BE(2); offset = 4;
      } else if (len === 127) {
        if (buf.length < 10) return;
        const hi = buf.readUInt32BE(2), lo = buf.readUInt32BE(6);
        len = hi * 2 ** 32 + lo; offset = 10;
      }
      if (len > 1 << 20) { try { socket.destroy(); } catch {} return; } // 1MB cap
      const need = offset + (masked ? 4 : 0) + len;
      if (buf.length < need) return;
      let payload;
      if (masked) {
        const mask = buf.slice(offset, offset + 4);
        payload = Buffer.alloc(len);
        for (let i = 0; i < len; i++) payload[i] = buf[offset + 4 + i] ^ mask[i & 3];
      } else {
        payload = buf.slice(offset, offset + len);
      }
      buf = buf.slice(need);

      if (opcode === 0x8) { onClose(); return; }         // close
      if (opcode === 0x9) {                               // ping -> pong
        try { socket.write(Buffer.concat([Buffer.from([0x8a, 0]), Buffer.alloc(0)])); } catch {}
        continue;
      }
      if (opcode === 0xa) continue;                       // pong
      if (opcode === 0x1 || opcode === 0x2 || opcode === 0x0) {
        frags.push(payload);
        if (fin) {
          const full = Buffer.concat(frags).toString('utf8');
          frags = [];
          onMessage(full);
        }
      }
    }
  };
}

// Thin wrapper so handlers can .send(obj)
function makeWs(socket) {
  return {
    socket,
    alive: true,
    send(obj) {
      if (!this.alive) return;
      try { socket.write(encodeFrame(JSON.stringify(obj))); }
      catch { this.alive = false; }
    },
    close() {
      if (!this.alive) return;
      this.alive = false;
      try { socket.end(Buffer.from([0x88, 0])); } catch {}
      try { socket.destroy(); } catch {}
    },
  };
}

// ---------------------------------------------------------------------------
// Broadcast helpers
// ---------------------------------------------------------------------------
function broadcastRoom(roomId, obj, exceptId) {
  const room = rooms.get(roomId);
  if (!room) return;
  for (const id of room.members) {
    if (id === exceptId) continue;
    const c = clients.get(id);
    if (c) c.ws.send(obj);
  }
}

function roomSnapshot(roomId) {
  const room = rooms.get(roomId);
  const occupants = [];
  for (const id of room.members) {
    const c = clients.get(id);
    if (!c) { room.members.delete(id); continue; } // prune stale member
    const prof = profiles[id] || {};
    occupants.push({
      id, name: prof.name, x: c.x, z: c.z, rot: c.rot,
      bodyColor: prof.bodyColor, hairColor: prof.hairColor, hairStyle: prof.hairStyle || 'long', body: prof.body || 'feminine',
      outfit: prof.outfit, outfitColor: prof.outfitColor, avatarUrl: prof.avatarUrl || '',
      emote: c.emote || null,
    });
  }
  return { type: 'roomState', room: room.def, occupants };
}

// Push a fresh presence list to everyone (locations masked per recipient).
function pushPresenceAll() {
  for (const [id, c] of clients) {
    c.ws.send({ type: 'presence', users: presenceFor(id) });
  }
}

function roomCounts() {
  const out = [];
  for (const [, room] of rooms) {
    const d = room.def;
    out.push({ id: d.id, name: d.name, theme: d.theme, accent: d.accent, count: room.members.size, custom: !!room.owner });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Join / leave / move
// ---------------------------------------------------------------------------
function placeInRoom(c, roomId) {
  const room = rooms.get(roomId);
  if (!room) return false;
  // leave old
  if (c.roomId && rooms.has(c.roomId)) {
    const old = rooms.get(c.roomId);
    old.members.delete(c.id);
    broadcastRoom(c.roomId, { type: 'left', id: c.id });
  }
  c.roomId = roomId;
  c.emote = null;               // emotes don't carry across rooms
  const d = room.def;
  c.x = (Math.random() - 0.5) * (d.w - 4);
  c.z = (Math.random() - 0.5) * (d.d - 4);
  c.rot = Math.random() * Math.PI * 2;
  room.members.add(c.id);
  // tell joiner the full room; tell others about the newcomer
  c.ws.send(roomSnapshot(roomId));
  const prof = profiles[c.id] || {};
  broadcastRoom(roomId, {
    type: 'joined',
    user: { id: c.id, name: prof.name, x: c.x, z: c.z, rot: c.rot,
      bodyColor: prof.bodyColor, hairColor: prof.hairColor, hairStyle: prof.hairStyle || 'long', body: prof.body || 'feminine',
      outfit: prof.outfit, outfitColor: prof.outfitColor, avatarUrl: prof.avatarUrl || '' },
  }, c.id);
  return true;
}

function handleMessage(c, msg) {
  let m;
  try { m = JSON.parse(msg); } catch { return; }
  if (!m || typeof m.type !== 'string') return;

  switch (m.type) {
    case 'hello': {
      // m: { userId, name }
      const uid = sanitize(m.userId, 40) || crypto.randomUUID();
      // If this userId is already connected (e.g. reconnect), retire the old socket.
      const prev = clients.get(uid);
      if (prev && prev !== c) {
        if (prev.roomId && rooms.has(prev.roomId)) {
          rooms.get(prev.roomId).members.delete(uid);
          broadcastRoom(prev.roomId, { type: 'left', id: uid });
        }
        prev.id = null;            // neutralize its later close handler
        try { prev.ws.close(); } catch {}
      }
      c.id = uid;
      if (!profiles[uid]) profiles[uid] = defaultProfile(sanitize(m.name, 24));
      if (m.name) profiles[uid].name = sanitize(m.name, 24) || profiles[uid].name;
      // ensure arrays
      if (!Array.isArray(profiles[uid].friends)) profiles[uid].friends = [];
      clients.set(uid, c);
      saveProfiles();
      c.ws.send({
        type: 'welcome',
        userId: uid,
        profile: publicProfile(uid),
        presets: AVATAR_PRESETS,
        rooms: roomCounts(),
      });
      pushPresenceAll();
      break;
    }
    case 'createRoom': {
      if (!c.id) return;
      const name = sanitize(m.name, 28);
      if (!name) { c.ws.send({ type: 'roomCreateResult', ok: false, reason: 'Enter a room name' }); return; }
      const theme = THEME_PRESETS[m.theme] ? m.theme : 'neon';
      // cap how many rooms one user can own
      let owned = 0; for (const [, r] of rooms) if (r.owner === c.id) owned++;
      if (owned >= 10) { c.ws.send({ type: 'roomCreateResult', ok: false, reason: 'Room limit reached' }); return; }
      const id = 'r_' + crypto.randomUUID().slice(0, 8);
      const tp = THEME_PRESETS[theme];
      const def = { id, name, theme, floor: tp.floor, accent: tp.accent, w: 22, d: 22 };
      rooms.set(id, { def, members: new Set(), owner: c.id });
      try { db.createRoom({ ...def, owner: c.id }); } catch (e) { console.error('createRoom', e.message); }
      broadcastRoomCountsAll();
      c.ws.send({ type: 'roomCreateResult', ok: true, roomId: id });
      break;
    }
    case 'joinRoom': {
      if (!c.id) return;
      const roomId = sanitize(m.roomId, 32);
      if (!rooms.has(roomId)) return;
      placeInRoom(c, roomId);
      c.ws.send({ type: 'rooms', rooms: roomCounts() });
      pushPresenceAll();
      broadcastRoomCountsAll();
      break;
    }
    case 'leaveRoom': {
      if (!c.id || !c.roomId) return;
      const old = rooms.get(c.roomId);
      if (old) { old.members.delete(c.id); broadcastRoom(c.roomId, { type: 'left', id: c.id }); }
      c.roomId = null;
      pushPresenceAll();
      broadcastRoomCountsAll();
      break;
    }
    case 'move': {
      if (!c.id || !c.roomId) return;
      const now = Date.now();
      const room = rooms.get(c.roomId); if (!room) return;
      const d = room.def;
      const hx = d.w / 2 - 1, hz = d.d / 2 - 1;
      const nx = clamp(Number(m.x) || 0, -hx, hx);
      const nz = clamp(Number(m.z) || 0, -hz, hz);
      // basic anti-teleport: cap step distance since last move
      c.x = nx; c.z = nz;
      c.rot = Number(m.rot) || 0;
      c.lastMove = now;
      broadcastRoom(c.roomId, { type: 'moved', id: c.id, x: c.x, z: c.z, rot: c.rot }, c.id);
      break;
    }
    case 'emote': {
      if (!c.id || !c.roomId) return;
      const name = (m.name == null || m.name === '') ? '' : sanitize(m.name, 20);
      c.emote = name || null;
      broadcastRoom(c.roomId, { type: 'emote', id: c.id, name: c.emote });
      break;
    }
    case 'chat': {
      if (!c.id || !c.roomId) return;
      const text = sanitize(m.text, 240);
      if (!text) return;
      const prof = profiles[c.id] || {};
      broadcastRoom(c.roomId, { type: 'chat', id: c.id, name: prof.name, text, ts: Date.now() });
      break;
    }
    case 'customize': {
      if (!c.id) return;
      const p = profiles[c.id];
      p.bodyColor = validColor(m.bodyColor, p.bodyColor);
      p.hairColor = validColor(m.hairColor, p.hairColor);
      p.outfitColor = validColor(m.outfitColor, p.outfitColor);
      if (AVATAR_PRESETS.outfits.includes(m.outfit)) p.outfit = m.outfit;
      if (AVATAR_PRESETS.hairStyles.includes(m.hairStyle)) p.hairStyle = m.hairStyle;
      if (AVATAR_PRESETS.bodies.includes(m.body)) p.body = m.body;
      if (typeof m.name === 'string' && sanitize(m.name, 24)) p.name = sanitize(m.name, 24);
      if ('avatarUrl' in m) { const v = validAvatarUrl(m.avatarUrl); if (v !== null) p.avatarUrl = v; }
      saveProfiles();
      c.ws.send({ type: 'profileUpdated', profile: publicProfile(c.id) });
      if (c.roomId) {
        broadcastRoom(c.roomId, {
          type: 'appearance', id: c.id, name: p.name,
          bodyColor: p.bodyColor, hairColor: p.hairColor, hairStyle: p.hairStyle || 'long', body: p.body || 'feminine', outfit: p.outfit,
          outfitColor: p.outfitColor, avatarUrl: p.avatarUrl || '',
        });
      }
      pushPresenceAll();
      break;
    }
    case 'setVisibility': {
      if (!c.id) return;
      const v = m.visibility;
      if (['everyone', 'friends', 'nobody'].includes(v)) {
        profiles[c.id].visibility = v;
        saveProfiles();
        c.ws.send({ type: 'profileUpdated', profile: publicProfile(c.id) });
        // Recompute everyone's view: others may need to gain/lose this location.
        pushPresenceAll();
      }
      break;
    }
    case 'addFriend': {
      // Mutual friendship: both must add each other. m: { name } or { userId }
      if (!c.id) return;
      let targetId = sanitize(m.userId, 40);
      if (!targetId && m.name) targetId = resolveByName(m.name);
      if (!targetId || targetId === c.id || !profiles[targetId]) {
        c.ws.send({ type: 'friendResult', ok: false, reason: 'User not found' });
        return;
      }
      const me = profiles[c.id];
      if (!me.friends.includes(targetId)) me.friends.push(targetId);
      saveProfiles();
      const mutual = (profiles[targetId].friends || []).includes(c.id);
      c.ws.send({ type: 'friendResult', ok: true, targetName: profiles[targetId].name, mutual });
      // location visibility may change for either side
      pushPresenceAll();
      break;
    }
    case 'whereis': {
      // Explicit presence lookup — server decides, hidden => null.
      if (!c.id) return;
      let targetId = sanitize(m.userId, 40);
      if (!targetId && m.name) targetId = resolveByName(m.name);
      const online = clients.has(targetId);
      const room = visibleRoomFor(targetId, c.id); // null if not allowed
      c.ws.send({
        type: 'whereisResult',
        userId: targetId || null,
        name: targetId && profiles[targetId] ? profiles[targetId].name : (m.name || null),
        online,
        roomId: room,
        roomName: room ? rooms.get(room).def.name : null,
        visible: room !== null,
      });
      break;
    }
    default: break;
  }
}

// Resolve a display name to a userId, preferring an ONLINE user so duplicate
// names across stale profiles never shadow the live person.
function resolveByName(name) {
  const want = sanitize(name, 24).toLowerCase();
  if (!want) return '';
  for (const [id] of clients) {
    const p = profiles[id];
    if (p && (p.name || '').toLowerCase() === want) return id;
  }
  for (const [id, p] of Object.entries(profiles)) {
    if ((p.name || '').toLowerCase() === want) return id;
  }
  return '';
}

function publicProfile(id) {
  const p = profiles[id] || {};
  return {
    id, name: p.name, bodyColor: p.bodyColor, hairColor: p.hairColor, hairStyle: p.hairStyle || 'long', body: p.body || 'feminine',
    outfit: p.outfit, outfitColor: p.outfitColor, avatarUrl: p.avatarUrl || '',
    visibility: p.visibility,
    friends: (p.friends || []).map(fid => ({ id: fid, name: profiles[fid] ? profiles[fid].name : fid })),
  };
}

function broadcastRoomCountsAll() {
  const rc = roomCounts();
  for (const [, c] of clients) c.ws.send({ type: 'rooms', rooms: rc });
}

function dropClient(c) {
  if (!c.id) return;
  // If a newer connection has already taken this userId, this stale socket
  // must not remove the live client or its room membership.
  if (clients.get(c.id) !== c) return;
  if (c.roomId && rooms.has(c.roomId)) {
    rooms.get(c.roomId).members.delete(c.id);
    broadcastRoom(c.roomId, { type: 'left', id: c.id });
  }
  clients.delete(c.id);
  pushPresenceAll();
  broadcastRoomCountsAll();
}

// ---------------------------------------------------------------------------
// HTTP (static) + WebSocket upgrade
// ---------------------------------------------------------------------------
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon', '.png': 'image/png',
};

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, rooms: roomCounts(), online: clients.size }));
    return;
  }
  // Upload an avatar file (user's own .glb/.vrm). Stored on this server and
  // served back by a shareable URL so other clients can load it too.
  if (req.method === 'POST' && req.url.startsWith('/api/upload-avatar')) {
    const ext = ((new URL(req.url, 'http://x').searchParams.get('ext')) || 'glb').toLowerCase();
    if (!['glb', 'vrm'].includes(ext)) { res.writeHead(400); res.end('bad ext'); return; }
    const chunks = []; let size = 0, aborted = false;
    req.on('data', (c) => {
      size += c.length;
      if (size > 45 * 1024 * 1024) { aborted = true; res.writeHead(413); res.end('too large'); req.destroy(); }
      else chunks.push(c);
    });
    req.on('end', () => {
      if (aborted) return;
      try {
        fs.mkdirSync(path.join(DATA_DIR, 'avatars'), { recursive: true });
        const name = crypto.randomUUID() + '.' + ext;
        fs.writeFileSync(path.join(DATA_DIR, 'avatars', name), Buffer.concat(chunks));
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ url: '/avatars/' + name }));
      } catch (e) { res.writeHead(500); res.end('err'); }
    });
    return;
  }
  // Serve uploaded avatars
  if (req.url.split('?')[0].startsWith('/avatars/')) {
    const fp = path.join(DATA_DIR, path.normalize(decodeURIComponent(req.url.split('?')[0])));
    if (!fp.startsWith(path.join(DATA_DIR, 'avatars'))) { res.writeHead(403); res.end(); return; }
    fs.readFile(fp, (e, d) => {
      if (e) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'content-type': 'model/gltf-binary', 'access-control-allow-origin': '*' });
      res.end(d);
    });
    return;
  }
  let urlPath = decodeURIComponent(req.url.split('?')[0]);
  if (urlPath === '/') urlPath = '/index.html';
  const filePath = path.join(PUBLIC_DIR, path.normalize(urlPath));
  if (!filePath.startsWith(PUBLIC_DIR)) { res.writeHead(403); res.end('forbidden'); return; }
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'content-type': MIME[path.extname(filePath)] || 'application/octet-stream' });
    res.end(data);
  });
});

server.on('upgrade', (req, socket) => {
  const key = req.headers['sec-websocket-key'];
  if (!key) { socket.destroy(); return; }
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
    'Upgrade: websocket\r\nConnection: Upgrade\r\n' +
    'Sec-WebSocket-Accept: ' + acceptKey(key) + '\r\n\r\n'
  );
  const ws = makeWs(socket);
  const c = { ws, id: null, roomId: null, x: 0, z: 0, rot: 0, lastMove: 0 };
  const parser = makeParser(
    (text) => { try { handleMessage(c, text); } catch (e) { console.error('msg', e.message); } },
    () => { ws.alive = false; dropClient(c); try { socket.destroy(); } catch {} },
    socket
  );
  socket.on('data', (chunk) => { try { parser(chunk); } catch (e) { console.error('parse', e.message); } });
  socket.on('close', () => { ws.alive = false; dropClient(c); });
  socket.on('error', () => { ws.alive = false; dropClient(c); });
});

// keepalive pings
setInterval(() => {
  for (const [, c] of clients) {
    try { c.ws.socket.write(Buffer.from([0x89, 0])); } catch {}
  }
}, 30000);

server.listen(PORT, () => {
  console.log(`Driftspace server on http://localhost:${PORT}`);
  console.log(`Rooms: ${ROOM_DEFS.map(r => r.name).join(', ')}`);
});
