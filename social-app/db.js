'use strict';
// SQLite data layer for Driftspace (Node's built-in node:sqlite, zero deps).
// Durable state only: user profiles/avatars/privacy/friends, sessions, and
// user-created rooms. Live state (sockets, positions, presence) stays in memory.
const { DatabaseSync } = require('node:sqlite');
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, 'data');
fs.mkdirSync(DATA_DIR, { recursive: true });
const db = new DatabaseSync(path.join(DATA_DIR, 'driftspace.db'));
db.exec('PRAGMA journal_mode = WAL;');
db.exec(`
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY,
  name TEXT,
  body_color TEXT, hair_color TEXT, hair_style TEXT,
  outfit TEXT, outfit_color TEXT, avatar_url TEXT,
  visibility TEXT, friends TEXT,
  pass_hash TEXT,
  created_at INTEGER
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id TEXT, created_at INTEGER, expires_at INTEGER
);
CREATE TABLE IF NOT EXISTS rooms(
  id TEXT PRIMARY KEY, name TEXT, theme TEXT, floor TEXT, accent TEXT,
  w INTEGER, d INTEGER, owner TEXT, created_at INTEGER
);
`);

function rowToProfile(r) {
  return {
    name: r.name,
    bodyColor: r.body_color, hairColor: r.hair_color, hairStyle: r.hair_style || 'long',
    outfit: r.outfit, outfitColor: r.outfit_color, avatarUrl: r.avatar_url || '',
    visibility: r.visibility || 'everyone',
    friends: safeArr(r.friends),
    passHash: r.pass_hash || null,
  };
}
function safeArr(s) { try { const a = JSON.parse(s || '[]'); return Array.isArray(a) ? a : []; } catch { return []; } }

// ---- profiles ----
exports.loadProfiles = function () {
  const out = {};
  for (const r of db.prepare('SELECT * FROM users').all()) out[r.id] = rowToProfile(r);
  return out;
};

const upsertUser = db.prepare(`
  INSERT INTO users(id,name,body_color,hair_color,hair_style,outfit,outfit_color,avatar_url,visibility,friends,pass_hash,created_at)
  VALUES(@id,@name,@body,@hair,@hstyle,@outfit,@ocolor,@url,@vis,@friends,@pass,@created)
  ON CONFLICT(id) DO UPDATE SET
    name=@name, body_color=@body, hair_color=@hair, hair_style=@hstyle,
    outfit=@outfit, outfit_color=@ocolor, avatar_url=@url, visibility=@vis,
    friends=@friends, pass_hash=@pass`);

exports.saveProfile = function (id, p) {
  upsertUser.run({
    id, name: p.name || 'Guest',
    body: p.bodyColor || '', hair: p.hairColor || '', hstyle: p.hairStyle || 'long',
    outfit: p.outfit || 'tee', ocolor: p.outfitColor || '', url: p.avatarUrl || '',
    vis: p.visibility || 'everyone', friends: JSON.stringify(p.friends || []),
    pass: p.passHash || null, created: Date.now(),
  });
};

// ---- sessions ----
const insSession = db.prepare('INSERT OR REPLACE INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)');
exports.createSession = function (token, userId, ttlMs) {
  const now = Date.now();
  insSession.run(token, userId, now, now + (ttlMs || 1000 * 60 * 60 * 24 * 30));
};
exports.getSession = function (token) {
  const r = db.prepare('SELECT * FROM sessions WHERE token=?').get(token);
  if (!r) return null;
  if (r.expires_at < Date.now()) { db.prepare('DELETE FROM sessions WHERE token=?').run(token); return null; }
  return { userId: r.user_id };
};

// ---- user-created rooms ----
exports.loadRooms = function () {
  return db.prepare('SELECT * FROM rooms ORDER BY created_at').all().map(r => ({
    id: r.id, name: r.name, theme: r.theme, floor: r.floor, accent: r.accent,
    w: r.w, d: r.d, owner: r.owner,
  }));
};
const insRoom = db.prepare('INSERT INTO rooms(id,name,theme,floor,accent,w,d,owner,created_at) VALUES(?,?,?,?,?,?,?,?,?)');
exports.createRoom = function (r) {
  insRoom.run(r.id, r.name, r.theme, r.floor, r.accent, r.w, r.d, r.owner || '', Date.now());
};
exports.deleteRoom = function (id, owner) {
  const r = db.prepare('SELECT owner FROM rooms WHERE id=?').get(id);
  if (!r || r.owner !== owner) return false;
  db.prepare('DELETE FROM rooms WHERE id=?').run(id);
  return true;
};

exports.db = db;
