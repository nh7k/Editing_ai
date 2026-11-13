// app.js — Driftspace client: scene, networking, input, UI.
import * as THREE from 'three';
import { createAvatarController } from './avatarController.js';

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
      buildRoomList(); buildCustomizeUI(); syncVisibilityUI();
      if (joinedRoomId) send({ type: 'joinRoom', roomId: joinedRoomId }); // rejoin after reconnect
      break;
    case 'rooms': roomsCache = m.rooms; buildRoomList(); break;
    case 'roomState': onRoomState(m); break;
    case 'joined': addRemote(m.user); break;
    case 'left': removeRemote(m.id); break;
    case 'moved': onMoved(m); break;
    case 'chat': onChat(m); break;
    case 'appearance': onAppearance(m); break;
    case 'emote': { const r = remotes.get(m.id); if (r) r.avatar.setEmote(m.name || null); break; }
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
let running = false;
const clock = new THREE.Clock();

// camera orbit
let camYaw = 0, camPitch = 0.5, camDist = 5.2;
let dragging = false, lastX = 0, lastY = 0;

// local movement
const myPos = new THREE.Vector3(0, 0, 0);
let myRot = 0;
let moveTarget = null;             // click-to-move target (Vector3) or null
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
  moveTarget = null;
  localEmote = null;
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

// ================= input / movement =================
function onPointerDown(e) {
  // click-to-move if clicking floor (not UI)
  if (e.button === 0) {
    const hit = raycastFloor(e.clientX, e.clientY);
    if (hit) { moveTarget = hit; }
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
    else moveTarget = null;
  }
  if (moving && localEmote) cancelEmote();   // moving cancels an emote/pose
  const sprint = moving && (keys['shift'] || keys['shiftleft'] || keys['shiftright']);
  if (moving) {
    const spd = SPEED * (sprint ? 1.9 : 1);
    myPos.x = clamp(myPos.x + moveX * spd * dt, -roomBounds.w / 2 + 1, roomBounds.w / 2 - 1);
    myPos.z = clamp(myPos.z + moveZ * spd * dt, -roomBounds.d / 2 + 1, roomBounds.d / 2 - 1);
    myRot = Math.atan2(moveX, moveZ);
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
  syncRpmUI();
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
  if (/^https:\/\/\S+\.(glb|vrm)(\?\S*)?$/i.test(u)) { setAvatarUrl(u); toast('Loading avatar…'); }
  else toast('Enter an https URL ending in .vrm or .glb');
};
$('clearRpm').onclick = () => { setAvatarUrl(''); toast('Using original avatar'); };

// Upload the user's own .vrm/.glb to this server, then use its shareable URL
$('uploadAvatarBtn').onclick = () => $('avatarFile').click();
$('avatarFile').onchange = async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['vrm', 'glb'].includes(ext)) { toast('Use a .vrm or .glb file'); return; }
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
