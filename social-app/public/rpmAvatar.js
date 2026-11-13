// rpmAvatar.js — load a rigged humanoid .glb (Ready Player Me or any glb) and
// animate it. If the glb ships its own idle/walk/run clips, we play them through
// an AnimationMixer with cross-fades. If it ships none (RPM avatars don't), we
// drive the standard humanoid bones with an original procedural idle/walk/run
// cycle. Bone lookup is normalized so it works on RPM names ("Hips", "LeftArm")
// and Mixamo names ("mixamorigHips") alike.
import * as THREE from 'three';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from './vendor/three-vrm.module.js';
import { FBXLoader } from './vendor/FBXLoader.js';

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));   // enable .vrm (VRoid/anime) avatars
const fbxLoader = new FBXLoader();                          // enable .fbx characters (Ara 3D Gen etc.)

function norm(n) { return String(n).toLowerCase().replace(/mixamorig/g, '').replace(/[:_\s.]/g, ''); }

// --- rig-agnostic arm poser: point an upper-arm bone along a world direction ---
// Works on any humanoid rig (VRM normalized, RPM/Mixamo raw) because it rotates
// from the arm's measured rest direction toward the target, in parent space.
export function makeArmPoser(upper, lower, uRest, lRest) {
  const restDir = new THREE.Vector3(), pW = new THREE.Quaternion(), pWi = new THREE.Quaternion();
  const _d = new THREE.Quaternion(), _adj = new THREE.Quaternion(), _t = new THREE.Vector3();
  const _a = new THREE.Vector3(), _b = new THREE.Vector3();
  // measure the arm's rest direction now, from the bind pose
  upper.updateWorldMatrix(true, false); lower.updateWorldMatrix(true, false);
  _a.setFromMatrixPosition(upper.matrixWorld); _b.setFromMatrixPosition(lower.matrixWorld);
  restDir.copy(_b).sub(_a); if (restDir.lengthSq() < 1e-8) restDir.set(0, -1, 0);
  restDir.normalize();
  upper.parent.getWorldQuaternion(pW); pWi.copy(pW).invert();
  return function point(x, y, z, bend) {
    _t.set(x, y, z); if (_t.lengthSq() < 1e-8) _t.set(0, -1, 0); _t.normalize();
    _d.setFromUnitVectors(restDir, _t);
    _adj.copy(pWi).multiply(_d).multiply(pW);
    upper.quaternion.copy(uRest).premultiply(_adj);
    lower.quaternion.copy(lRest); lower.rotateX(-(bend || 0));
  };
}

// Emote/pose library — authored against an avatar that faces +Z, Y up, with
// +X to the avatar's left. Each emote receives time t and an `a` API provided
// by the driver (so the same emote works on VRM, RPM and the fallback rig).
// Arm targets are world-ish directions; legs/spine/head are euler; hipsY offset.
export const EMOTE_NAMES = ['wave', 'clap', 'dance', 'sit', 'hug', 'cheer', 'cool', 'think'];
const DOWN_L = [0.32, -0.95, 0.05], DOWN_R = [-0.32, -0.95, 0.05];
export const EMOTES = {
  wave(t, a) {
    a.Larm(DOWN_L[0], DOWN_L[1], DOWN_L[2], 0.15);
    a.Rarm(-0.25 + 0.18 * Math.sin(t * 9), 0.92, 0.18, 0.5);
    a.head(0, 0, -0.08);
  },
  clap(t, a) {
    const c = 0.18 + 0.14 * (0.5 + 0.5 * Math.sin(t * 10));
    a.Larm(c, -0.05, 0.9, 1.1); a.Rarm(-c, -0.05, 0.9, 1.1);
    a.spine(0.06, 0, 0);
  },
  dance(t, a) {
    const s = Math.sin(t * 4), s2 = Math.sin(t * 8);
    a.Larm(0.5, 0.55 + 0.25 * s, 0.1, 0.7 + 0.2 * s);
    a.Rarm(-0.5, 0.55 - 0.25 * s, 0.1, 0.7 - 0.2 * s);
    a.spine(0.04, 0.12 * s, 0.08 * s); a.hipsY(Math.abs(s2) * 0.05);
    a.leg('l', 0.12 * s); a.leg('r', -0.12 * s); a.head(0, 0.1 * s, 0.1 * s);
  },
  sit(t, a) {
    a.hipsY(-0.42); a.spine(0.12, 0, 0);
    a.leg('l', 1.45); a.leg('r', 1.45); a.knee('l', 1.5); a.knee('r', 1.5);
    a.foot('l', 0.2); a.foot('r', 0.2);
    a.Larm(0.3, -0.75, 0.35, 0.5); a.Rarm(-0.3, -0.75, 0.35, 0.5);
  },
  hug(t, a) {
    const p = 0.9 + 0.05 * Math.sin(t * 2);
    a.Larm(0.15, 0.05, p, 1.2); a.Rarm(-0.15, 0.05, p, 1.2);
    a.spine(0.08, 0, 0); a.head(0.08, 0, 0);
  },
  cheer(t, a) {
    const b = 0.03 * Math.sin(t * 6);
    a.Larm(0.4, 0.92, 0.08, 0.15); a.Rarm(-0.4, 0.92, 0.08, 0.15);
    a.hipsY(Math.abs(Math.sin(t * 6)) * 0.04); a.head(-0.1, 0, 0);
  },
  cool(t, a) {              // static pose: hand on hip
    a.Larm(0.55, -0.55, 0.12, 1.5); a.Rarm(DOWN_R[0], DOWN_R[1], DOWN_R[2], 0.1);
    a.spine(0, 0.06, 0.04); a.head(0, 0.15, 0);
  },
  think(t, a) {             // static pose: hand near chin
    a.Larm(DOWN_L[0], DOWN_L[1], DOWN_L[2], 0.1);
    a.Rarm(-0.12, 0.35, 0.45, 2.1); a.head(0.12, -0.12, 0);
  },
  // paired-pose roles (tasteful): reach a hand toward a partner / high-five
  holdR(t, a) {   // right hand reaches out to the side to hold a partner's hand
    a.Larm(DOWN_L[0], DOWN_L[1], DOWN_L[2], 0.1);
    a.Rarm(-0.75, -0.35, 0.15, 0.2); a.head(0, -0.08, 0);
  },
  holdL(t, a) {   // left hand reaches out (mirror of holdR)
    a.Rarm(DOWN_R[0], DOWN_R[1], DOWN_R[2], 0.1);
    a.Larm(0.75, -0.35, 0.15, 0.2); a.head(0, 0.08, 0);
  },
  highfive(t, a) {
    a.Larm(DOWN_L[0], DOWN_L[1], DOWN_L[2], 0.1);
    a.Rarm(-0.25, 0.7, 0.45, 0.35); a.head(-0.05, 0, 0);
  },
};

// capture rest quaternions so emote eulers apply as deltas on the real rest pose
export function restMap(nodes) {
  const m = {};
  for (const k in nodes) { const n = nodes[k]; if (n) m[k] = { node: n, rest: n.quaternion.clone() }; }
  return m;
}
export function makeEmoteApi(map, poseL, poseR, hipsRestY) {
  const _e = new THREE.Euler(), _q = new THREE.Quaternion();
  function setE(key, rx, ry, rz) {
    const m = map[key]; if (!m) return;
    _q.setFromEuler(_e.set(rx || 0, ry || 0, rz || 0));
    m.node.quaternion.copy(m.rest).premultiply(_q);
  }
  return {
    Larm: (x, y, z, bend) => poseL && poseL(x, y, z, bend),
    Rarm: (x, y, z, bend) => poseR && poseR(x, y, z, bend),
    leg: (side, rx) => setE(side === 'l' ? 'lleg' : 'rleg', rx, 0, 0),
    knee: (side, rx) => setE(side === 'l' ? 'lknee' : 'rknee', rx, 0, 0),
    foot: (side, rx) => setE(side === 'l' ? 'lfoot' : 'rfoot', rx, 0, 0),
    spine: (rx, ry, rz) => setE('spine', rx, ry, rz),
    chest: (rx, ry, rz) => setE('chest', rx, ry, rz),
    head: (rx, ry, rz) => setE('head', rx, ry, rz),
    hipsY: (off) => { const h = map.hips; if (h) h.node.position.y = hipsRestY + off; },
    _reset() {   // clean base each frame: arms relaxed-down, other bones at rest
      for (const k of ['spine', 'chest', 'head', 'lleg', 'rleg', 'lknee', 'rknee', 'lfoot', 'rfoot']) {
        const m = map[k]; if (m) m.node.quaternion.copy(m.rest);
      }
      if (poseL) poseL(DOWN_L[0], DOWN_L[1], DOWN_L[2], 0.1);
      if (poseR) poseR(DOWN_R[0], DOWN_R[1], DOWN_R[2], 0.1);
    },
  };
}

// canonical humanoid bones we care about
const WANT = ['hips', 'spine', 'spine1', 'spine2', 'neck', 'head',
  'leftshoulder', 'rightshoulder', 'leftarm', 'rightarm', 'leftforearm', 'rightforearm',
  'lefthand', 'righthand', 'leftupleg', 'rightupleg', 'leftleg', 'rightleg', 'leftfoot', 'rightfoot'];

function mapBones(root) {
  const map = {};
  root.traverse(o => {
    if (o.isBone || o.type === 'Bone') {
      const n = norm(o.name);
      if (WANT.includes(n) && !map[n]) map[n] = o;
    }
  });
  return map;
}

// pick embedded idle/walk/run clips by fuzzy name
function pickEmbedded(animations) {
  if (!animations || !animations.length) return null;
  const find = (...keys) => animations.find(a => keys.some(k => a.name.toLowerCase().includes(k)));
  const idle = find('idle', 'breath', 'stand');
  const walk = find('walk');
  const run = find('run', 'jog', 'sprint');
  if (!idle && !walk) return null;
  return { idle: idle || walk, walk: walk || idle, run: run || walk || idle };
}

export function loadHumanoidGLB(url, opts = {}) {
  return new Promise((resolve, reject) => {
    if (/\.fbx(\?|$)/i.test(url)) { loadFBX(url, opts, resolve, reject); return; }
    loader.load(url, (gltf) => {
      try {
        // ---- VRM (VRoid / anime) avatar path --------------------------------
        const vrm = gltf.userData && gltf.userData.vrm;
        if (vrm) { resolve(buildVRM(vrm)); return; }

        const scene = gltf.scene || gltf.scenes[0];
        scene.traverse(o => {
          if (o.isMesh || o.isSkinnedMesh) {
            o.castShadow = true; o.receiveShadow = false; o.frustumCulled = false;
            if (o.material) { o.material.side = THREE.FrontSide; o.material.shadowSide = THREE.FrontSide; }
          }
        });
        // center feet at origin, face +Z toward viewer-neutral
        const box = new THREE.Box3().setFromObject(scene);
        scene.position.y -= box.min.y;                  // drop feet to y=0
        const root = new THREE.Group();
        root.add(scene);
        root.updateMatrixWorld(true);               // bone world matrices for rig analysis

        const bones = mapBones(scene);
        let forceProc = opts.procedural;
        try { if (localStorage.getItem('ds_force_proc') === '1') forceProc = true; } catch {}
        const embedded = forceProc ? null : pickEmbedded(gltf.animations);

        let api;
        if (embedded) api = mixerDriver(scene, embedded);
        else api = proceduralDriver(bones);

        resolve({
          root,
          update: api.update,
          setAnim: api.setAnim,
          setAppearance: () => {},    // RPM look is baked into the glb
          get outfit() { return 'rpm'; },
          dispose() {
            scene.traverse(o => {
              if (o.geometry) o.geometry.dispose();
              if (o.material) { const m = Array.isArray(o.material) ? o.material : [o.material]; m.forEach(x => { for (const k in x) { if (x[k] && x[k].isTexture) x[k].dispose(); } x.dispose && x.dispose(); }); }
            });
          },
        });
      } catch (e) { reject(e); }
    }, undefined, (err) => reject(err));
  });
}

// ---- FBX character (e.g. Ara 3D Gen) ---------------------------------------
function loadFBX(url, opts, resolve, reject) {
  fbxLoader.load(url, (obj) => {
    try {
      // FBX is often authored in cm — normalise to ~1.8 m tall, then drop feet to y=0
      obj.updateMatrixWorld(true);
      let box = new THREE.Box3().setFromObject(obj);
      const h = box.max.y - box.min.y;
      if (h > 0.001) obj.scale.multiplyScalar(1.8 / h);
      obj.updateMatrixWorld(true);
      box = new THREE.Box3().setFromObject(obj);
      obj.position.y -= box.min.y;
      obj.traverse(o => {
        if (o.isMesh || o.isSkinnedMesh) {
          o.castShadow = true; o.receiveShadow = false; o.frustumCulled = false;
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          mats.forEach(m => { if (m) { m.side = THREE.FrontSide; if (m.map) m.map.colorSpace = THREE.SRGBColorSpace; } });
        }
      });
      const root = new THREE.Group();
      root.add(obj);
      root.updateMatrixWorld(true);

      const bones = mapBones(obj);
      const anims = obj.animations || [];
      const embedded = opts.procedural ? null : pickEmbedded(anims);
      const api = embedded ? mixerDriver(obj, embedded) : proceduralDriver(bones);

      resolve({
        root,
        update: api.update,
        setAnim: api.setAnim,
        setEmote: api.setEmote || (() => {}),
        setAppearance: () => {},
        get outfit() { return 'fbx'; },
        _info: { animations: anims.map(a => a.name), bones: Object.keys(bones), driver: embedded ? 'embedded' : 'procedural' },
        dispose() {
          obj.traverse(o => {
            if (o.geometry) o.geometry.dispose();
            if (o.material) { const mm = Array.isArray(o.material) ? o.material : [o.material]; mm.forEach(m => { if (!m) return; for (const k in m) { if (m[k] && m[k].isTexture) m[k].dispose(); } m.dispose && m.dispose(); }); }
          });
        },
      });
    } catch (e) { reject(e); }
  }, undefined, (err) => reject(err));
}

// ---- VRM (VRoid / anime) avatar --------------------------------------------
function buildVRM(vrm) {
  try { VRMUtils.removeUnnecessaryVertices(vrm.scene); } catch {}
  try { VRMUtils.removeUnnecessaryJoints(vrm.scene); } catch {}
  try { VRMUtils.combineSkeletons && VRMUtils.combineSkeletons(vrm.scene); } catch {}

  vrm.scene.traverse(o => {
    if (o.isMesh || o.isSkinnedMesh) {
      o.castShadow = true; o.receiveShadow = false; o.frustumCulled = false;
    }
  });
  // VRM faces -Z by convention; rotate so "forward" is +Z like our other avatars
  try { VRMUtils.rotateVRM0(vrm); } catch {}
  const root = new THREE.Group();
  const facing = new THREE.Group();
  facing.rotation.y = Math.PI;            // turn to face +Z (tuned on a real VRM)
  facing.add(vrm.scene);
  root.add(facing);
  root.updateMatrixWorld(true);

  const driver = vrmDriver(vrm);
  return {
    root,
    update: (dt) => { driver.update(dt); if (vrm.update) vrm.update(dt); },
    setAnim: driver.setAnim,
    setAppearance: () => {},
    get outfit() { return 'vrm'; },
    dispose() { try { VRMUtils.deepDispose ? VRMUtils.deepDispose(vrm.scene) : vrm.scene.traverse(o => { o.geometry && o.geometry.dispose(); }); } catch {} },
  };
}

// VRM normalized humanoid is a canonical, world-aligned T-pose, so rotations are
// reliable without per-rig analysis. Original idle/walk/run cycle.
function vrmDriver(vrm) {
  const h = vrm.humanoid;
  const B = (n) => { try { return h.getNormalizedBoneNode(n); } catch { return null; } };
  const b = {
    hips: B('hips'), spine: B('spine'), chest: B('chest'), upperChest: B('upperChest'),
    neck: B('neck'), head: B('head'),
    larm: B('leftUpperArm'), rarm: B('rightUpperArm'), lfore: B('leftLowerArm'), rfore: B('rightLowerArm'),
    lleg: B('leftUpperLeg'), rleg: B('rightUpperLeg'), lknee: B('leftLowerLeg'), rknee: B('rightLowerLeg'),
    lfoot: B('leftFoot'), rfoot: B('rightFoot'),
  };
  const hipsRestY = b.hips ? b.hips.position.y : 0;
  function set(node, rx, ry, rz) { if (node) node.rotation.set(rx, ry, rz); }

  // rest quats + arm posers for emotes
  const uLRest = b.larm ? b.larm.quaternion.clone() : null;
  const uRRest = b.rarm ? b.rarm.quaternion.clone() : null;
  const lLRest = b.lfore ? b.lfore.quaternion.clone() : null;
  const lRRest = b.rfore ? b.rfore.quaternion.clone() : null;
  const poseL = (b.larm && b.lfore) ? makeArmPoser(b.larm, b.lfore, uLRest, lLRest) : null;
  const poseR = (b.rarm && b.rfore) ? makeArmPoser(b.rarm, b.rfore, uRRest, lRRest) : null;
  const emoteMap = restMap({
    spine: b.spine, chest: b.chest, head: b.head, hips: b.hips,
    lleg: b.lleg, rleg: b.rleg, lknee: b.lknee, rknee: b.rknee, lfoot: b.lfoot, rfoot: b.rfoot,
  });
  const emoteApi = makeEmoteApi(emoteMap, poseL, poseR, hipsRestY);

  let phase = 0, t = 0, w = 0, runW = 0, wT = 0, runT = 0, emote = null, emoteT = 0;
  const ARM_DOWN = 1.25;

  function update(dt) {
    t += dt;
    w += (wT - w) * Math.min(1, dt * 8);
    runW += (runT - runW) * Math.min(1, dt * 8);
    // Emote plays only when essentially standing still.
    if (emote && EMOTES[emote] && w < 0.2 && runW < 0.2) {
      emoteT += dt;
      if (b.hips) b.hips.position.y = hipsRestY;
      emoteApi._reset();
      EMOTES[emote](emoteT, emoteApi);
      return;
    }
    phase += dt * (7 + runW * 3.5) * (0.35 + w);
    const s = Math.sin(phase), s2 = Math.sin(phase + Math.PI);
    const legAmp = 0.42 * w + 0.32 * runW, armAmp = 0.35 * w + 0.33 * runW;
    const kneeAmp = 0.8 * w + 0.6 * runW, lean = 0.05 * w + 0.2 * runW;
    const breathe = 0.02 * Math.sin(t * 1.6) * (1 - 0.6 * w);

    set(b.spine, lean * 0.5 + breathe, 0, 0);
    set(b.chest, lean * 0.3, 0, 0);
    set(b.head, -lean * 0.5, 0.04 * Math.sin(t * 0.9) * (1 - w), 0);
    set(b.larm, s * armAmp, 0, -ARM_DOWN);
    set(b.rarm, s2 * armAmp, 0, ARM_DOWN);
    set(b.lfore, -0.2 - Math.max(0, s) * 0.3 * w, 0, 0);
    set(b.rfore, -0.2 - Math.max(0, s2) * 0.3 * w, 0, 0);
    set(b.lleg, s * legAmp, 0, 0);
    set(b.rleg, s2 * legAmp, 0, 0);
    set(b.lknee, Math.max(0, -s) * kneeAmp + 0.05, 0, 0);
    set(b.rknee, Math.max(0, -s2) * kneeAmp + 0.05, 0, 0);
    set(b.lfoot, 0.1 + s * 0.12 * w, 0, 0);
    set(b.rfoot, 0.1 + s2 * 0.12 * w, 0, 0);
    if (b.hips) b.hips.position.y = hipsRestY + Math.abs(Math.sin(phase)) * 0.03 * w;
  }
  function setAnim(name) {
    if (name === 'idle') { wT = 0; runT = 0; }
    else if (name === 'walk') { wT = 1; runT = 0; }
    else if (name === 'run') { wT = 1; runT = 1; }
  }
  function setEmote(name) { if (name !== emote) { emote = name || null; emoteT = 0; } }
  return { update, setAnim, setEmote };
}

// ---- driver A: play the glb's own clips via AnimationMixer + crossfade ------
function mixerDriver(scene, clips) {
  const mixer = new THREE.AnimationMixer(scene);
  const actions = {};
  for (const k of ['idle', 'walk', 'run']) {
    if (clips[k]) { actions[k] = mixer.clipAction(clips[k]); actions[k].enabled = true; actions[k].setEffectiveWeight(k === 'idle' ? 1 : 0); actions[k].play(); }
  }
  let current = 'idle';
  return {
    update: (dt) => mixer.update(dt),
    setAnim: (name) => {
      if (!actions[name] || name === current) return;
      const from = actions[current], to = actions[name];
      to.enabled = true; to.setEffectiveWeight(1); to.setEffectiveTimeScale(1);
      to.crossFadeFrom(from, 0.25, false); to.play();
      current = name;
    },
    setEmote: () => {},   // avatars that ship their own locomotion clips skip procedural emotes
  };
}

// ---- driver B: original procedural cycle on standard humanoid bones ---------
// Rotations are applied in PARENT space (premultiplied onto the rest pose), so
// they behave predictably on any T-pose humanoid rig without knowing each
// bone's local axis frame.
function proceduralDriver(bones) {
  const rest = {};
  for (const k in bones) rest[k] = bones[k].quaternion.clone();
  const hips = bones.hips;
  const hipsRestY = hips ? hips.position.y : 0;

  // Bake an "arms down at the sides" correction into the rest pose, computed
  // from the rig's actual geometry so it is correct on any humanoid (RPM T-pose
  // or A-pose). We rotate each upper-arm bone so it points down + slightly out.
  const _va = new THREE.Vector3(), _vc = new THREE.Vector3(), _cur = new THREE.Vector3();
  function armDown(armKey, childKey, outward) {
    const arm = bones[armKey], child = bones[childKey];
    if (!arm || !child) return;
    _va.setFromMatrixPosition(arm.matrixWorld);
    _vc.setFromMatrixPosition(child.matrixWorld);
    _cur.copy(_vc).sub(_va); if (_cur.lengthSq() < 1e-6) return; _cur.normalize();
    const target = new THREE.Vector3(outward * 0.28, -1, 0.05).normalize();
    const dW = new THREE.Quaternion().setFromUnitVectors(_cur, target);     // world rotation
    const pW = new THREE.Quaternion(); arm.parent.getWorldQuaternion(pW);
    const adjust = pW.clone().invert().multiply(dW).multiply(pW);           // → parent space
    rest[armKey].premultiply(adjust);                                       // adjust * rest
  }
  armDown('leftarm', 'leftforearm', +1);
  armDown('rightarm', 'rightforearm', -1);

  // emote posers (use raw bind rest, captured before any animation)
  const poseL = (bones.leftarm && bones.leftforearm)
    ? makeArmPoser(bones.leftarm, bones.leftforearm, bones.leftarm.quaternion.clone(), bones.leftforearm.quaternion.clone()) : null;
  const poseR = (bones.rightarm && bones.rightforearm)
    ? makeArmPoser(bones.rightarm, bones.rightforearm, bones.rightarm.quaternion.clone(), bones.rightforearm.quaternion.clone()) : null;
  const emoteMap = restMap({
    spine: bones.spine, chest: bones.spine2 || bones.chest, head: bones.head, hips: bones.hips,
    lleg: bones.leftupleg, rleg: bones.rightupleg, lknee: bones.leftleg, rknee: bones.rightleg,
    lfoot: bones.leftfoot, rfoot: bones.rightfoot,
  });
  const emoteApi = makeEmoteApi(emoteMap, poseL, poseR, hipsRestY);
  let emote = null, emoteT = 0;

  const _e = new THREE.Euler();
  const _dq = new THREE.Quaternion();
  function set(key, rx, ry, rz) {
    const b = bones[key]; if (!b) return;
    _dq.setFromEuler(_e.set(rx, ry, rz));
    b.quaternion.copy(rest[key]).premultiply(_dq); // delta * rest  (parent space)
  }

  let phase = 0, t = 0;
  let w = 0, runW = 0;          // walk / run blend weights
  let wT = 0, runT = 0;         // targets
  let current = 'idle';

  function update(dt) {
    t += dt;
    w += (wT - w) * Math.min(1, dt * 8);
    runW += (runT - runW) * Math.min(1, dt * 8);
    if (emote && EMOTES[emote] && w < 0.2 && runW < 0.2) {
      emoteT += dt;
      if (hips) hips.position.y = hipsRestY;
      emoteApi._reset();
      EMOTES[emote](emoteT, emoteApi);
      return;
    }
    const cadence = 7.0 + runW * 3.5;
    phase += dt * cadence * (0.35 + w);          // stride faster when walking/running
    const s = Math.sin(phase), s2 = Math.sin(phase + Math.PI);

    const legAmp = 0.42 * w + 0.32 * runW;
    const armAmp = 0.38 * w + 0.35 * runW;
    const kneeAmp = 0.7 * w + 0.6 * runW;
    const lean = 0.06 * w + 0.22 * runW;         // forward lean when moving

    // breathing / idle sway (always a little)
    const breathe = 0.02 * Math.sin(t * 1.6) * (1 - 0.6 * w);
    const sway = 0.03 * Math.sin(t * 0.9) * (1 - w);

    set('spine', lean * 0.4 + breathe, 0, 0);
    set('spine1', lean * 0.3, sway * 0.5, 0);
    set('spine2', lean * 0.3, 0, 0);
    set('head', -lean * 0.5, sway, 0);

    // legs: swing about parent X; knees bend on the lifted/back phase
    set('leftupleg', s * legAmp, 0, 0);
    set('rightupleg', s2 * legAmp, 0, 0);
    set('leftleg', Math.max(0, -s) * kneeAmp + 0.05, 0, 0);
    set('rightleg', Math.max(0, -s2) * kneeAmp + 0.05, 0, 0);
    set('leftfoot', 0.1 + s * 0.15 * w, 0, 0);
    set('rightfoot', 0.1 + s2 * 0.15 * w, 0, 0);

    // arms: rest is already "down at the sides"; add a counter-swing to the legs
    set('leftarm', s * armAmp + breathe * 0.5, 0, 0);
    set('rightarm', s2 * armAmp + breathe * 0.5, 0, 0);
    set('leftforearm', -0.3 - Math.max(0, s) * 0.4 * w, 0, 0);
    set('rightforearm', -0.3 - Math.max(0, s2) * 0.4 * w, 0, 0);

    if (hips) hips.position.y = hipsRestY + (Math.abs(Math.sin(phase)) * 0.04) * w;
  }

  function setAnim(name) {
    current = name;
    if (name === 'idle') { wT = 0; runT = 0; }
    else if (name === 'walk') { wT = 1; runT = 0; }
    else if (name === 'run') { wT = 1; runT = 1; }
  }
  function setEmote(name) { if (name !== emote) { emote = name || null; emoteT = 0; } }

  return { update, setAnim, setEmote };
}
