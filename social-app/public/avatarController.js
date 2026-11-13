// avatarController.js — one avatar handle that is either the original procedural
// humanoid or a loaded Ready Player Me .glb, with the procedural one as an
// always-available fallback so the app never breaks (offline, bad URL, load error).
import * as THREE from 'three';
import { createAvatar } from './avatar.js';
import { loadHumanoidGLB } from './rpmAvatar.js';

export function createAvatarController(look = {}) {
  const root = new THREE.Group();
  let impl = createAvatar(look);          // procedural first — shows instantly
  root.add(impl.root);
  let mode = 'procedural';
  let currentAnim = 'idle';
  let currentEmote = null;
  let loadToken = 0;                       // guards against stale async loads
  let destroyed = false;
  let lastUrl = look.avatarUrl || '';

  function swap(newImpl) {
    root.remove(impl.root);
    if (impl.dispose) try { impl.dispose(); } catch {}
    impl = newImpl;
    root.add(impl.root);
    impl.setAnim(currentAnim);
    if (currentEmote && impl.setEmote) impl.setEmote(currentEmote);
  }

  async function applyUrl(url) {
    url = url || '';
    if (url === lastUrl && mode !== 'procedural' === !!url) { /* no-op */ }
    lastUrl = url;
    const token = ++loadToken;
    if (!url) {
      if (mode !== 'procedural') { swap(createAvatar(look)); mode = 'procedural'; }
      return;
    }
    try {
      const rpm = await loadHumanoidGLB(url);
      if (destroyed || token !== loadToken) { if (rpm.dispose) rpm.dispose(); return; }
      swap(rpm); mode = 'rpm';
    } catch (e) {
      console.warn('[Driftspace] RPM avatar load failed, using procedural fallback:', e && e.message || e);
      if (mode !== 'procedural') { swap(createAvatar(look)); mode = 'procedural'; }
    }
  }

  if (lastUrl) applyUrl(lastUrl);

  return {
    root,
    update: (dt) => impl.update(dt),
    setAnim: (n) => { currentAnim = n; impl.setAnim(n); },
    setEmote: (n) => { currentEmote = n || null; if (impl.setEmote) impl.setEmote(currentEmote); },
    setAppearance: (next) => {
      Object.assign(look, next);
      if ('avatarUrl' in next && (next.avatarUrl || '') !== lastUrl) applyUrl(next.avatarUrl);
      if (mode === 'procedural') impl.setAppearance(next);
    },
    get mode() { return mode; },
    get outfit() { return mode === 'rpm' ? 'rpm' : impl.outfit; },
    dispose() { destroyed = true; if (impl.dispose) try { impl.dispose(); } catch {} },
  };
}
