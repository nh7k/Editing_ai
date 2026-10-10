import type {
  Job,
  JobEvent,
  JobThought,
  RenderStep,
  LiveColorItem,
  LiveFxItem,
  LiveMusicItem,
  LiveTextItem,
  LiveTimeline,
  LiveTrack,
  LiveVideoItem,
} from '../api/types';

/** Tracks drawn as rows in the live view (colour is shown as a chip). */
export const LIVE_ROWS = ['video', 'text', 'fx', 'music'] as const;
export type LiveRow = (typeof LIVE_ROWS)[number];
export const LIVE_TRACKS: readonly LiveTrack[] = ['video', 'text', 'fx', 'music', 'color'];

export const ROW_LABELS: Record<LiveRow, string> = { video: 'Video', text: 'Text', fx: 'FX', music: 'Music' };

export interface LiveThoughtEntry {
  key: string;
  t: number;
  agent: string;
  text: string;
}

export interface LiveState {
  thoughts: LiveThoughtEntry[];
  tracks: LiveTimeline;
  /** Highest event sequence number applied (-1 = none). */
  lastSeq: number;
  /** Track of the newest `timeline` event (where the "build cursor" goes); unknown for snapshot-only state. */
  lastTrack?: LiveTrack;
  /**
   * Latest render step of the CURRENT render: set by `render_step`, cleared by a newer `timeline` event (a re-cut
   * makes the old render stale) or a `progress` event whose stage is not a render stage (e.g. "reviewing").
   */
  renderStep?: RenderStep | null;
  /** Newest job stage seen in `progress` events (fresher than a polled `job.stage`). */
  stage?: string;
  /** True once any event shows the worker picked the job up (it is no longer waiting in the queue). */
  started?: boolean;
}

/** Event types that prove the job left the queue. */
const START_EVENTS = new Set(['job_started', 'job_resumed', 'node_started', 'agent_started', 'progress', 'thought', 'timeline', 'render_step']);

/** True for a job stage written while the video is rendered ("rendering segment 4/9", "joining segments", …). */
export function isRenderStage(stage: string | null | undefined): boolean {
  return typeof stage === 'string' && /render|joining segments|adding text|reusing the cut|exporting /i.test(stage);
}

/**
 * A render step from a `render_step` event / `job.render_step` (its `step` wins) or, failing that, from the
 * renderer's message (the job stage while rendering: "retry 1: rendering segment 4/9"). Null when not a render step.
 */
export function parseRenderStep(raw: unknown): RenderStep | null {
  const obj = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null;
  const text = String((obj ? obj.text : raw) ?? '').trim();
  const msg = text.replace(/^retry \d+:\s*/i, '');
  const intOrNull = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.round(v)) : null);
  let done = obj ? intOrNull(obj.done) : null;
  let total = obj ? intOrNull(obj.total) : null;
  const seg = /rendering segment (\d+)\s*\/\s*(\d+)/i.exec(msg);
  const many = /rendering (\d+) segments/i.exec(msg);
  if (seg) {
    done = done ?? Number(seg[1]);
    total = total ?? Number(seg[2]);
  } else if (many) {
    total = total ?? Number(many[1]);
  }
  const fromText = seg
    ? 'segment'
    : many
      ? 'segment'
      : /^joining/i.test(msg)
        ? 'join'
        : /^(adding|exporting)/i.test(msg)
          ? 'finish'
          : /^reusing/i.test(msg)
            ? 'reuse'
            : /^render complete/i.test(msg)
              ? 'done'
              : /render/i.test(msg)
                ? 'start'
                : null;
  const given = obj && typeof obj.step === 'string' && obj.step && obj.step !== 'start' ? obj.step : null;
  const step = given ?? fromText ?? (obj && obj.step === 'start' ? 'start' : null);
  if (!step) return null;
  if (step === 'segment' && done === null) done = 0;
  const out: RenderStep = { step, done, total, text };
  if (obj && typeof obj.round === 'number') out.round = obj.round;
  return out;
}

/** What the live view is showing: waiting in the queue, agents deciding, rendering, or reviewing the result. */
export type LivePhase = 'queued' | 'working' | 'rendering' | 'reviewing';

/**
 * The phase from the job status and the freshest stage (events first, else the polled job). A known stage
 * decides; without one, a pending render step means rendering.
 */
export function livePhase(
  job: Partial<Pick<Job, 'status' | 'stage'>> | null | undefined,
  state: Pick<LiveState, 'stage' | 'renderStep' | 'started'>,
): LivePhase {
  const stage = state.stage ?? job?.stage ?? '';
  if (job?.status === 'queued' && !state.started && (!stage || stage === 'queued')) return 'queued';
  if (/^review/i.test(stage)) return 'reviewing';
  if (isRenderStage(stage)) return 'rendering';
  if (stage && stage !== 'queued') return 'working';
  return state.renderStep ? 'rendering' : 'working';
}

export const EMPTY_LIVE: LiveState = { thoughts: [], tracks: {}, lastSeq: -1 };

function num(v: unknown, fallback = 0): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function isLiveTrack(v: unknown): v is LiveTrack {
  return typeof v === 'string' && (LIVE_TRACKS as readonly string[]).includes(v);
}

/** Read a field from the event itself or from a nested `data` object (both shapes are tolerated). */
function field(ev: JobEvent, key: string): unknown {
  if (ev[key] !== undefined) return ev[key];
  const data = ev.data;
  return data && typeof data === 'object' ? (data as Record<string, unknown>)[key] : undefined;
}

/** Clean up one track's items: drop junk, make times numbers. */
export function normalizeItems(track: LiveTrack, raw: unknown): LiveTimeline[LiveTrack] {
  const list = Array.isArray(raw) ? raw.filter((x): x is Record<string, unknown> => !!x && typeof x === 'object') : [];
  if (track === 'color') {
    return list.map((x) => ({
      preset: typeof x.preset === 'string' ? x.preset : null,
      lut: typeof x.lut === 'string' ? x.lut : null,
    })) as LiveColorItem[];
  }
  const timed: (Record<string, unknown> & { start: number; dur: number })[] = list.map((x) => ({ ...x, start: Math.max(0, num(x.start)), dur: Math.max(0, num(x.dur)) }));
  switch (track) {
    case 'video':
      return timed.map((x) => ({
        ...x,
        clip_id: String(x.clip_id ?? ''),
        filename: String(x.filename ?? ''),
        thumb: typeof x.thumb === 'string' ? x.thumb : null,
      })) as LiveVideoItem[];
    case 'text':
      return timed.map((x) => ({ ...x, text: String(x.text ?? ''), kind: String(x.kind ?? 'caption') })) as LiveTextItem[];
    case 'fx':
      return timed.map((x) => ({ ...x, type: String(x.type ?? 'fx') })) as LiveFxItem[];
    case 'music':
      return timed.map((x) => ({ ...x, name: String(x.name ?? '') })) as LiveMusicItem[];
  }
}

/**
 * Reducer: apply one live event. `thought` appends to the feed, `timeline` REPLACES that track
 * (a retry re-cuts the video). Other events and repeats (seq already applied) leave the state unchanged.
 */
export function applyLiveEvent(prev: LiveState, ev: JobEvent): LiveState {
  if (ev.seq <= prev.lastSeq) return prev;
  const state: LiveState = START_EVENTS.has(ev.type) && !prev.started ? { ...prev, started: true } : prev;
  if (ev.type === 'render_step') {
    const step = parseRenderStep({
      step: field(ev, 'step'),
      done: field(ev, 'done'),
      total: field(ev, 'total'),
      text: field(ev, 'text'),
      round: field(ev, 'round'),
    });
    return { ...state, lastSeq: ev.seq, renderStep: step ?? state.renderStep ?? null };
  }
  if (ev.type === 'progress') {
    const stage = field(ev, 'stage');
    if (typeof stage !== 'string' || !stage) return { ...state, lastSeq: ev.seq };
    // a render stage carries the step too ("rendering segment 4/9"); any other stage ends the render
    const fromStage = isRenderStage(stage) ? parseRenderStep(stage) : null;
    const renderStep = isRenderStage(stage) ? (fromStage && fromStage.step !== 'start' ? fromStage : (state.renderStep ?? fromStage)) : null;
    return { ...state, lastSeq: ev.seq, stage, renderStep };
  }
  if (ev.type === 'thought') {
    const text = field(ev, 'text');
    if (typeof text !== 'string' || !text.trim()) return { ...state, lastSeq: ev.seq };
    const agent = field(ev, 'agent');
    return {
      ...state,
      lastSeq: ev.seq,
      thoughts: [...state.thoughts, { key: `e${ev.seq}`, t: num(ev.t), agent: typeof agent === 'string' && agent ? agent : 'Agent', text }],
    };
  }
  if (ev.type === 'timeline') {
    const track = field(ev, 'track');
    if (!isLiveTrack(track)) return { ...state, lastSeq: ev.seq };
    return {
      ...state,
      lastSeq: ev.seq,
      lastTrack: track,
      tracks: { ...state.tracks, [track]: normalizeItems(track, field(ev, 'items')) },
      // the agents changed the edit again (a retry): the previous render no longer applies
      ...(state.renderStep ? { renderStep: null } : {}),
    };
  }
  return { ...state, lastSeq: ev.seq };
}

/** Thoughts from the job snapshot (`job.thoughts`), as feed entries. */
export function snapshotThoughts(thoughts: JobThought[] | undefined): LiveThoughtEntry[] {
  return (thoughts ?? [])
    .filter((x) => x && typeof x.text === 'string' && x.text.trim())
    .map((x, i) => ({ key: `s${i}`, t: num(x.t), agent: x.agent || 'Agent', text: x.text }));
}

/**
 * The live view's state from what the screen has: the polled job snapshot (`timeline`, `thoughts`) and the
 * events (SSE-streamed and/or from the snapshot, sorted by seq). Events are the newest knowledge, so a track
 * an event filled wins over the snapshot's copy; the snapshot fills the rest (polling-only clients).
 * The feed comes from whichever source knows more thoughts (the snapshot keeps the last 200).
 */
export function buildLiveState(
  job: (Pick<Job, 'timeline' | 'thoughts'> & Partial<Pick<Job, 'render_step' | 'stage' | 'status'>>) | null | undefined,
  events: JobEvent[],
): LiveState {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  const fromEvents = sorted.reduce(applyLiveEvent, EMPTY_LIVE);
  const tracks: LiveTimeline = {};
  const snap = job?.timeline ?? {};
  for (const t of LIVE_TRACKS) {
    if (fromEvents.tracks[t] !== undefined) (tracks as Record<string, unknown>)[t] = fromEvents.tracks[t];
    else if (snap[t] !== undefined) (tracks as Record<string, unknown>)[t] = normalizeItems(t, snap[t]);
  }
  const snapThoughts = snapshotThoughts(job?.thoughts);
  const thoughts = fromEvents.thoughts.length >= snapThoughts.length ? fromEvents.thoughts : snapThoughts;
  const out: LiveState = { thoughts, tracks, lastSeq: fromEvents.lastSeq, ...(fromEvents.lastTrack ? { lastTrack: fromEvents.lastTrack } : {}) };
  // polling fallback: the job's stage / render step when the events do not say (the stage is the freshest
  // render message; `job.render_step` is only trusted while the stage is a render stage — it outlives a retry)
  const stage = fromEvents.stage ?? (typeof job?.stage === 'string' && job.stage ? job.stage : undefined);
  if (stage) out.stage = stage;
  let renderStep = fromEvents.renderStep ?? null;
  if (!renderStep && !fromEvents.stage && isRenderStage(stage)) {
    const fromStage = parseRenderStep(stage);
    const snap = parseRenderStep(job?.render_step ?? null);
    renderStep = fromStage && fromStage.step !== 'start' ? fromStage : (snap ?? fromStage);
  }
  if (renderStep) out.renderStep = renderStep;
  if (fromEvents.started || (job?.status && job.status !== 'queued')) out.started = true;
  return out;
}

/** True when there is anything to show (a thought or any track). */
export function hasLiveContent(state: LiveState): boolean {
  return state.thoughts.length > 0 || LIVE_TRACKS.some((t) => (state.tracks[t]?.length ?? 0) > 0);
}

function trackEnd(items: { start: number; dur: number }[] | undefined): number {
  return (items ?? []).reduce((m, x) => Math.max(m, x.start + x.dur), 0);
}

/**
 * Length of the output timeline: the end of the video track (the cut decides the length); before the video
 * exists, the end of text / fx / music. Never below 1 s.
 */
export function liveTotal(tracks: LiveTimeline): number {
  const video = trackEnd(tracks.video);
  if (video > 0) return video;
  return Math.max(1, trackEnd(tracks.text), trackEnd(tracks.fx), trackEnd(tracks.music));
}

/**
 * Where the live "build cursor" stops: the end of the newest block of the track the agents filled last;
 * when that is unknown (snapshot only) or has no times (colour), the end of the whole live timeline.
 */
export function liveBuildEnd(state: Pick<LiveState, 'tracks' | 'lastTrack'>): number {
  const t = state.lastTrack;
  if (t && t !== 'color') {
    const end = trackEnd(state.tracks[t]);
    if (end > 0) return end;
  }
  return LIVE_ROWS.some((r) => (state.tracks[r]?.length ?? 0) > 0) ? liveTotal(state.tracks) : 0;
}

/** Pixels per second so the whole timeline fits `width`, but never below `minPps` (then it scrolls). */
export function pxPerSecond(total: number, width: number, minPps = 8): number {
  if (!(total > 0) || !(width > 0)) return minPps;
  return Math.max(minPps, width / total);
}

/** Left / width of a block, width proportional to `dur`; blocks past `total` are clipped. */
export function blockGeometry(
  start: number,
  dur: number,
  pps: number,
  total = Infinity,
  minWidth = 3,
): { left: number; width: number } {
  const s = Math.max(0, Math.min(start, total));
  const e = Math.max(s, Math.min(start + Math.max(0, dur), total));
  return { left: Math.round(s * pps), width: Math.max(minWidth, Math.round((e - s) * pps)) };
}

/**
 * Stable key of a block: changes when the block's content changes, so a replaced track's new blocks
 * mount fresh and animate in, while unchanged blocks stay put.
 */
export function blockKey(track: LiveTrack, item: { start: number; dur: number } & Record<string, unknown>, i: number): string {
  const what = item.clip_id ?? item.text ?? item.type ?? item.name ?? '';
  return `${track}-${i}-${item.start.toFixed(2)}-${item.dur.toFixed(2)}-${String(what)}`;
}

/** The agent working right now: a running agent of the job, else the author of the latest thought. */
export function workingAgent(job: Pick<Job, 'status' | 'agents'> | null | undefined, thoughts: LiveThoughtEntry[]): string | null {
  if (!job || (job.status !== 'running' && job.status !== 'queued')) return null;
  const running = job.agents?.find((a) => a.status === 'running' || a.status === 'retrying');
  if (running) return running.name;
  return thoughts.length ? thoughts[thoughts.length - 1].agent : job.status === 'queued' ? null : 'Director';
}

/** Chip text for the colour track ("warm", "LUT teal_orange"). */
export function colorLabel(items: LiveColorItem[] | undefined): string | null {
  const c = items?.[0];
  if (!c) return null;
  if (c.preset && c.lut) return `${c.preset} · ${c.lut}`;
  return c.preset ?? (c.lut ? `LUT ${c.lut}` : null);
}

/** "0:04" style seconds label for ruler / tooltips. */
export function secondsLabel(s: number): string {
  const v = Math.max(0, Math.round(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
}

// ---- What the agent is doing right now (timeline header ticker) ----

/** Glyph of an agent for the ticker: ✂ cutter, 🎨 color, ✨ effects, ♪ audio, 🎬 render, 👀 review, 🧠 the rest. */
export function agentGlyph(agent: string | null | undefined): string {
  const a = (agent ?? '').toLowerCase();
  if (a.includes('cut')) return '✂';
  if (a.includes('colo')) return '🎨';
  if (a.includes('effect') || a === 'fx') return '✨';
  if (a.includes('audio') || a.includes('music')) return '♪';
  if (a.includes('render')) return '🎬';
  if (a.includes('review')) return '👀';
  return '🧠';
}

/** One short line of a thought: the decision without its reason ("— because …"), at most `max` characters. */
export function shortThought(text: string, max = 64): string {
  let s = text.replace(/\s+/g, ' ').trim();
  s = s.split(/\s+[—–]\s+|\s+-\s+|;\s+/)[0].trim();
  s = s.replace(/[.…]+$/, '').trim();
  if (s.length > max) s = `${s.slice(0, max - 1).trimEnd()}…`;
  return s;
}

/** The ticker's words for a render step (Hinglish, like the rest of the live view). */
export function renderStepLabel(step: RenderStep | null | undefined): string {
  if (!step) return '🎬 Video render ho raha hai';
  switch (step.step) {
    case 'segment':
      if (step.total && step.done) return `🎬 Shot ${Math.min(step.done, step.total)}/${step.total} ban gaya`;
      return step.total ? `🎬 ${step.total} shots render ho rahe hain` : '🎬 Shots render ho rahe hain';
    case 'join':
      return '🎬 Shots jod raha hai';
    case 'finish':
      return '🎬 Text + gaana + final encode';
    case 'reuse':
      return '🎬 Cut wahi hai, sirf text/gaana';
    case 'done':
      return '🎬 Render ho gaya';
    default:
      return '🎬 Render shuru…';
  }
}

/** Queue line of the header ("Line me hai — 2 edit aage"). */
export function queueLabel(position: number | null | undefined): string {
  const n = typeof position === 'number' && position > 0 ? Math.round(position) : 0;
  return n > 0 ? `Line me hai — ${n} edit aage` : 'Line me hai — agla number aapka';
}

/** One line: what the agent is doing right now, from the phase, the render step and the latest thought. */
export function tickerText(
  phase: LivePhase,
  state: Pick<LiveState, 'thoughts' | 'renderStep'>,
): string {
  if (phase === 'queued') return '⏳ Pichla edit khatam hone ka intezaar';
  if (phase === 'reviewing') return '👀 Result dekh raha hai';
  if (phase === 'rendering') return renderStepLabel(state.renderStep);
  const last = state.thoughts[state.thoughts.length - 1];
  if (!last) return '🧠 Prompt samajh raha hai';
  const line = shortThought(last.text);
  return line ? `${agentGlyph(last.agent)} ${line}` : '🧠 Soch raha hai';
}

/** Render progress drawn on the Main track: how many shots show ✓, the join / finish shimmer, the "reuse" note. */
export interface RenderProgress {
  /** The first `doneCount` shots are marked finished (segments render in parallel: a count, not indexes). */
  doneCount: number;
  /** Thin progress shimmer across the whole timeline (joining the shots / final pass). */
  shimmer: boolean;
  /** The cut was reused: every shot ✓ at once, only text / audio are redone. */
  reuse: boolean;
}

export function renderProgress(phase: LivePhase, step: RenderStep | null | undefined, shots: number): RenderProgress {
  const none: RenderProgress = { doneCount: 0, shimmer: false, reuse: false };
  if (shots <= 0) return none;
  if (phase === 'reviewing') return { doneCount: shots, shimmer: false, reuse: false };
  if (phase !== 'rendering' || !step) return none;
  switch (step.step) {
    case 'segment': {
      const done = step.done ?? 0;
      const total = step.total && step.total > 0 ? step.total : shots;
      // the renderer may count shots differently from the live track (e.g. a re-cut): scale to our blocks
      const count = total === shots ? done : Math.round((done / total) * shots);
      return { doneCount: Math.max(0, Math.min(shots, count)), shimmer: false, reuse: false };
    }
    case 'join':
    case 'finish':
      return { doneCount: shots, shimmer: true, reuse: false };
    case 'reuse':
      return { doneCount: shots, shimmer: true, reuse: true };
    case 'done':
      return { doneCount: shots, shimmer: false, reuse: false };
    default:
      return none;
  }
}
