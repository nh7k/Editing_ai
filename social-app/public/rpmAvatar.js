// rpmAvatar.js — load a rigged humanoid .glb (Ready Player Me or any glb) and
// animate it. If the glb ships its own idle/walk/run clips, we play them through
// an AnimationMixer with cross-fades. If it ships none (RPM avatars don't), we
// drive the standard humanoid bones with an original procedural idle/walk/run
// cycle. Bone lookup is normalized so it works on RPM names ("Hips", "LeftArm")
// and Mixamo names ("mixamorigHips") alike.
import * as THREE from 'three';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from './vendor/three-vrm.module.js';

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));   // enable .vrm (VRoid/anime) avatars

function norm(n) { return String(n).toLowerCase().replace(/mixamorig/g, '').replace(/[:_\s.]/g, ''); }

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

  let phase = 0, t = 0, w = 0, runW = 0, wT = 0, runT = 0;
  const ARM_DOWN = 1.25;

  function update(dt) {
    t += dt;
    w += (wT - w) * Math.min(1, dt * 8);
    runW += (runT - runW) * Math.min(1, dt * 8);
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
  return { update, setAnim };
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

  return { update, setAnim };
}
