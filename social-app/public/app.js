// app.js — Driftspace client: scene, networking, input, UI.
import * as THREE from 'three';
import { createAvatarController } from './avatarController.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';
const gltfLoader = new GLTFLoader();

// ---------- identity ----------
const uid = localStorage.getItem('ds_uid') || crypto.randomUUID();
localStorage.setItem('ds_uid', uid);
let myName = localStorage.getItem('ds_name') || '';

// ---------- DOM ----------
const $ = (id) => document.getElementById(id);
const lobby = $('lobby'), world = $('world');
const nameInput = $('nameInput'), enterBtn = $('enterBtn');
const loginStep = $('loginStep'), roomStep = $('roomStep'), roomList = $('roomList');
const chatLog = $('chatLog'), chatForm = $('chatForm'), chatInput = $('chatInput');
const roomTitle = $('roomTitle');

if (myName) nameInput.value = myName;

// ---------- networking ----------
let ws, myProfile = null, presets = null, roomsCache = [];
let currentRoom = null;
let joinedRoomId = null;   // for auto-rejoin after reconnect
let connected = false;
const pending = [];
function send(obj) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
  else pending.push(obj);
}
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}`);
  ws.onopen = () => {
    connected = true;
    send({ type: 'hello', userId: uid, name: myName });
    while (pending.length) ws.send(JSON.stringify(pending.shift()));
  };
  ws.onclose = () => { connected = false; toast('Disconnected — reconnecting…'); setTimeout(connect, 1500); };
  ws.onmessage = (ev) => { try { handle(JSON.parse(ev.data)); } catch {} };
}

function handle(m) {
  switch (m.type) {
    case 'welcome':
      myProfile = m.profile; presets = m.presets; roomsCache = m.rooms;
      pairedPosesList = m.pairedPoses || [];
      buildRoomList(); buildCustomizeUI(); syncVisibilityUI();
      if (joinedRoomId) send({ type: 'joinRoom', roomId: joinedRoomId }); // rejoin after reconnect
      break;
    case 'rooms': roomsCache = m.rooms; buildRoomList(); break;
    case 'roomCreateResult':
      if (m.ok) { if ($('roomCreateMsg')) $('roomCreateMsg').textContent = ''; enterRoom(m.roomId); }
      else if ($('roomCreateMsg')) $('roomCreateMsg').textContent = m.reason || 'Could not create room';
      break;
    case 'roomState': onRoomState(m); break;
    case 'joined': addRemote(m.user); break;
    case 'left': removeRemote(m.id); break;
    case 'moved': onMoved(m); break;
    case 'chat': onChat(m); break;
    case 'appearance': onAppearance(m); break;
    case 'emote': { const r = remotes.get(m.id); if (r) r.avatar.setEmote(m.name || null); if (m.id === uid && m.name === null) clearPairLocal(); break; }
    case 'pairInvite': onPairInvite(m); break;
    case 'pairedPose': onPairedPose(m); break;
    case 'pairResult': if (!m.ok) toast(m.reason || 'Pairing failed'); break;
    case 'profileUpdated': myProfile = m.profile; syncVisibilityUI(); buildFriendList(); syncRpmUI(); break;
    case 'presence': onPresence(m.users); break;
    case 'whereisResult': onWhereis(m); break;
    case 'friendResult': onFriendResult(m); break;
  }
}

// ---------- lobby ----------
enterBtn.onclick = () => {
  const n = nameInput.value.trim();
  if (!n) { nameInput.focus(); return; }
  myName = n; localStorage.setItem('ds_name', n);
  if (!ws) connect(); else send({ type: 'hello', userId: uid, name: myName });
  loginStep.hidden = true; roomStep.hidden = false;
};
$('backToName').onclick = () => { roomStep.hidden = true; loginStep.hidden = false; };
if ($('createRoomBtn')) $('createRoomBtn').onclick = () => {
  const name = $('newRoomName').value.trim();
  if (!name) { $('roomCreateMsg').textContent = 'Enter a room name'; return; }
  $('roomCreateMsg').textContent = 'Creating…';
  send({ type: 'createRoom', name, theme: $('newRoomTheme').value });
};
nameInput.onkeydown = (e) => { if (e.key === 'Enter') enterBtn.click(); };

function buildRoomList() {
  if (!roomList) return;
  roomList.innerHTML = '';
  for (const r of roomsCache) {
    const el = document.createElement('button');
    el.className = 'room-card';
    el.innerHTML = `<span class="room-dot" style="background:${r.accent}"></span>
      <span><div class="rn">${esc(r.name)}</div><div class="rc">${r.count} here · ${r.theme}</div></span>`;
    el.onclick = () => enterRoom(r.id);
    roomList.appendChild(el);
  }
}

function enterRoom(roomId) {
  joinedRoomId = roomId;
  send({ type: 'joinRoom', roomId });
  lobby.hidden = true; world.hidden = false;
  if (!renderer) initScene();
  running = true;
}

$('leaveBtn').onclick = () => {
  joinedRoomId = null;
  send({ type: 'leaveRoom' });
  clearRoom();
  world.hidden = true; lobby.hidden = false;
  roomStep.hidden = false; loginStep.hidden = true;
  running = false;
};

// ================= THREE scene =================
let renderer, scene, camera, pmrem;
let localAvatar = null;
const remotes = new Map();         // id -> { avatar, group, target, label, lastPos, speed, bubble, bubbleTimer }
let roomMeshGroup = null;
let roomUpdate = null;          // per-frame hook for animated rooms (penthouse water/skyline/candles)
let penthouseSeats = [];        // sit spots: {x,z,rot,label}
let penthouseColliders = [];    // furniture colliders: {x,z,r}
let setAtmosphere = null;       // penthouse atmosphere preset setter
let running = false;
const clock = new THREE.Clock();

// camera orbit
let camYaw = 0, camPitch = 0.5, camDist = 5.2;
let dragging = false, lastX = 0, lastY = 0;

// local movement
const myPos = new THREE.Vector3(0, 0, 0);
let myRot = 0;
let moveTarget = null;             // click-to-move target (Vector3) or null
let pendingSit = null;             // seat to sit on when the avatar arrives
const keys = {};
let lastSent = 0, lastSentPos = new THREE.Vector3();
let roomBounds = { w: 24, d: 24 };

function initScene() {
  const canvas = $('scene');
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 200);

  pmrem = new THREE.PMREMGenerator(renderer);
  pmrem.compileEquirectangularShader();

  addEventListener('resize', onResize);
  // pointer controls
  canvas.addEventListener('pointerdown', onPointerDown);
  addEventListener('pointermove', onPointerMove);
  addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('wheel', (e) => { camDist = clamp(camDist + e.deltaY * 0.003, 2.5, 10); e.preventDefault(); }, { passive: false });
  addEventListener('keydown', (e) => { if (document.activeElement.tagName === 'INPUT') return; keys[e.key.toLowerCase()] = true; });
  addEventListener('keyup', (e) => { keys[e.key.toLowerCase()] = false; });

  animate();
  // lightweight debug hook (handy for diagnostics; harmless in production)
  window.__ds = {
    get remotes() { return [...remotes.entries()].map(([id, r]) => ({ id, name: r.name, x: +r.group.position.x.toFixed(2), z: +r.group.position.z.toFixed(2), mode: r.avatar.mode })); },
    get me() { return { x: +myPos.x.toFixed(2), z: +myPos.z.toFixed(2), rot: +myRot.toFixed(2), mode: localAvatar && localAvatar.mode }; },
    get room() { return currentRoom && currentRoom.name; },
    setAvatar(u) { setAvatarUrl(u); },
    get info() { return renderer && renderer.info.render; },
    stats() {
      let point = 0, dir = 0, hemi = 0, mesh = 0, vis = 0;
      scene && scene.traverse(o => { if (o.isPointLight) point++; else if (o.isDirectionalLight) dir++; else if (o.isHemisphereLight) hemi++; else if (o.isMesh) { mesh++; if (o.visible) vis++; } });
      return { point, dir, hemi, mesh, visMesh: vis, draws: renderer && renderer.info.render.calls, tris: renderer && renderer.info.render.triangles };
    },
  };
}

function envFromGradient(top, mid, bottom) {
  const c = document.createElement('canvas'); c.width = 16; c.height = 256;
  const g = c.getContext('2d').createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0, top); g.addColorStop(0.5, mid); g.addColorStop(1, bottom);
  const ctx = c.getContext('2d'); ctx.fillStyle = g; ctx.fillRect(0, 0, 16, 256);
  const tex = new THREE.CanvasTexture(c);
  tex.mapping = THREE.EquirectangularReflectionMapping;
  const env = pmrem.fromEquirectangular(tex).texture;
  tex.dispose();
  return env;
}

const THEME_ENV = {
  neon:   ['#3a1d5e', '#1b1033', '#06040c'],
  warm:   ['#4a3417', '#241a10', '#0b0804'],
  nature: ['#213d2a', '#122018', '#060a07'],
  mono:   ['#3a3a44', '#202024', '#0a0a0c'],
};

// ---------- build a room (original geometry) ----------
function buildRoom(def) {
  if (roomMeshGroup) { scene.remove(roomMeshGroup); disposeGroup(roomMeshGroup); }
  roomMeshGroup = new THREE.Group();
  scene.add(roomMeshGroup);
  roomBounds = { w: def.w, d: def.d };
  roomUpdate = null; penthouseSeats = []; penthouseColliders = [];

  if (def.theme === 'penthouse') { buildPenthouse(def); return; }

  const env = THEME_ENV[def.theme] || THEME_ENV.mono;
  scene.environment = envFromGradient(env[0], env[1], env[2]);
  scene.background = new THREE.Color(env[2]);
  scene.fog = new THREE.Fog(new THREE.Color(env[2]), def.w * 0.9, def.w * 2.2);

  const accent = new THREE.Color(def.accent);

  // lights
  const hemi = new THREE.HemisphereLight(0xffffff, 0x222233, 0.55);
  roomMeshGroup.add(hemi);
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(def.w * 0.4, def.w * 0.9, def.d * 0.3);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  const s = Math.max(def.w, def.d) * 0.75;
  Object.assign(key.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 1, far: def.w * 3 });
  key.shadow.bias = -0.0004; key.shadow.normalBias = 0.02;
  roomMeshGroup.add(key);
  const fill = new THREE.PointLight(accent, 12, def.w * 1.5, 2);
  fill.position.set(-def.w * 0.25, 2.4, -def.d * 0.2);
  roomMeshGroup.add(fill);

  // floor
  const floorMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(def.floor), roughness: 0.85, metalness: 0.08 });
  const floor = new THREE.Mesh(new THREE.BoxGeometry(def.w, 0.4, def.d), floorMat);
  floor.position.y = -0.2; floor.receiveShadow = true;
  roomMeshGroup.add(floor);

  // subtle grid inlay
  const grid = new THREE.GridHelper(Math.min(def.w, def.d), Math.min(def.w, def.d), accent, 0x333344);
  grid.material.opacity = 0.18; grid.material.transparent = true; grid.position.y = 0.012;
  roomMeshGroup.add(grid);

  // walls
  const wallMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(def.floor).lerp(new THREE.Color('#ffffff'), 0.08), roughness: 0.9, metalness: 0.02 });
  const h = 3.4;
  const walls = [
    [def.w, h, 0.2, 0, h / 2, -def.d / 2],
    [def.w, h, 0.2, 0, h / 2, def.d / 2],
    [0.2, h, def.d, -def.w / 2, h / 2, 0],
    [0.2, h, def.d, def.w / 2, h / 2, 0],
  ];
  for (const [ww, wh, wd, x, y, z] of walls) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(ww, wh, wd), wallMat);
    m.position.set(x, y, z); m.receiveShadow = true; m.castShadow = false;
    roomMeshGroup.add(m);
  }
  // accent trim strip along walls
  const trimMat = new THREE.MeshStandardMaterial({ color: accent, emissive: accent, emissiveIntensity: 0.6, roughness: 0.4 });
  for (const [ww, , wd, x, , z] of walls) {
    const strip = new THREE.Mesh(new THREE.BoxGeometry(ww || 0.22, 0.08, wd || 0.22), trimMat);
    strip.position.set(x, 2.2, z);
    roomMeshGroup.add(strip);
  }

  // props: seats around a central low table (original simple geometry)
  const seatMat = new THREE.MeshStandardMaterial({ color: accent.clone().lerp(new THREE.Color('#ffffff'), 0.2), roughness: 0.6 });
  const tableMat = new THREE.MeshStandardMaterial({ color: new THREE.Color('#2a2a33'), roughness: 0.5, metalness: 0.2 });
  const table = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.2, 0.5, 24), tableMat);
  table.position.y = 0.25; table.castShadow = true; table.receiveShadow = true;
  roomMeshGroup.add(table);
  const seatN = 6;
  for (let i = 0; i < seatN; i++) {
    const a = (i / seatN) * Math.PI * 2;
    const seat = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.45, 18), seatMat);
    seat.position.set(Math.cos(a) * 2.6, 0.22, Math.sin(a) * 2.6);
    seat.castShadow = true; seat.receiveShadow = true;
    roomMeshGroup.add(seat);
  }
  // a couple of tall accent pillars in corners
  const pillarMat = new THREE.MeshStandardMaterial({ color: accent, emissive: accent, emissiveIntensity: 0.25, roughness: 0.3, metalness: 0.4 });
  for (const sgn of [[-1, -1], [1, 1]]) {
    const p = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, h, 16), pillarMat);
    p.position.set(sgn[0] * (def.w / 2 - 1.2), h / 2, sgn[1] * (def.d / 2 - 1.2));
    p.castShadow = true;
    roomMeshGroup.add(p);
  }
}

// ---------- room state ----------
function onRoomState(m) {
  clearRoom();
  currentRoom = m.room;
  roomTitle.textContent = m.room.name;
  buildRoom(m.room);
  buildEmoteBar();
  buildPairBar();
  // local avatar
  localAvatar = createAvatarController({
    bodyColor: myProfile.bodyColor, hairColor: myProfile.hairColor, hairStyle: myProfile.hairStyle || 'long', body: myProfile.body || 'feminine',
    outfit: myProfile.outfit, outfitColor: myProfile.outfitColor, avatarUrl: myProfile.avatarUrl || '',
  });
  scene.add(localAvatar.root);
  const me = m.occupants.find(o => o.id === uid);
  if (me) { myPos.set(me.x, 0, me.z); myRot = me.rot; }
  localAvatar.root.position.copy(myPos);
  localAvatar.root.rotation.y = myRot;
  camYaw = myRot;
  // others
  for (const o of m.occupants) if (o.id !== uid) addRemote(o);
  sysMsg(`Welcome to ${m.room.name}`);
}

function clearRoom() {
  for (const [, r] of remotes) { if (r.avatar.dispose) r.avatar.dispose(); scene && scene.remove(r.group); disposeGroup(r.group); }
  remotes.clear();
  if (localAvatar && scene) { if (localAvatar.dispose) localAvatar.dispose(); scene.remove(localAvatar.root); disposeGroup(localAvatar.root); localAvatar = null; }
  moveTarget = null; roomUpdate = null; penthouseSeats = []; penthouseColliders = []; setAtmosphere = null;
  const ab = document.getElementById('atmoBar'); if (ab) ab.hidden = true;
  localEmote = null; pairLock = false;
  const pin = $('pairInvite'); if (pin) pin.hidden = true;
  document.querySelectorAll('#emoteBar .emote-btn').forEach(b => b.classList.remove('on'));
  chatLog.innerHTML = '';
}

function addRemote(o) {
  if (o.id === uid || remotes.has(o.id)) return;
  const avatar = createAvatarController({ bodyColor: o.bodyColor, hairColor: o.hairColor, hairStyle: o.hairStyle || 'long', body: o.body || 'feminine', outfit: o.outfit, outfitColor: o.outfitColor, avatarUrl: o.avatarUrl || '' });
  const group = new THREE.Group();
  group.add(avatar.root);
  group.position.set(o.x, 0, o.z);
  avatar.root.rotation.y = o.rot;
  const label = makeLabel(o.name);
  label.position.set(0, 2.05, 0);
  group.add(label);
  scene.add(group);
  remotes.set(o.id, {
    avatar, group, name: o.name, label,
    target: new THREE.Vector3(o.x, 0, o.z), targetRot: o.rot,
    lastPos: new THREE.Vector3(o.x, 0, o.z), speed: 0, bubble: null, bubbleTimer: 0,
  });
  if (o.emote) avatar.setEmote(o.emote);
  sysMsg(`${o.name} joined`);
}

function removeRemote(id) {
  const r = remotes.get(id);
  if (!r) return;
  if (r.name) sysMsg(`${r.name} left`);
  if (r.avatar.dispose) r.avatar.dispose();
  scene.remove(r.group); disposeGroup(r.group);
  remotes.delete(id);
}

function onMoved(m) {
  const r = remotes.get(m.id);
  if (!r) return;
  r.target.set(m.x, 0, m.z);
  r.targetRot = m.rot;
}

function onAppearance(m) {
  const r = remotes.get(m.id);
  if (r) {
    r.avatar.setAppearance({ bodyColor: m.bodyColor, hairColor: m.hairColor, hairStyle: m.hairStyle || 'long', body: m.body || 'feminine', outfit: m.outfit, outfitColor: m.outfitColor, avatarUrl: m.avatarUrl || '' });
    if (m.name && r.name !== m.name) { r.name = m.name; r.group.remove(r.label); r.label = makeLabel(m.name); r.label.position.set(0, 2.05, 0); r.group.add(r.label); }
  }
}

// ---------- labels & bubbles (canvas sprites) ----------
function makeTextTexture(text, bg, pad = 16) {
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d');
  const font = 42;
  ctx.font = `600 ${font}px Inter, system-ui, sans-serif`;
  const w = Math.min(640, ctx.measureText(text).width + pad * 2);
  c.width = w; c.height = font + pad * 2;
  const x2 = c.getContext('2d');
  x2.font = `600 ${font}px Inter, system-ui, sans-serif`;
  x2.fillStyle = bg; roundRect(x2, 0, 0, c.width, c.height, 18); x2.fill();
  x2.fillStyle = '#fff'; x2.textBaseline = 'middle'; x2.textAlign = 'center';
  x2.fillText(text, c.width / 2, c.height / 2 + 2);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return { tex: t, w: c.width, h: c.height };
}
function makeLabel(name) {
  const { tex, w, h } = makeTextTexture(name, 'rgba(20,18,36,0.82)');
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  const sc = 0.0022; spr.scale.set(w * sc, h * sc, 1);
  spr.renderOrder = 10;
  return spr;
}
function showBubble(group, holder, text) {
  if (holder.bubble) { group.remove(holder.bubble); holder.bubble.material.map.dispose(); }
  const { tex, w, h } = makeTextTexture(text.length > 60 ? text.slice(0, 60) + '…' : text, 'rgba(255,79,216,0.92)');
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  const sc = 0.0024; spr.scale.set(w * sc, h * sc, 1);
  spr.position.set(0, 2.45, 0); spr.renderOrder = 11;
  group.add(spr);
  holder.bubble = spr; holder.bubbleTimer = 5;
}

// ---------- chat ----------
chatForm.onsubmit = (e) => {
  e.preventDefault();
  const t = chatInput.value.trim();
  if (!t) return;
  send({ type: 'chat', text: t });
  chatInput.value = '';
};
function onChat(m) {
  addChatLine(m.name, m.text, m.id === uid);
  if (m.id === uid) { if (localAvatar) showBubbleLocal(m.text); }
  else { const r = remotes.get(m.id); if (r) showBubble(r.group, r, m.text); }
}
let localBubble = null, localBubbleTimer = 0;
function showBubbleLocal(text) {
  if (localBubble) { localAvatar.root.remove(localBubble); localBubble.material.map.dispose(); }
  const { tex, w, h } = makeTextTexture(text.length > 60 ? text.slice(0, 60) + '…' : text, 'rgba(143,155,255,0.92)');
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  const sc = 0.0024; spr.scale.set(w * sc, h * sc, 1); spr.position.set(0, 2.45, 0); spr.renderOrder = 11;
  localAvatar.root.add(spr); localBubble = spr; localBubbleTimer = 5;
}
function addChatLine(name, text, mine) {
  const el = document.createElement('div');
  el.className = 'chat-msg' + (mine ? ' me' : '');
  el.innerHTML = `<span class="who" style="color:${mine ? 'var(--accent2)' : 'var(--accent)'}">${esc(name)}</span>${esc(text)}`;
  chatLog.appendChild(el); chatLog.scrollTop = chatLog.scrollHeight;
  while (chatLog.children.length > 60) chatLog.removeChild(chatLog.firstChild);
}
function sysMsg(text) {
  const el = document.createElement('div');
  el.className = 'chat-msg sys'; el.textContent = text;
  chatLog.appendChild(el); chatLog.scrollTop = chatLog.scrollHeight;
}

// ================= emotes =================
let localEmote = null;
function doEmote(name) {
  localEmote = (name === localEmote || !name) ? null : name;
  if (localAvatar) localAvatar.setEmote(localEmote);
  send({ type: 'emote', name: localEmote || '' });
  document.querySelectorAll('#emoteBar .emote-btn').forEach(b => b.classList.toggle('on', b.dataset.emote === localEmote));
}
function cancelEmote() {
  if (!localEmote) return;
  localEmote = null;
  if (localAvatar) localAvatar.setEmote(null);
  send({ type: 'emote', name: '' });
  document.querySelectorAll('#emoteBar .emote-btn').forEach(b => b.classList.remove('on'));
}
const EMOTE_BTNS = [['wave', '👋'], ['clap', '👏'], ['dance', '🕺'], ['sit', '🪑'], ['hug', '🤗'], ['cheer', '🙌'], ['cool', '😎'], ['think', '🤔']];
function buildEmoteBar() {
  const bar = $('emoteBar'); if (!bar || bar.childElementCount) return;
  for (const [name, icon] of EMOTE_BTNS) {
    const b = document.createElement('button');
    b.className = 'emote-btn'; b.dataset.emote = name; b.title = name;
    b.innerHTML = `<span>${icon}</span><small>${name}</small>`;
    b.onclick = () => doEmote(name);
    bar.appendChild(b);
  }
}

// ================= paired (two-character) poses =================
let pairedPosesList = [];
let pairLock = false;              // true while my avatar is in a paired pose

function nearestRemoteId() {
  let best = null, bestD = Infinity;
  for (const [id, r] of remotes) {
    const d = Math.hypot(r.group.position.x - myPos.x, r.group.position.z - myPos.z);
    if (d < bestD) { bestD = d; best = id; }
  }
  return bestD < 6 ? best : null;   // must be reasonably close
}
function startPair(poseKey) {
  const targetId = nearestRemoteId();
  if (!targetId) { toast('Stand near someone to pair up'); return; }
  const r = remotes.get(targetId);
  send({ type: 'pairInvite', targetId, pose: poseKey });
  toast('Invited ' + (r ? r.name : 'them') + '…');
}
function onPairInvite(m) {
  // show an accept/decline banner
  const el = $('pairInvite');
  $('pairInviteText').textContent = `${m.fromName} wants to ${m.label.toLowerCase()} 💞`;
  el.hidden = false;
  el.dataset.from = m.fromId; el.dataset.pose = m.pose;
}
$('pairAcceptBtn') && ($('pairAcceptBtn').onclick = () => {
  const el = $('pairInvite');
  send({ type: 'pairAccept', fromId: el.dataset.from, pose: el.dataset.pose });
  el.hidden = true;
});
$('pairDeclineBtn') && ($('pairDeclineBtn').onclick = () => {
  const el = $('pairInvite');
  send({ type: 'pairDecline', fromId: el.dataset.from });
  el.hidden = true;
});
function onPairedPose(m) {
  for (const side of [m.a, m.b]) {
    if (side.id === uid) {
      // snap my avatar to the server-set paired position + lock movement
      myPos.set(side.x, 0, side.z); myRot = side.rot;
      if (localAvatar) { localAvatar.root.position.copy(myPos); localAvatar.root.rotation.y = myRot; localAvatar.setEmote(side.pose); }
      moveTarget = null; pairLock = true; localEmote = side.pose;
    } else {
      const r = remotes.get(side.id);
      if (r) { r.target.set(side.x, 0, side.z); r.targetRot = side.rot; r.avatar.setEmote(side.pose); }
    }
  }
}
function clearPairLocal() {
  if (!pairLock) return;
  pairLock = false; localEmote = null;
  if (localAvatar) localAvatar.setEmote(null);
  document.querySelectorAll('#emoteBar .emote-btn').forEach(b => b.classList.remove('on'));
}
function buildPairBar() {
  const bar = $('pairBar'); if (!bar || bar.childElementCount) return;
  const icons = { hug: '🤗', dance: '💃', hold: '🤝', five: '🙌' };
  for (const p of pairedPosesList) {
    const b = document.createElement('button');
    b.className = 'emote-btn'; b.title = p.label;
    b.innerHTML = `<span>${icons[p.key] || '💞'}</span><small>${p.label}</small>`;
    b.onclick = () => startPair(p.key);
    bar.appendChild(b);
  }
}

// ================= input / movement =================
function onPointerDown(e) {
  // click-to-move if clicking floor (not UI)
  if (e.button === 0) {
    const hit = raycastFloor(e.clientX, e.clientY);
    if (hit) {
      // click near a penthouse seat -> walk there and sit
      let seat = null, best = 1.4;
      for (const s of penthouseSeats) { const d = Math.hypot(s.x - hit.x, s.z - hit.z); if (d < best) { best = d; seat = s; } }
      if (seat) { moveTarget = new THREE.Vector3(seat.x, 0, seat.z); pendingSit = seat; }
      else { moveTarget = hit; pendingSit = null; }
    }
  }
  dragging = true; lastX = e.clientX; lastY = e.clientY;
  draggedDist = 0;
}
let draggedDist = 0;
function onPointerMove(e) {
  if (!dragging) return;
  const dx = e.clientX - lastX, dy = e.clientY - lastY;
  lastX = e.clientX; lastY = e.clientY;
  draggedDist += Math.abs(dx) + Math.abs(dy);
  if (draggedDist > 6) moveTarget = moveTarget; // keep; orbit still rotates camera
  camYaw -= dx * 0.005;
  camPitch = clamp(camPitch + dy * 0.004, 0.08, 1.3);
}
function onPointerUp() { dragging = false; }

const _ray = new THREE.Raycaster(), _ndc = new THREE.Vector2();
const _floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
function raycastFloor(cx, cy) {
  _ndc.set((cx / innerWidth) * 2 - 1, -(cy / innerHeight) * 2 + 1);
  _ray.setFromCamera(_ndc, camera);
  const pt = new THREE.Vector3();
  if (_ray.ray.intersectPlane(_floorPlane, pt)) {
    const hw = roomBounds.w / 2 - 1, hd = roomBounds.d / 2 - 1;
    pt.x = clamp(pt.x, -hw, hw); pt.z = clamp(pt.z, -hd, hd);
    return pt;
  }
  return null;
}

const SPEED = 2.6; // m/s
function updateLocal(dt) {
  if (!localAvatar) return;
  let moveX = 0, moveZ = 0;
  const f = (keys['w'] || keys['arrowup']) ? 1 : (keys['s'] || keys['arrowdown']) ? -1 : 0;
  const s = (keys['d'] || keys['arrowright']) ? 1 : (keys['a'] || keys['arrowleft']) ? -1 : 0;
  let moving = false;
  if (f || s) {
    moveTarget = null;
    // camera-relative
    const sinY = Math.sin(camYaw), cosY = Math.cos(camYaw);
    const fx = -sinY, fz = -cosY;       // forward (into screen)
    const rx = cosY, rz = -sinY;        // right
    moveX = fx * f + rx * s; moveZ = fz * f + rz * s;
    const len = Math.hypot(moveX, moveZ) || 1;
    moveX /= len; moveZ /= len; moving = true;
  } else if (moveTarget) {
    const dx = moveTarget.x - myPos.x, dz = moveTarget.z - myPos.z;
    const d = Math.hypot(dx, dz);
    if (d > 0.08) { moveX = dx / d; moveZ = dz / d; moving = true; }
    else {
      moveTarget = null;
      if (pendingSit) { myRot = pendingSit.rot; localEmote = 'sit'; localAvatar.setEmote('sit'); send({ type: 'emote', name: 'sit' }); pendingSit = null; }
    }
  }
  if (moving && pairLock) { pairLock = false; send({ type: 'pairCancel' }); clearPairLocal(); }
  if (moving && localEmote) cancelEmote();   // moving cancels an emote/pose
  const sprint = moving && (keys['shift'] || keys['shiftleft'] || keys['shiftright']);
  if (moving) {
    const spd = SPEED * (sprint ? 1.9 : 1);
    myPos.x = clamp(myPos.x + moveX * spd * dt, -roomBounds.w / 2 + 1, roomBounds.w / 2 - 1);
    myPos.z = clamp(myPos.z + moveZ * spd * dt, -roomBounds.d / 2 + 1, roomBounds.d / 2 - 1);
    myRot = Math.atan2(moveX, moveZ);
  }
  // furniture collision (penthouse): push the avatar out of furniture footprints
  // (skipped while walking to a seat / seated / paired, so sitting still works)
  if (!pendingSit && !pairLock && localEmote !== 'sit') {
    for (const c of penthouseColliders) {
      const dx = myPos.x - c.x, dz = myPos.z - c.z, d = Math.hypot(dx, dz), minD = c.r + 0.35;
      if (d < minD && d > 1e-4) { myPos.x = c.x + dx / d * minD; myPos.z = c.z + dz / d * minD; moveTarget = null; }
    }
  }
  localAvatar.root.position.copy(myPos);
  localAvatar.root.rotation.y = dampAngle(localAvatar.root.rotation.y, myRot, 12, dt);
  localAvatar.setAnim(moving ? (sprint ? 'run' : 'walk') : 'idle');
  localAvatar.update(dt);

  // send throttled
  const now = performance.now();
  if (now - lastSent > 70 && (moving || lastSentPos.distanceTo(myPos) > 0.01)) {
    send({ type: 'move', x: +myPos.x.toFixed(3), z: +myPos.z.toFixed(3), rot: +myRot.toFixed(3) });
    lastSent = now; lastSentPos.copy(myPos);
  }
  // local bubble timer
  if (localBubble) { localBubbleTimer -= dt; if (localBubbleTimer <= 0) { localAvatar.root.remove(localBubble); localBubble.material.map.dispose(); localBubble = null; } }
}

function updateRemotes(dt) {
  for (const [, r] of remotes) {
    const prev = r.group.position.clone();
    r.group.position.x = damp(r.group.position.x, r.target.x, 10, dt);
    r.group.position.z = damp(r.group.position.z, r.target.z, 10, dt);
    const moved = prev.distanceTo(r.group.position);
    r.speed = moved / Math.max(dt, 0.001);
    const movingR = r.speed > 0.25;
    r.avatar.root.rotation.y = dampAngle(r.avatar.root.rotation.y, r.targetRot, 10, dt);
    r.avatar.setAnim(movingR ? (r.speed > SPEED * 1.35 ? 'run' : 'walk') : 'idle');
    r.avatar.update(dt);
    if (r.bubble) { r.bubbleTimer -= dt; if (r.bubbleTimer <= 0) { r.group.remove(r.bubble); r.bubble.material.map.dispose(); r.bubble = null; } }
  }
}

// ---------- camera ----------
function updateCamera(dt) {
  if (!localAvatar) return;
  const tgt = myPos;
  const cx = tgt.x + Math.sin(camYaw) * Math.cos(camPitch) * camDist;
  const cz = tgt.z + Math.cos(camYaw) * Math.cos(camPitch) * camDist;
  const cy = 1.0 + Math.sin(camPitch) * camDist;
  camera.position.set(cx, cy, cz);
  camera.lookAt(tgt.x, 1.1, tgt.z);
}

// ---------- loop ----------
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  if (running && scene) {
    updateLocal(dt);
    updateRemotes(dt);
    updateCamera(dt);
    if (roomUpdate) roomUpdate(dt);
    renderer.render(scene, camera);
  }
}

function onResize() {
  if (!renderer) return;
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}

// ================= panels / UI =================
document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => { $(b.dataset.close).hidden = true; });
function togglePanel(id) { const p = $(id); const willShow = p.hidden; document.querySelectorAll('.panel').forEach(x => x.hidden = true); p.hidden = !willShow; }
$('toggleCustomize').onclick = () => togglePanel('customizePanel');
$('togglePrivacy').onclick = () => togglePanel('privacyPanel');
$('toggleFriends').onclick = () => { togglePanel('friendsPanel'); buildFriendList(); };

// appearance
let sel = { bodyColor: null, hairColor: null, hairStyle: null, outfit: null, outfitColor: null };
function buildCustomizeUI() {
  if (!presets) return;
  sel = {
    bodyColor: myProfile.bodyColor, hairColor: myProfile.hairColor, hairStyle: myProfile.hairStyle || 'long',
    body: myProfile.body || 'feminine', outfit: myProfile.outfit, outfitColor: myProfile.outfitColor,
  };
  $('czName').value = myProfile.name || myName;
  pills('bodyTypes', presets.bodies || ['feminine', 'neutral', 'athletic', 'male'], 'body');
  swatches('bodyColors', presets.bodyColors, 'bodyColor');
  swatches('hairColors', presets.hairColors, 'hairColor');
  swatches('outfitColors', presets.outfitColors, 'outfitColor');
  pills('hairStyles', presets.hairStyles || ['long', 'wavy', 'ponytail', 'bun', 'short'], 'hairStyle');
  pills('outfitStyles', presets.outfits, 'outfit');
  buildReadyAvatars();
  syncRpmUI();
}
function buildReadyAvatars() {
  const c = $('readyAvatars'); if (!c || !presets) return;
  c.innerHTML = '';
  for (const a of (presets.readyAvatars || [])) {
    const b = document.createElement('button');
    b.textContent = '✨ ' + a.name;
    b.onclick = () => { setAvatarUrl(a.url); toast('Loading ' + a.name + '…'); };
    c.appendChild(b);
  }
}
function pills(containerId, items, key) {
  const c = $(containerId); if (!c) return; c.innerHTML = '';
  for (const it of items) {
    const el = document.createElement('button');
    el.className = 'pill' + (it === sel[key] ? ' sel' : '');
    el.textContent = it;
    el.onclick = () => { sel[key] = it; [...c.children].forEach(x => x.classList.toggle('sel', x.textContent === it)); previewLook(); };
    c.appendChild(el);
  }
}
function swatches(containerId, colors, key) {
  const c = $(containerId); c.innerHTML = '';
  for (const col of colors) {
    const el = document.createElement('button');
    el.className = 'swatch' + (col === sel[key] ? ' sel' : '');
    el.style.background = col;
    el.onclick = () => { sel[key] = col; [...c.children].forEach(x => x.classList.remove('sel')); el.classList.add('sel'); previewLook(); };
    c.appendChild(el);
  }
}
function previewLook() {
  if (localAvatar) localAvatar.setAppearance({ ...sel });
}
$('saveAppearance').onclick = () => {
  const name = $('czName').value.trim();
  send({ type: 'customize', name, bodyColor: sel.bodyColor, hairColor: sel.hairColor, hairStyle: sel.hairStyle, body: sel.body, outfit: sel.outfit, outfitColor: sel.outfitColor });
  if (name) { myName = name; localStorage.setItem('ds_name', name); }
  toast('Look saved');
};

// ---------- Ready Player Me ----------
const RPM_SUBDOMAIN = localStorage.getItem('ds_rpm_subdomain') || 'demo';
function rpmCreatorUrl() {
  return `https://${RPM_SUBDOMAIN}.readyplayer.me/avatar?frameApi&clearCache&bodyType=fullbody`;
}
function syncRpmUI() {
  if (!myProfile) return;
  const on = !!myProfile.avatarUrl;
  const isVrm = on && /\.vrm(\?|$)/i.test(myProfile.avatarUrl);
  const st = $('rpmStatus'); st.textContent = on ? (isVrm ? 'Anime avatar ✓' : 'Custom avatar ✓') : 'Original avatar';
  st.classList.toggle('on', on);
  $('clearRpm').hidden = !on;
  const pc = $('procControls'); // keep color controls usable even with RPM (for fallback)
}
function setAvatarUrl(url) {
  send({ type: 'customize', avatarUrl: url });            // server persists + broadcasts
  if (localAvatar) localAvatar.setAppearance({ avatarUrl: url });
  myProfile.avatarUrl = url;
  syncRpmUI();
}
let rpmLoadTimer = null, rpmReady = false;
function openRpmCreator() {
  rpmReady = false;
  const f = $('rpmFrame');
  $('rpmHint').textContent = 'Loading the character creator…';
  $('rpmHint').classList.remove('err');
  f.src = rpmCreatorUrl();
  $('rpmModal').hidden = false;
  clearTimeout(rpmLoadTimer);
  rpmLoadTimer = setTimeout(() => {
    if (!rpmReady) {
      $('rpmHint').innerHTML = 'The creator didn’t load — you may be offline or it’s blocked here. ' +
        'Close this and either style the quick avatar in <b>Appearance</b>, or <b>Upload</b> your own .vrm/.glb (make one free in VRoid Studio).';
      $('rpmHint').classList.add('err');
    }
  }, 9000);
}
$('openRpm').onclick = openRpmCreator;
if ($('lobbyCreateChar')) $('lobbyCreateChar').onclick = openRpmCreator;
if ($('lobbyUploadChar')) $('lobbyUploadChar').onclick = () => $('avatarFile').click();
$('closeRpm').onclick = () => { $('rpmModal').hidden = true; $('rpmFrame').src = 'about:blank'; clearTimeout(rpmLoadTimer); };
$('applyRpmUrl').onclick = () => {
  const u = $('rpmUrl').value.trim();
  if (/^https:\/\/\S+\.(glb|vrm|fbx)(\?\S*)?$/i.test(u)) { setAvatarUrl(u); toast('Loading avatar…'); }
  else toast('Enter an https URL ending in .vrm, .glb or .fbx');
};
$('clearRpm').onclick = () => { setAvatarUrl(''); toast('Using original avatar'); };

// Upload the user's own .vrm/.glb to this server, then use its shareable URL
$('uploadAvatarBtn').onclick = () => $('avatarFile').click();
$('avatarFile').onchange = async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['vrm', 'glb', 'fbx'].includes(ext)) { toast('Use a .vrm, .glb or .fbx file'); return; }
  if (file.size > 45 * 1024 * 1024) { toast('File too large (max 45 MB)'); return; }
  toast('Uploading avatar…');
  try {
    const res = await fetch('/api/upload-avatar?ext=' + ext, { method: 'POST', body: file });
    const data = await res.json();
    if (data.url) { setAvatarUrl(data.url); toast('Avatar uploaded ✓'); }
    else toast('Upload failed');
  } catch { toast('Upload failed'); }
  e.target.value = '';
};

// Receive the exported .glb from the Ready Player Me iframe
window.addEventListener('message', (ev) => {
  let json = ev.data;
  if (typeof json === 'string') {
    if (/\.glb(\?|$)/i.test(json) && json.startsWith('http')) { onRpmExport(json); return; }
    try { json = JSON.parse(json); } catch { return; }
  }
  if (!json || json.source !== 'readyplayerme') return;
  if (json.eventName === 'v1.frame.ready') {
    rpmReady = true; clearTimeout(rpmLoadTimer);
    $('rpmHint').textContent = 'Build your character, then press the button in the creator to finish — it loads in automatically.';
    $('rpmHint').classList.remove('err');
    try { $('rpmFrame').contentWindow.postMessage(JSON.stringify({ target: 'readyplayerme', type: 'subscribe', eventName: 'v1.**' }), '*'); } catch {}
  }
  if (json.eventName === 'v1.avatar.exported' && json.data && json.data.url) onRpmExport(json.data.url);
});
function onRpmExport(url) {
  clearTimeout(rpmLoadTimer);
  $('rpmModal').hidden = true; $('rpmFrame').src = 'about:blank';
  setAvatarUrl(url);
  toast('Realistic avatar loaded ✓');
}

// privacy
function syncVisibilityUI() {
  if (!myProfile) return;
  document.querySelectorAll('input[name="vis"]').forEach(r => { r.checked = (r.value === myProfile.visibility); });
}
document.querySelectorAll('input[name="vis"]').forEach(r => {
  r.onchange = () => { if (r.checked) { send({ type: 'setVisibility', visibility: r.value }); toast(`Room visibility: ${r.value}`); } };
});
$('whereisBtn').onclick = () => {
  const name = $('whereisName').value.trim();
  if (name) send({ type: 'whereis', name });
};
function onWhereis(m) {
  const el = $('whereisResult');
  if (!m.online && !m.userId) { el.innerHTML = `<span class="no">No user named “${esc(m.name || '')}” found.</span>`; return; }
  if (!m.online) { el.innerHTML = `<span class="no">${esc(m.name)} is offline.</span>`; return; }
  if (m.visible && m.roomName) el.innerHTML = `<span class="ok">${esc(m.name)} is in <b>${esc(m.roomName)}</b>.</span>`;
  else el.innerHTML = `<span class="no">${esc(m.name)} is online, but their room is <b>hidden</b> from you.</span>`;
}

// friends
$('addFriendBtn').onclick = () => {
  const n = $('addFriendName').value.trim();
  if (n) send({ type: 'addFriend', name: n });
};
function onFriendResult(m) {
  const el = $('friendMsg');
  if (!m.ok) { el.textContent = m.reason || 'Could not add.'; return; }
  el.textContent = m.mutual ? `You and ${m.targetName} are now mutual friends.` : `Request sent to ${m.targetName}. They must add you back.`;
  $('addFriendName').value = '';
}
function buildFriendList() {
  const el = $('friendList'); if (!el || !myProfile) return;
  el.innerHTML = '';
  if (!myProfile.friends || !myProfile.friends.length) { el.innerHTML = '<div class="muted">No friends yet.</div>'; return; }
  for (const f of myProfile.friends) {
    const row = document.createElement('div'); row.className = 'friend-row';
    row.innerHTML = `<span class="dot"></span>${esc(f.name || f.id)}`;
    el.appendChild(row);
  }
}
function onPresence(users) {
  const el = $('presenceList'); if (!el) return;
  el.innerHTML = '';
  for (const u of users) {
    if (u.id === uid) continue;
    const row = document.createElement('div'); row.className = 'presence-row';
    let loc;
    if (u.roomName) loc = `<span class="loc">in ${esc(u.roomName)}</span>`;
    else loc = `<span class="loc hidden">location hidden</span>`;
    row.innerHTML = `<span class="dot"></span>${esc(u.name)}${u.isFriend ? ' <small style="color:var(--accent2)">friend</small>' : ''}${loc}`;
    el.appendChild(row);
  }
  if (!el.children.length) el.innerHTML = '<div class="muted">Nobody else online.</div>';
}

// ================= Penthouse (Midnight Romance) =================
// Premium luxury penthouse — original procedural architecture & furniture in a
// burgundy / wine / charcoal / champagne-gold palette, with a real licensed
// damask chair asset. Warm PBR lighting, animated night skyline + jacuzzi water,
// and Day/Sunset/Night/Romantic atmosphere presets. (No intimacy system.)
const pMat = (c, r, m) => new THREE.MeshStandardMaterial({ color: new THREE.Color(c), roughness: r, metalness: m || 0 });

function buildPenthouse(def) {
  const g = roomMeshGroup;
  const W = def.w, D = def.d, H = 4.2;
  const GOLD = '#c8a95e', WINE = '#5a1a2e', VELVET = '#6b1f3a', CREAM = '#d8cdb8';
  const goldMat = pMat(GOLD, 0.35, 0.9), marbleMat = pMat('#2a2633', 0.22, 0.12),
        velvetMat = pMat(VELVET, 0.92, 0), wineMat = pMat(WINE, 0.88, 0), creamMat = pMat(CREAM, 0.8, 0);

  scene.background = new THREE.Color('#0a0710');
  scene.environment = envFromGradient('#4a2a40', '#1a1020', '#0a0710');
  scene.fog = new THREE.Fog(new THREE.Color('#0a0710'), W * 1.4, W * 3);

  // floor (dark marble) + ceiling
  const floor = new THREE.Mesh(new THREE.BoxGeometry(W, 0.3, D), pMat('#241f2b', 0.22, 0.14));
  floor.position.y = -0.15; floor.receiveShadow = true; g.add(floor);
  const ceil = new THREE.Mesh(new THREE.BoxGeometry(W, 0.3, D), pMat('#1a141c', 1, 0)); ceil.position.y = H; g.add(ceil);

  // 3 solid walls
  const wallMat = pMat('#2a1d28', 0.9, 0);
  const wall = (w, h, d, x, y, z) => { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), wallMat); m.position.set(x, y, z); m.receiveShadow = true; g.add(m); };
  wall(W, H, 0.3, 0, H / 2, -D / 2); wall(0.3, H, D, -W / 2, H / 2, 0); wall(0.3, H, D, W / 2, H / 2, 0);
  // decorative wall panels (back wall)
  for (let i = -3; i <= 3; i++) { const p = new THREE.Mesh(new THREE.BoxGeometry(1.1, H - 1.2, 0.08), pMat(i % 2 ? '#3a1226' : '#2a1020', 0.8, 0.05)); p.position.set(i * 1.3, H / 2, -D / 2 + 0.2); g.add(p); }

  // cove ceiling lighting (emissive gold strips)
  const coveMat = new THREE.MeshStandardMaterial({ color: GOLD, emissive: new THREE.Color(GOLD), emissiveIntensity: 1.2, roughness: 0.4 });
  for (const [w, d, x, z] of [[W - 1, 0.12, 0, -D / 2 + 0.4], [0.12, D - 1, -W / 2 + 0.4, 0], [0.12, D - 1, W / 2 - 0.4, 0]]) {
    const srp = new THREE.Mesh(new THREE.BoxGeometry(w, 0.12, d), coveMat); srp.position.set(x, H - 0.3, z); g.add(srp);
  }

  // front floor-to-ceiling glass + gold mullions + night skyline + balcony
  const glassMat = new THREE.MeshStandardMaterial({ color: '#bfe0ff', transparent: true, opacity: 0.1, roughness: 0.02, metalness: 0, side: THREE.DoubleSide });
  const glass = new THREE.Mesh(new THREE.BoxGeometry(W, H, 0.06), glassMat); glass.position.set(0, H / 2, D / 2 - 0.2); g.add(glass);
  for (let i = -2; i <= 2; i++) { const mull = new THREE.Mesh(new THREE.BoxGeometry(0.1, H, 0.1), goldMat); mull.position.set(i * W / 5, H / 2, D / 2 - 0.15); g.add(mull); }
  const skyTex = makeSkylineTexture();
  const skyMat = new THREE.MeshBasicMaterial({ map: skyTex, fog: false });
  const sky = new THREE.Mesh(new THREE.PlaneGeometry(W * 2.4, H * 2.6), skyMat); sky.position.set(0, H * 0.75, D / 2 + 9); g.add(sky);
  const balcony = new THREE.Mesh(new THREE.BoxGeometry(W, 0.2, 3), pMat('#2a2633', 0.3, 0.1)); balcony.position.set(0, -0.1, D / 2 + 1.6); g.add(balcony);
  const railMat = new THREE.MeshStandardMaterial({ color: '#bfe0ff', transparent: true, opacity: 0.14, roughness: 0.03 });
  const rail = new THREE.Mesh(new THREE.BoxGeometry(W, 1.0, 0.05), railMat); rail.position.set(0, 0.5, D / 2 + 3); g.add(rail);
  for (let i = -4; i <= 4; i++) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.06, 1.0, 0.06), goldMat); p.position.set(i * W / 9, 0.5, D / 2 + 3); g.add(p); }

  // velvet curtains at glass sides
  for (const sx of [-1, 1]) { const cur = new THREE.Mesh(new THREE.BoxGeometry(1.3, H - 0.4, 0.18), velvetMat); cur.position.set(sx * (W / 2 - 1.1), H / 2 - 0.1, D / 2 - 0.45); cur.castShadow = true; g.add(cur); }

  // lighting
  const hemi = new THREE.HemisphereLight(0xffe8d0, 0x201018, 0.38); g.add(hemi);
  const key = new THREE.DirectionalLight(0xffdca8, 1.1); key.position.set(W * 0.3, H * 1.2, D * 0.2); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  const ss = Math.max(W, D) * 0.6; Object.assign(key.shadow.camera, { left: -ss, right: ss, top: ss, bottom: -ss, near: 1, far: W * 3 }); key.shadow.bias = -0.0004; key.shadow.normalBias = 0.03; g.add(key);
  const warmA = new THREE.PointLight(0xffb060, 18, 28, 2); warmA.position.set(-W * 0.25, 2.8, -D * 0.1); g.add(warmA);
  const warmB = new THREE.PointLight(0xff9050, 14, 26, 2); warmB.position.set(W * 0.2, 2.4, D * 0.1); g.add(warmB);
  const amb = new THREE.AmbientLight(0xffe0c0, 0.25); g.add(amb);   // soft base so the big room never goes pitch black

  // furniture: king bed (original) + real licensed velvet sofa (CC-BY)
  buildBed(g, -W * 0.3, -D * 0.2, velvetMat, creamMat, goldMat);
  loadFurniture('/models/furniture/GlamVelvetSofa.glb', W * 0.16, D * 0.06, 3.4, Math.PI, g,
    () => buildSofa(g, W * 0.16, D * 0.06, velvetMat, goldMat));   // procedural fallback
  buildCoffeeTable(g, W * 0.16, D * 0.06 - 2.2, marbleMat, goldMat);
  // furniture colliders (keep avatars from walking through the big pieces)
  penthouseColliders.push({ x: -W * 0.3, z: -D * 0.2, r: 1.7 });   // bed
  penthouseColliders.push({ x: W * 0.16, z: D * 0.06, r: 1.9 });   // sofa
  penthouseColliders.push({ x: W * 0.16, z: D * 0.06 - 2.2, r: 1.0 }); // coffee table
  penthouseColliders.push({ x: W * 0.3, z: D * 0.3, r: 2.0 });     // jacuzzi
  const rug = new THREE.Mesh(new THREE.CircleGeometry(3.3, 40), pMat('#3a1024', 0.96, 0)); rug.rotation.x = -Math.PI / 2; rug.position.set(W * 0.16, 0.015, D * 0.06 - 1.1); g.add(rug);
  buildLampTable(g, W * 0.16 - 3.8, D * 0.06 + 1.0, goldMat);
  buildLampTable(g, -W * 0.3 - 2.6, -D * 0.2, goldMat);
  buildPlant(g, -W / 2 + 1.3, D / 2 - 2.2); buildPlant(g, W / 2 - 1.3, -D / 2 + 1.6);
  for (let i = -1; i <= 1; i++) {
    const art = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 1.9), new THREE.MeshStandardMaterial({ color: new THREE.Color().setHSL(0.93, 0.5, 0.28 + 0.08 * i), roughness: 0.6, emissive: new THREE.Color('#2a0a1a'), emissiveIntensity: 0.3 }));
    art.position.set(W / 2 - 0.25, 2.3, i * 2.4); art.rotation.y = -Math.PI / 2; g.add(art);
  }
  const water = buildJacuzzi(g, W * 0.3, D * 0.3, marbleMat, goldMat);
  const petals = buildPetals(g, -W * 0.3, -D * 0.2);   // on the bed, hidden unless Romantic

  // real licensed furniture: damask upholstered chairs (CC-BY, Wayfair) — see CREDITS
  gltfLoader.load('/models/furniture/ChairDamaskPurplegold.glb', (gl) => {
    const proto = gl.scene; proto.traverse(o => { if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; } });
    const bb = new THREE.Box3().setFromObject(proto); const hh = bb.max.y - bb.min.y; const sc = hh > 0.001 ? 1.15 / hh : 1;
    for (const [x, z, rot] of [[W * 0.02, D * 0.06 + 1.9, Math.PI], [W * 0.33, D * 0.06 + 1.0, -2.3]]) {
      const c = proto.clone(true); c.scale.setScalar(sc); const b2 = new THREE.Box3().setFromObject(c); c.position.set(x, -b2.min.y, z); c.rotation.y = rot; g.add(c);
      penthouseSeats.push({ x, z: z - 0.35, rot: rot + Math.PI, label: 'Chair' });
    }
  }, undefined, (e) => console.warn('[penthouse] chair load failed:', e && e.message));

  // sit spots on sofa + bed
  penthouseSeats.push({ x: W * 0.16 - 1.4, z: D * 0.06 + 0.2, rot: Math.PI, label: 'Sofa' });
  penthouseSeats.push({ x: W * 0.16, z: D * 0.06 + 0.2, rot: Math.PI, label: 'Sofa' });
  penthouseSeats.push({ x: W * 0.16 + 1.4, z: D * 0.06 + 0.2, rot: Math.PI, label: 'Sofa' });
  penthouseSeats.push({ x: -W * 0.3, z: -D * 0.2 + 0.8, rot: 0, label: 'Bed' });

  // atmosphere presets
  const P = {
    day:      { bg: '#aec2d6', hemi: 1.1, key: 1.9, keyCol: 0xffffff, warm: 6, amb: 0.5, sky: 0.25, cove: 0.3, fog: [W * 2.4, W * 4.4] },
    sunset:   { bg: '#c06a3c', hemi: 0.8, key: 1.6, keyCol: 0xff9a4a, warm: 14, amb: 0.4, sky: 0.65, cove: 0.9, fog: [W * 1.8, W * 3.6] },
    night:    { bg: '#12101e', hemi: 0.6, key: 1.1, keyCol: 0x9fb0ff, warm: 20, amb: 0.3, sky: 1.0, cove: 1.2, fog: [W * 1.6, W * 3.2] },
    romantic: { bg: '#1e0a16', hemi: 0.42, key: 0.7, keyCol: 0xff8a5a, warm: 26, amb: 0.28, sky: 1.0, cove: 1.3, fog: [W * 1.3, W * 2.8] },
  };
  setAtmosphere = (name) => {
    const p = P[name] || P.night;
    scene.background.set(p.bg); scene.fog.color.set(p.bg); scene.fog.near = p.fog[0]; scene.fog.far = p.fog[1];
    hemi.intensity = p.hemi; key.intensity = p.key; key.color.setHex(p.keyCol); amb.intensity = p.amb;
    warmA.intensity = p.warm; warmB.intensity = p.warm * 0.7; coveMat.emissiveIntensity = p.cove;
    skyMat.color.setScalar(0.55 + 0.45 * p.sky);
    petals.visible = (name === 'romantic');
    document.querySelectorAll('#atmoBar button').forEach(b => b.classList.toggle('on', b.dataset.atmo === name));
  };
  setAtmosphere('night');

  let t = 0;
  roomUpdate = (dt) => { t += dt; if (water) animateWater(water, t); };
  buildPenthouseUI();
}

// load a GLB furniture piece: scale to target footprint, centre, drop to floor,
// rotate about its centre; call fallback() on failure.
function loadFurniture(url, x, z, targetW, rotY, g, fallback) {
  gltfLoader.load(url, (gl) => {
    const s = gl.scene; s.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; o.frustumCulled = false; } });
    const bb = new THREE.Box3().setFromObject(s); const w = Math.max(bb.max.x - bb.min.x, bb.max.z - bb.min.z); const sc = w > 0.001 ? targetW / w : 1;
    s.scale.setScalar(sc);
    const b2 = new THREE.Box3().setFromObject(s); const cx = (b2.min.x + b2.max.x) / 2, cz = (b2.min.z + b2.max.z) / 2;
    const pivot = new THREE.Group(); pivot.position.set(x, 0, z); pivot.rotation.y = rotY || 0;
    s.position.set(-cx, -b2.min.y, -cz); pivot.add(s); g.add(pivot);
  }, undefined, (e) => { console.warn('[penthouse] furniture load failed:', url, e && e.message); if (fallback) fallback(); });
}

function makeSkylineTexture() {
  const c = document.createElement('canvas'); c.width = 1024; c.height = 512; const x = c.getContext('2d');
  const grd = x.createLinearGradient(0, 0, 0, 512); grd.addColorStop(0, '#0a0e2a'); grd.addColorStop(0.55, '#1a1038'); grd.addColorStop(1, '#2a1230');
  x.fillStyle = grd; x.fillRect(0, 0, 1024, 512);
  x.fillStyle = '#fef3c0'; x.beginPath(); x.arc(840, 90, 34, 0, 7); x.fill();           // moon
  x.globalAlpha = 0.9; for (let i = 0; i < 120; i++) { x.fillStyle = '#ffffff'; x.globalAlpha = Math.random() * 0.6; x.fillRect(Math.random() * 1024, Math.random() * 180, 1.5, 1.5); } x.globalAlpha = 1;
  // buildings with lit windows
  let bx = 0; while (bx < 1024) { const bw = 40 + Math.random() * 70, bh = 120 + Math.random() * 260; const by = 512 - bh;
    x.fillStyle = `rgb(${10 + Math.random() * 20},${8 + Math.random() * 16},${20 + Math.random() * 24})`; x.fillRect(bx, by, bw, bh);
    for (let wy = by + 8; wy < 500; wy += 14) for (let wx = bx + 5; wx < bx + bw - 6; wx += 12) { if (Math.random() < 0.45) { x.fillStyle = Math.random() < 0.8 ? '#ffd27a' : '#bfe0ff'; x.fillRect(wx, wy, 5, 7); } }
    bx += bw + 6; }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function buildBed(g, x, z, velvet, cream, gold) {
  const base = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.5, 2.3), pMat('#1e1620', 0.7, 0)); base.position.set(x, 0.25, z); base.castShadow = base.receiveShadow = true; g.add(base);
  const head = new THREE.Mesh(new THREE.BoxGeometry(2.5, 1.5, 0.25), velvet); head.position.set(x, 1.0, z - 1.15); head.castShadow = true; g.add(head);
  for (let i = -2; i <= 2; i++) for (let j = 0; j < 3; j++) { const b = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 8), gold); b.position.set(x + i * 0.5, 0.6 + j * 0.4, z - 1.02); g.add(b); } // tufting buttons
  const mat = new THREE.Mesh(new THREE.BoxGeometry(2.3, 0.35, 2.2), cream); mat.position.set(x, 0.62, z); mat.castShadow = true; g.add(mat);
  const duvet = new THREE.Mesh(new THREE.BoxGeometry(2.32, 0.18, 1.4), pMat('#6b1f3a', 0.9, 0)); duvet.position.set(x, 0.82, z + 0.4); g.add(duvet);
  for (const px of [-0.6, 0.6]) { const pil = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.22, 0.55), cream); pil.position.set(x + px, 0.86, z - 0.75); g.add(pil); }
}
function buildSofa(g, x, z, velvet, gold) {
  // shallow curved 3-seg velvet sofa facing -z (toward lounge)
  for (let i = -1; i <= 1; i++) {
    const a = i * 0.32;
    const seat = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.45, 0.95), velvet); seat.position.set(x + i * 1.35, 0.42, z + Math.abs(i) * 0.25); seat.rotation.y = -a; seat.castShadow = true; g.add(seat);
    const back = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.9, 0.28), velvet); back.position.set(x + i * 1.35, 0.85, z + 0.5 + Math.abs(i) * 0.25); back.rotation.y = -a; g.add(back);
    const cush = new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.22, 0.8), pMat('#7a2742', 0.9, 0)); cush.position.set(x + i * 1.35, 0.6, z + Math.abs(i) * 0.25); cush.rotation.y = -a; g.add(cush);
  }
  for (const ax of [-2.3, 2.3]) { const arm = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.7, 1.0), velvet); arm.position.set(x + ax, 0.55, z + 0.4); g.add(arm); }
}
function buildCoffeeTable(g, x, z, marble, gold) {
  const top = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.12, 36), pMat('#e8e3d8', 0.25, 0.05)); top.position.set(x, 0.42, z); top.castShadow = true; g.add(top);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.28, 0.42, 24), gold); base.position.set(x, 0.2, z); g.add(base);
}
function buildLampTable(g, x, z, gold) {
  const t = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.55, 0.7), pMat('#2a2030', 0.6, 0.1)); t.position.set(x, 0.3, z); t.castShadow = true; g.add(t);
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.7, 12), gold); pole.position.set(x, 0.95, z); g.add(pole);
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.3, 0.3, 20, 1, true), new THREE.MeshStandardMaterial({ color: '#f5e2b0', emissive: new THREE.Color('#ffcf7a'), emissiveIntensity: 0.9, roughness: 0.7, side: THREE.DoubleSide })); shade.position.set(x, 1.35, z); g.add(shade);
  const l = new THREE.PointLight(0xffcf8a, 6, 6, 2); l.position.set(x, 1.3, z); g.add(l);
}
function buildPlant(g, x, z) {
  const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.22, 0.5, 20), pMat('#3a3038', 0.6, 0.1)); pot.position.set(x, 0.25, z); pot.castShadow = true; g.add(pot);
  for (let i = 0; i < 6; i++) { const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.9, 6), pMat('#2f5a3a', 0.8, 0)); leaf.position.set(x + (Math.random() - 0.5) * 0.3, 0.9 + Math.random() * 0.3, z + (Math.random() - 0.5) * 0.3); leaf.rotation.set(Math.random() * 0.5, Math.random() * 6, Math.random() * 0.5); g.add(leaf); }
}
function buildJacuzzi(g, x, z, marble, gold) {
  const surround = new THREE.Mesh(new THREE.CylinderGeometry(1.9, 1.9, 0.7, 40), pMat('#e8e3d8', 0.3, 0.05)); surround.position.set(x, 0.35, z); surround.castShadow = surround.receiveShadow = true; g.add(surround);
  const inner = new THREE.Mesh(new THREE.CylinderGeometry(1.55, 1.55, 0.6, 40, 1, true), pMat('#1a2630', 0.4, 0.2)); inner.position.set(x, 0.42, z); g.add(inner);
  const water = new THREE.Mesh(new THREE.CircleGeometry(1.5, 48), new THREE.MeshStandardMaterial({ color: '#2a6a8a', roughness: 0.12, metalness: 0.35, transparent: true, opacity: 0.9 }));
  water.rotation.x = -Math.PI / 2; water.position.set(x, 0.66, z); g.add(water);
  water.geometry.userData = { base: water.geometry.attributes.position.array.slice() };
  // candles: emissive flames (no per-candle light — keeps the point-light count
  // low so the shader compiles; the warm ambience comes from the room lights)
  const flameMat = new THREE.MeshStandardMaterial({ color: '#ffd090', emissive: new THREE.Color('#ffa040'), emissiveIntensity: 2.2, roughness: 0.5 });
  for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI * 2; const cx = x + Math.cos(a) * 2.1, cz = z + Math.sin(a) * 2.1;
    const candle = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.22, 10), pMat('#f0e6d0', 0.6, 0)); candle.position.set(cx, 0.81, cz); g.add(candle);
    const flame = new THREE.Mesh(new THREE.SphereGeometry(0.04, 8, 8), flameMat); flame.scale.y = 1.8; flame.position.set(cx, 0.98, cz); g.add(flame);
  }
  return water;
}
function animateWater(water, t) {
  const pos = water.geometry.attributes.position; const base = water.geometry.userData.base;
  for (let i = 0; i < pos.count; i++) { const bx = base[i * 3], by = base[i * 3 + 1]; pos.array[i * 3 + 2] = Math.sin(bx * 2.5 + t * 2) * 0.03 + Math.cos(by * 3 + t * 1.6) * 0.03; }
  pos.needsUpdate = true;
}
function buildPetals(g, x, z) {
  const group = new THREE.Group(); group.visible = false;
  const m = pMat('#c01030', 0.7, 0);
  for (let i = 0; i < 40; i++) { const pet = new THREE.Mesh(new THREE.CircleGeometry(0.06, 6), m); pet.rotation.x = -Math.PI / 2; pet.position.set(x + (Math.random() - 0.5) * 2.2, 0.86, z + (Math.random() - 0.5) * 1.8); group.add(pet); }
  g.add(group); return group;
}
function buildPenthouseUI() {
  let bar = document.getElementById('atmoBar');
  if (!bar) {
    bar = document.createElement('div'); bar.id = 'atmoBar'; bar.className = 'atmo-bar';
    for (const [k, label] of [['day', '☀ Day'], ['sunset', '🌇 Sunset'], ['night', '🌙 Night'], ['romantic', '🕯 Romantic']]) {
      const b = document.createElement('button'); b.dataset.atmo = k; b.textContent = label; b.onclick = () => { if (setAtmosphere) setAtmosphere(k); }; bar.appendChild(b);
    }
    const mus = document.createElement('button'); mus.id = 'musicBtn'; mus.textContent = '♪ Music'; mus.onclick = toggleMusic; bar.appendChild(mus);
    document.getElementById('world').appendChild(bar);
  }
  bar.hidden = false;
}

// soft generated ambient pad (no external audio asset bundled)
let audioCtx = null, musicGain = null, musicOn = false;
function toggleMusic() {
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      musicGain = audioCtx.createGain(); musicGain.gain.value = 0.06; musicGain.connect(audioCtx.destination);
      const lp = audioCtx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 700; lp.connect(musicGain);
      [110, 164.81, 220].forEach((f, i) => { const o = audioCtx.createOscillator(); o.type = 'sine'; o.frequency.value = f; const d = audioCtx.createOscillator(); d.type = 'sine'; d.frequency.value = f * 1.003; const gg = audioCtx.createGain(); gg.gain.value = 0.5; o.connect(gg); d.connect(gg); gg.connect(lp); o.start(); d.start(); });
    }
    musicOn = !musicOn;
    audioCtx.resume();
    musicGain.gain.setTargetAtTime(musicOn ? 0.06 : 0.0, audioCtx.currentTime, 0.3);
    document.getElementById('musicBtn').classList.toggle('on', musicOn);
  } catch (e) { toast('Audio not available'); }
}

// ================= helpers =================
function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
function damp(a, b, lambda, dt) { return a + (b - a) * (1 - Math.exp(-lambda * dt)); }
function dampAngle(a, b, lambda, dt) {
  let d = ((b - a + Math.PI) % (Math.PI * 2)) - Math.PI;
  if (d < -Math.PI) d += Math.PI * 2;
  return a + d * (1 - Math.exp(-lambda * dt));
}
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
function disposeGroup(g) { g.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) { const mm = Array.isArray(o.material) ? o.material : [o.material]; mm.forEach(m => { if (m.map) m.map.dispose(); m.dispose && m.dispose(); }); } }); }
let toastTimer = null;
function toast(msg) { const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, 2200); }

// boot
connect();
