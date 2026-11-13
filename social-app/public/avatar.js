// avatar.js — original rigged humanoid for Driftspace.
// A procedurally generated SkinnedMesh human: good proportions, PBR materials,
// cross-joint skin weighting (smooth bends), and hand-authored idle + walk clips.
// Fully original geometry — no third-party models or captured assets.
import * as THREE from 'three';
import { makeArmPoser, makeEmoteApi, restMap, EMOTES } from './rpmAvatar.js';

// --- Bind-pose skeleton (A-pose, metres, feet at y=0) -----------------------
// name, absolute bind position, parent name
const BONES = [
  ['hips',      [0.00, 0.98, 0.00], null],
  ['spine',     [0.00, 1.12, 0.00], 'hips'],
  ['chest',     [0.00, 1.30, 0.00], 'spine'],
  ['neck',      [0.00, 1.46, 0.00], 'chest'],
  ['head',      [0.00, 1.57, 0.00], 'neck'],
  ['shoulderL', [0.055,1.42, 0.00], 'chest'],
  ['upperArmL', [0.17, 1.40, 0.00], 'shoulderL'],
  ['lowerArmL', [0.17, 1.13, 0.00], 'upperArmL'],
  ['handL',     [0.17, 0.89, 0.00], 'lowerArmL'],
  ['shoulderR', [-0.055,1.42,0.00], 'chest'],
  ['upperArmR', [-0.17, 1.40,0.00], 'shoulderR'],
  ['lowerArmR', [-0.17, 1.13,0.00], 'upperArmR'],
  ['handR',     [-0.17, 0.89,0.00], 'lowerArmR'],
  ['upLegL',    [0.085,0.92, 0.00], 'hips'],
  ['loLegL',    [0.095,0.52, 0.00], 'upLegL'],
  ['footL',     [0.095,0.07, 0.00], 'loLegL'],
  ['upLegR',    [-0.085,0.92,0.00], 'hips'],
  ['loLegR',    [-0.095,0.52,0.00], 'upLegR'],
  ['footR',     [-0.095,0.07,0.00], 'loLegR'],
];
const IDX = Object.fromEntries(BONES.map((b, i) => [b[0], i]));
const ABS = Object.fromEntries(BONES.map(b => [b[0], new THREE.Vector3(...b[1])]));

function buildSkeleton() {
  const bones = BONES.map(([name, pos, parent]) => {
    const b = new THREE.Bone();
    b.name = name;
    const p = parent ? ABS[parent] : new THREE.Vector3();
    b.position.set(pos[0] - p.x, pos[1] - p.y, pos[2] - p.z);
    return b;
  });
  BONES.forEach(([name, , parent], i) => { if (parent) bones[IDX[parent]].add(bones[i]); });
  return bones;
}

// --- Geometry builder (accumulates into material buckets) -------------------
class Buckets {
  constructor() { this.b = {}; }
  bucket(name) {
    if (!this.b[name]) this.b[name] = { pos: [], norm: [], si: [], sw: [], idx: [], count: 0 };
    return this.b[name];
  }
}

const _ref = new THREE.Vector3(), _axis = new THREE.Vector3(), _u = new THREE.Vector3(),
      _v = new THREE.Vector3(), _p = new THREE.Vector3();

// weights for a vertex at param t (0 at A end .. 1 at B end)
function weightsAt(t, main, child, parent) {
  let cw = 0, pw = 0;
  if (child != null && t > 0.68) cw = ((t - 0.68) / 0.32) * 0.5;
  if (parent != null && t < 0.26) pw = (1 - t / 0.26) * 0.4;
  const mw = Math.max(0.0001, 1 - cw - pw);
  const s = mw + cw + pw;
  return [
    main, child != null ? child : 0, parent != null ? parent : 0, 0,
    mw / s, cw / s, pw / s, 0,
  ];
}

// A tapered tube from A to B. mainBone drives it; blends to child (distal) / parent (proximal).
function tube(buk, A, B, rA, rB, mainBone, childBone, parentBone, radial = 12, rings = 8) {
  const g = buk;
  const base = g.count;
  _axis.copy(B).sub(A); const len = _axis.length(); _axis.normalize();
  _ref.set(0, 1, 0); if (Math.abs(_axis.y) > 0.9) _ref.set(1, 0, 0);
  _u.crossVectors(_ref, _axis).normalize();
  _v.crossVectors(_axis, _u).normalize();
  const mi = IDX[mainBone], ci = childBone != null ? IDX[childBone] : null, pi = parentBone != null ? IDX[parentBone] : null;
  for (let r = 0; r <= rings; r++) {
    const t = r / rings;
    const radius = rA + (rB - rA) * t;
    const w = weightsAt(t, mi, ci, pi);
    for (let s = 0; s < radial; s++) {
      const a = (s / radial) * Math.PI * 2;
      const dir = _u.clone().multiplyScalar(Math.cos(a)).addScaledVector(_v, Math.sin(a));
      _p.copy(A).addScaledVector(_axis, len * t).addScaledVector(dir, radius);
      g.pos.push(_p.x, _p.y, _p.z);
      g.norm.push(dir.x, dir.y, dir.z);
      g.si.push(w[0], w[1], w[2], w[3]);
      g.sw.push(w[4], w[5], w[6], w[7]);
    }
  }
  for (let r = 0; r < rings; r++) {
    for (let s = 0; s < radial; s++) {
      const a = base + r * radial + s;
      const b = base + r * radial + ((s + 1) % radial);
      const c = base + (r + 1) * radial + s;
      const d = base + (r + 1) * radial + ((s + 1) % radial);
      g.idx.push(a, c, b, b, c, d);
    }
  }
  g.count += (rings + 1) * radial;
}

// An ellipsoid (sphere scaled) fully weighted to one bone.
function blob(buk, center, radius, scale, boneName, wseg = 14, hseg = 12) {
  const g = buk;
  const base = g.count;
  const bi = IDX[boneName];
  const sx = scale[0], sy = scale[1], sz = scale[2];
  for (let i = 0; i <= hseg; i++) {
    const phi = (i / hseg) * Math.PI;
    for (let j = 0; j <= wseg; j++) {
      const th = (j / wseg) * Math.PI * 2;
      const nx = Math.sin(phi) * Math.cos(th), ny = Math.cos(phi), nz = Math.sin(phi) * Math.sin(th);
      g.pos.push(center.x + nx * radius * sx, center.y + ny * radius * sy, center.z + nz * radius * sz);
      const n = new THREE.Vector3(nx / sx, ny / sy, nz / sz).normalize();
      g.norm.push(n.x, n.y, n.z);
      g.si.push(bi, 0, 0, 0); g.sw.push(1, 0, 0, 0);
    }
  }
  for (let i = 0; i < hseg; i++) {
    for (let j = 0; j < wseg; j++) {
      const a = base + i * (wseg + 1) + j, b = a + 1;
      const c = base + (i + 1) * (wseg + 1) + j, d = c + 1;
      g.idx.push(a, c, b, b, c, d);
    }
  }
  g.count += (hseg + 1) * (wseg + 1);
}

// cone skirt for dresses
function skirt(buk, topY, botY, rTop, rBot, boneTop, boneBot, radial = 16) {
  const g = buk; const base = g.count;
  const bt = IDX[boneTop], bb = IDX[boneBot];
  for (let r = 0; r <= 1; r++) {
    const y = r === 0 ? topY : botY, rad = r === 0 ? rTop : rBot;
    for (let s = 0; s < radial; s++) {
      const a = (s / radial) * Math.PI * 2;
      g.pos.push(Math.cos(a) * rad, y, Math.sin(a) * rad);
      g.norm.push(Math.cos(a), 0.3, Math.sin(a));
      if (r === 0) { g.si.push(bt, 0, 0, 0); g.sw.push(1, 0, 0, 0); }
      else { g.si.push(bb, bt, 0, 0); g.sw.push(0.6, 0.4, 0, 0); }
    }
  }
  for (let s = 0; s < radial; s++) {
    const a = base + s, b = base + ((s + 1) % radial);
    const c = base + radial + s, d = base + radial + ((s + 1) % radial);
    g.idx.push(a, c, b, b, c, d);
  }
  g.count += 2 * radial;
}

function makeGeometry(buk) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(buk.pos, 3));
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(buk.norm, 3));
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(buk.si, 4));
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(buk.sw, 4));
  geo.setIndex(buk.idx);
  geo.computeVertexNormals();
  return geo;
}

const OUTFITS = {
  tee:    { sleeves: false, skirt: false },
  tank:   { sleeves: false, skirt: false },
  hoodie: { sleeves: true,  skirt: false, bulk: 1.12 },
  jacket: { sleeves: true,  skirt: false, bulk: 1.06 },
  dress:  { sleeves: false, skirt: true },
  shorts: { sleeves: false, skirt: false, shirtless: true },   // beach: bare torso + shorts
};

// Body type multipliers (original parametric proportions, not a likeness of any
// specific person): shoulder width, chest, waist, hip, arm & leg thickness.
const BODY_TYPES = {
  feminine: { shoulder: 0.9, chest: 0.96, waist: 0.84, hip: 1.12, arm: 0.84, leg: 0.96, legOut: 1.0 },
  neutral:  { shoulder: 1.0, chest: 1.0,  waist: 1.0,  hip: 1.0,  arm: 1.0,  leg: 1.0, legOut: 1.0 },
  athletic: { shoulder: 1.12, chest: 1.1, waist: 0.92, hip: 1.0,  arm: 1.14, leg: 1.08, legOut: 1.0 },
  male:     { shoulder: 1.22, chest: 1.14, waist: 1.0, hip: 0.9,  arm: 1.2,  leg: 1.12, legOut: 1.0 },
};

export function createAvatar(opts = {}) {
  const look = Object.assign({
    bodyColor: '#f0c27b', hairColor: '#2b2b2b', outfit: 'tee', outfitColor: '#ff4fd8', hairStyle: 'long', body: 'feminine',
  }, opts);

  const root = new THREE.Group();
  const bones = buildSkeleton();
  root.add(bones[0]);
  root.updateMatrixWorld(true);
  const skeleton = new THREE.Skeleton(bones);

  const buckets = new Buckets();
  rebuildGeometry(buckets, look);

  const mats = {
    skin: new THREE.MeshStandardMaterial({ color: look.bodyColor, roughness: 0.62, metalness: 0.0 }),
    outfit: new THREE.MeshStandardMaterial({ color: look.outfitColor, roughness: 0.78, metalness: 0.02 }),
    hair: new THREE.MeshStandardMaterial({ color: look.hairColor, roughness: 0.5, metalness: 0.0 }),
    shoe: new THREE.MeshStandardMaterial({ color: '#23232b', roughness: 0.6, metalness: 0.05 }),
  };

  const meshes = {};
  for (const name of Object.keys(buckets.b)) {
    const m = new THREE.SkinnedMesh(makeGeometry(buckets.b[name]), mats[name] || mats.skin);
    m.castShadow = true; m.receiveShadow = false; m.frustumCulled = false;
    m.bind(skeleton);
    root.add(m);
    meshes[name] = m;
  }
  // bones[0] added to root already; skinned meshes reference the shared skeleton.

  const mixer = new THREE.AnimationMixer(root);
  const clips = { idle: idleClip(), walk: walkClip() };
  const actions = {
    idle: mixer.clipAction(clips.idle),
    walk: mixer.clipAction(clips.walk),
  };
  actions.idle.play();
  actions.walk.play(); actions.walk.setEffectiveWeight(0);
  let current = 'idle';

  // --- emote/pose support (same library as the custom avatars) ---
  const B = (n) => bones[IDX[n]];
  const hipsRestY = B('hips').position.y;
  const poseL = makeArmPoser(B('upperArmL'), B('lowerArmL'), B('upperArmL').quaternion.clone(), B('lowerArmL').quaternion.clone());
  const poseR = makeArmPoser(B('upperArmR'), B('lowerArmR'), B('upperArmR').quaternion.clone(), B('lowerArmR').quaternion.clone());
  const emoteMap = restMap({
    spine: B('spine'), chest: B('chest'), head: B('head'), hips: B('hips'),
    lleg: B('upLegL'), rleg: B('upLegR'), lknee: B('loLegL'), rknee: B('loLegR'),
    lfoot: B('footL'), rfoot: B('footR'),
  });
  const emoteApi = makeEmoteApi(emoteMap, poseL, poseR, hipsRestY);
  let emote = null, emoteT = 0;

  function setAnim(name) {
    if (name === current || !actions[name]) return;
    const from = actions[current], to = actions[name];
    to.enabled = true; to.setEffectiveTimeScale(1); to.setEffectiveWeight(1);
    to.crossFadeFrom(from, 0.25, false);
    // ensure target plays
    to.play();
    current = name;
  }

  function setAppearance(next) {
    Object.assign(look, next);
    mats.skin.color.set(look.bodyColor);
    mats.hair.color.set(look.hairColor);
    mats.outfit.color.set(look.outfitColor);
    // outfit silhouette change -> rebuild geometry
    const nb = new Buckets();
    rebuildGeometry(nb, look);
    for (const name of Object.keys(meshes)) {
      if (nb.b[name]) {
        meshes[name].geometry.dispose();
        meshes[name].geometry = makeGeometry(nb.b[name]);
        meshes[name].bind(skeleton);
        meshes[name].visible = true;
      } else {
        meshes[name].visible = false;
      }
    }
  }

  function update(dt) {
    mixer.update(dt);
    if (emote && EMOTES[emote] && current === 'idle') {
      emoteT += dt;
      B('hips').position.y = hipsRestY;
      emoteApi._reset();
      EMOTES[emote](emoteT, emoteApi);
    }
  }

  return {
    root, mixer, setAnim,
    update,
    setAppearance,
    setEmote: (name) => { if (name !== emote) { emote = name || null; emoteT = 0; } },
    get outfit() { return look.outfit; },
  };
}

function rebuildGeometry(buckets, look) {
  const of = OUTFITS[look.outfit] || OUTFITS.tee;
  const bulk = of.bulk || 1;
  const bd = BODY_TYPES[look.body] || BODY_TYPES.feminine;
  const skin = buckets.bucket('skin');
  const outfit = buckets.bucket('outfit');
  const hair = buckets.bucket('hair');
  const shoe = buckets.bucket('shoe');
  const torsoMat = of.shirtless ? skin : outfit;   // bare torso for beach shorts

  // Torso (proportions scale with body type)
  tube(torsoMat, ABS.hips, ABS.spine, 0.145 * bulk * bd.hip, 0.155 * bulk * bd.waist, 'hips', 'spine', null);
  tube(torsoMat, ABS.spine, ABS.chest, 0.155 * bulk * bd.waist, 0.175 * bulk * bd.chest, 'spine', 'chest', 'hips');
  tube(torsoMat, ABS.chest, ABS.neck, 0.175 * bulk * bd.shoulder, 0.095, 'chest', 'neck', 'spine');
  // shoulder fill
  blob(torsoMat, ABS.shoulderL, 0.075 * bulk * bd.shoulder, [1, 0.9, 1], 'chest');
  blob(torsoMat, ABS.shoulderR, 0.075 * bulk * bd.shoulder, [1, 0.9, 1], 'chest');

  // Neck + head (skin) + hair cap
  tube(skin, ABS.neck, ABS.head, 0.052, 0.05, 'neck', 'head', 'chest');
  blob(skin, new THREE.Vector3(0, 1.62, 0.005), 0.108, [0.92, 1.08, 1.0], 'head');
  // nose hint
  blob(skin, new THREE.Vector3(0, 1.60, 0.108), 0.022, [0.8, 0.9, 1], 'head');
  // hair: crown sits at the hairline (reveals forehead/face) + style-dependent length
  const hs = look.hairStyle || 'short';
  blob(hair, new THREE.Vector3(0, 1.70, -0.025), 0.118, [1.02, 0.82, 0.95], 'head');  // crown
  blob(hair, new THREE.Vector3(0, 1.605, -0.07), 0.092, [1.08, 1.4, 0.82], 'head');   // nape
  if (hs === 'long' || hs === 'wavy') {
    // long hair falling down the back and over the shoulders (original volumes)
    blob(hair, new THREE.Vector3(0, 1.32, -0.11), 0.11, [1.25, 3.1, 0.62], 'head');   // back length
    blob(hair, new THREE.Vector3(0.125, 1.34, -0.01), 0.06, [0.8, 3.2, 0.95], 'head'); // L shoulder strand
    blob(hair, new THREE.Vector3(-0.125, 1.34, -0.01), 0.06, [0.8, 3.2, 0.95], 'head');// R shoulder strand
    if (hs === 'wavy') { blob(hair, new THREE.Vector3(0, 1.1, -0.08), 0.1, [1.2, 1.6, 0.7], 'head'); } // wave at the ends
  } else if (hs === 'ponytail') {
    blob(hair, new THREE.Vector3(0, 1.74, -0.1), 0.05, [1, 1, 1], 'head');             // tie
    blob(hair, new THREE.Vector3(0, 1.45, -0.17), 0.065, [0.85, 3.0, 0.85], 'head');   // tail
  } else if (hs === 'bun') {
    blob(hair, new THREE.Vector3(0, 1.8, -0.05), 0.072, [1, 1, 1], 'head');            // bun
  }
  // 'short' adds nothing beyond crown + nape

  // Arms
  const armMat = (of.sleeves && !of.shirtless) ? outfit : skin;
  const upRL = ((of.sleeves && !of.shirtless) ? 0.056 * bulk : 0.05) * bd.arm;
  tube(armMat, ABS.upperArmL, ABS.lowerArmL, upRL, 0.044 * bd.arm, 'upperArmL', 'lowerArmL', 'shoulderL');
  tube(armMat, ABS.upperArmR, ABS.lowerArmR, upRL, 0.044 * bd.arm, 'upperArmR', 'lowerArmR', 'shoulderR');
  tube(skin, ABS.lowerArmL, ABS.handL, 0.042 * bd.arm, 0.032, 'lowerArmL', 'handL', 'upperArmL');
  tube(skin, ABS.lowerArmR, ABS.handR, 0.042 * bd.arm, 0.032, 'lowerArmR', 'handR', 'upperArmR');
  blob(skin, ABS.handL, 0.045, [0.8, 1.1, 0.6], 'handL');
  blob(skin, ABS.handR, 0.045, [0.8, 1.1, 0.6], 'handR');

  // Legs
  const thighR = 0.092 * bulk * bd.leg, shinR = 0.07 * bd.leg;
  if (of.skirt) {
    // dress skirt replaces thigh covering; shins skin
    skirt(outfit, 1.00, 0.56, 0.17 * bulk * bd.hip, 0.30 * bd.hip, 'hips', 'upLegL');
    tube(skin, ABS.upLegL, ABS.loLegL, 0.085 * bd.leg, 0.066 * bd.leg, 'upLegL', 'loLegL', 'hips');
    tube(skin, ABS.upLegR, ABS.loLegR, 0.085 * bd.leg, 0.066 * bd.leg, 'upLegR', 'loLegR', 'hips');
  } else {
    // 'shorts' covers only the thighs (outfit); otherwise trousers to the ankle
    const legMat = outfit;
    tube(legMat, ABS.upLegL, ABS.loLegL, thighR, 0.07 * bd.leg, 'upLegL', 'loLegL', 'hips');
    tube(legMat, ABS.upLegR, ABS.loLegR, thighR, 0.07 * bd.leg, 'upLegR', 'loLegR', 'hips');
  }
  const shinMat = of.shirtless ? skin : skin;   // shins are bare below shorts/trousers hem detail
  tube(shinMat, ABS.loLegL, ABS.footL, shinR, 0.045, 'loLegL', 'footL', 'upLegL');
  tube(shinMat, ABS.loLegR, ABS.footR, shinR, 0.045, 'loLegR', 'footR', 'upLegR');
  // shoes
  blob(shoe, new THREE.Vector3(ABS.footL.x, 0.035, 0.05), 0.06, [0.75, 0.55, 1.6], 'footL');
  blob(shoe, new THREE.Vector3(ABS.footR.x, 0.035, 0.05), 0.06, [0.75, 0.55, 1.6], 'footR');
}

// --- Animation authoring ----------------------------------------------------
const _e = new THREE.Euler(), _q = new THREE.Quaternion();
function quatTrack(boneName, times, eulers) {
  const values = [];
  for (const [x, y, z] of eulers) {
    _q.setFromEuler(_e.set(x, y, z));
    values.push(_q.x, _q.y, _q.z, _q.w);
  }
  return new THREE.QuaternionKeyframeTrack(`${boneName}.quaternion`, times, values);
}
const D = Math.PI / 180;

function idleClip() {
  const t = [0, 1, 2, 3, 4];
  const tracks = [
    quatTrack('spine', t, [[0,0,0],[0.02,0,0.01],[0.03,0,0],[0.02,0,-0.01],[0,0,0]]),
    quatTrack('chest', t, [[0,0,0],[0.02,0,0],[0.035,0,0],[0.02,0,0],[0,0,0]]),
    quatTrack('head',  t, [[0,0,0],[0,0.05,0],[0,0,0],[0,-0.05,0],[0,0,0]]),
    quatTrack('upperArmL', t, [[0,0,0.05],[0,0,0.08],[0,0,0.05],[0,0,0.08],[0,0,0.05]]),
    quatTrack('upperArmR', t, [[0,0,-0.05],[0,0,-0.08],[0,0,-0.05],[0,0,-0.08],[0,0,-0.05]]),
  ];
  const bob = new THREE.VectorKeyframeTrack('hips.position', t,
    pos4(0.98, [0, 0.004, 0.008, 0.004, 0]));
  tracks.push(bob);
  const clip = new THREE.AnimationClip('idle', 4, tracks);
  return clip;
}

function pos4(baseY, deltas) {
  const out = [];
  for (const d of deltas) out.push(0, baseY + d, 0);
  // hips bind local pos is (0,0.98,0); keep x,z 0
  return out.map((v, i) => (i % 3 === 1 ? v : 0));
}

function walkClip() {
  const t = [0, 0.25, 0.5, 0.75, 1.0];
  const sw = 40 * D; // leg swing amplitude
  const kn = 50 * D; // knee bend
  const ar = 32 * D; // arm swing
  const tracks = [
    // legs: hips rotate thighs about X (forward/back)
    quatTrack('upLegL', t, [[ sw,0,0],[0,0,0],[-sw,0,0],[0,0,0],[ sw,0,0]]),
    quatTrack('upLegR', t, [[-sw,0,0],[0,0,0],[ sw,0,0],[0,0,0],[-sw,0,0]]),
    // knees bend most on back-swing / contact
    quatTrack('loLegL', t, [[0,0,0],[kn,0,0],[0.15,0,0],[0.1,0,0],[0,0,0]]),
    quatTrack('loLegR', t, [[0.15,0,0],[0.1,0,0],[0,0,0],[kn,0,0],[0.15,0,0]]),
    // ankles
    quatTrack('footL', t, [[-0.1,0,0],[0.25,0,0],[0.1,0,0],[-0.2,0,0],[-0.1,0,0]]),
    quatTrack('footR', t, [[0.1,0,0],[-0.2,0,0],[-0.1,0,0],[0.25,0,0],[0.1,0,0]]),
    // arms counter-swing
    quatTrack('upperArmL', t, [[-ar,0,0.08],[0,0,0.08],[ ar,0,0.08],[0,0,0.08],[-ar,0,0.08]]),
    quatTrack('upperArmR', t, [[ ar,0,-0.08],[0,0,-0.08],[-ar,0,-0.08],[0,0,-0.08],[ ar,0,-0.08]]),
    quatTrack('lowerArmL', t, [[-0.3,0,0],[-0.4,0,0],[-0.25,0,0],[-0.4,0,0],[-0.3,0,0]]),
    quatTrack('lowerArmR', t, [[-0.3,0,0],[-0.4,0,0],[-0.25,0,0],[-0.4,0,0],[-0.3,0,0]]),
    // torso counter-rotation + bob
    quatTrack('spine', t, [[0.04,0.06,0],[0.05,0,0],[0.04,-0.06,0],[0.05,0,0],[0.04,0.06,0]]),
    quatTrack('chest', t, [[0,-0.08,0],[0,0,0],[0,0.08,0],[0,0,0],[0,-0.08,0]]),
  ];
  const bob = new THREE.VectorKeyframeTrack('hips.position', t,
    pos4(0.96, [0.0, 0.03, 0.0, 0.03, 0.0]));
  tracks.push(bob);
  return new THREE.AnimationClip('walk', 1.0, tracks);
}
