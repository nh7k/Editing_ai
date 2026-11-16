// characterValidator.js — data-driven validation for a loaded humanoid avatar.
// Works on any THREE.Object3D root (procedural, GLB, VRM or FBX). Reports
// skeleton, required humanoid bones, skinning weights, materials/textures,
// black-patch risk, animations and dimensions. Nothing is hardcoded to one
// model; bone names are matched by a normalized map so different rigs pass.
import * as THREE from 'three';

const norm = (n) => String(n).toLowerCase().replace(/mixamorig/g, '').replace(/[:_\s.|-]/g, '');

// canonical humanoid bones -> accepted normalized aliases
const REQUIRED = {
  hips: ['hips', 'pelvis', 'root'],
  spine: ['spine', 'spine1', 'chest'],
  head: ['head'],
  leftUpperArm: ['leftarm', 'leftupperarm', 'upperarml', 'lshoulder'],
  rightUpperArm: ['rightarm', 'rightupperarm', 'upperarmr', 'rshoulder'],
  leftLowerArm: ['leftforearm', 'leftlowerarm', 'lowerarml'],
  rightLowerArm: ['rightforearm', 'rightlowerarm', 'lowerarmr'],
  leftUpperLeg: ['leftupleg', 'leftupperleg', 'uplegl', 'lefthip'],
  rightUpperLeg: ['rightupleg', 'rightupperleg', 'uplegr', 'righthip'],
  leftLowerLeg: ['leftleg', 'leftlowerleg', 'lolegl', 'leftknee'],
  rightLowerLeg: ['rightleg', 'rightlowerleg', 'lolegr', 'rightknee'],
  leftFoot: ['leftfoot', 'footl'],
  rightFoot: ['rightfoot', 'footr'],
};

export function validateCharacter(root, animations = []) {
  const checks = [];
  const add = (name, pass, detail) => checks.push({ name, pass: !!pass, detail: detail || '' });

  // ---- skeleton / skinned meshes ----
  const bones = new Map();          // normalized name -> bone
  let skinned = 0, skinnedWithWeights = 0, meshes = 0;
  root.traverse(o => {
    if (o.isBone || o.type === 'Bone') { const n = norm(o.name); if (!bones.has(n)) bones.set(n, o); }
    if (o.isMesh || o.isSkinnedMesh) {
      meshes++;
      if (o.isSkinnedMesh) {
        skinned++;
        const g = o.geometry;
        if (g && g.attributes.skinIndex && g.attributes.skinWeight) skinnedWithWeights++;
      }
    }
  });
  add('has-mesh', meshes > 0, `${meshes} mesh(es)`);
  add('has-skeleton', bones.size > 0, `${bones.size} bones`);
  add('skinned-mesh', skinned > 0, `${skinned} skinned mesh(es)`);
  add('skinning-weights', skinned === 0 ? false : skinnedWithWeights === skinned,
    `${skinnedWithWeights}/${skinned} skinned meshes have skinIndex+skinWeight`);

  // ---- required humanoid bones ----
  const matched = {}, missing = [];
  for (const [canon, aliases] of Object.entries(REQUIRED)) {
    let hit = null;
    for (const n of bones.keys()) if (aliases.some(a => n === a || n.includes(a))) { hit = n; break; }
    if (hit) matched[canon] = hit; else missing.push(canon);
  }
  add('humanoid-bones', missing.length === 0, missing.length ? `missing: ${missing.join(', ')}` : `all ${Object.keys(REQUIRED).length} found`);
  add('root-and-hips', !!matched.hips, matched.hips ? `hips bone: ${matched.hips}` : 'no hips/pelvis/root bone');

  // ---- materials / textures / black-patch risk ----
  const mats = new Set(); let withMap = 0, noMap = 0, blackRisk = 0; const riskNames = [];
  root.traverse(o => {
    if (!o.material) return;
    const list = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of list) {
      if (!m || mats.has(m)) continue; mats.add(m);
      if (m.map) withMap++; else if ('map' in m) noMap++;   // map assigned (decode is async)
      // transparent card with an alpha source but no alphaTest -> can render black
      if (m.transparent && (m.alphaMap || (m.map && m.map.image)) && !(m.alphaTest > 0)) { blackRisk++; riskNames.push(m.name || '(unnamed)'); }
    }
  });
  add('materials', mats.size > 0, `${mats.size} material(s); ${withMap} with loaded texture, ${noMap} with no diffuse map`);
  add('no-black-patch-risk', blackRisk === 0, blackRisk ? `${blackRisk} transparent material(s) w/o alphaTest: ${riskNames.join(', ')}` : 'alpha handling OK');

  // ---- animations ----
  const anims = (animations && animations.length) ? animations : (root.animations || []);
  const names = anims.map(a => a.name);
  const hasLoco = ['idle', 'walk', 'run'].filter(k => names.some(n => n.toLowerCase().includes(k)));
  add('animations', anims.length > 0, anims.length ? `${anims.length}: ${names.join(', ')}` : 'no clips (procedural driver will animate instead)');
  add('locomotion-clips', hasLoco.length > 0, hasLoco.length ? `found ${hasLoco.join('/')}` : 'none named idle/walk/run');

  // ---- dimensions ----
  const box = new THREE.Box3().setFromObject(root);
  const h = box.max.y - box.min.y;
  add('height-plausible', h > 0.5 && h < 400, `${h.toFixed(2)} units (scaled to ~1.8 m at load if an FBX)`);

  const errors = checks.filter(c => !c.pass && ['has-mesh', 'has-skeleton', 'skinning-weights', 'root-and-hips'].includes(c.name));
  const ok = errors.length === 0;
  return {
    ok,
    ready: ok && checks.find(c => c.name === 'no-black-patch-risk').pass,
    checks,
    bones: matched,
    missingBones: missing,
    heightUnits: +h.toFixed(3),
    animationNames: names,
    materialCount: mats.size,
  };
}
