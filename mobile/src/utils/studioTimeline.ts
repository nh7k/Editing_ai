// Pure layout math for the desktop studio timeline (no React / Skia here, so it is unit-testable).
import type { Clip, EditPlan, Job, LiveTimeline, PlanOverlay } from '../api/types';
import {
  blockKey,
  colorLabel,
  liveBuildEnd,
  livePhase,
  liveTotal,
  renderProgress,
  tickerText,
  type LivePhase,
  type LiveState,
  type RenderProgress,
} from './liveTimeline';

/** One piece of the "Main" video track, in output time. */
export interface StudioSegment {
  key: string;
  clipId: string;
  label: string;
  /** Source in / out points (seconds in the clip). */
  in: number;
  out: number;
  speed: number;
  /** Output start / end (seconds). */
  start: number;
  end: number;
  /** Duration of the source clip (0 when unknown). */
  clipDuration: number;
  /** Live mode: server path of one frame of the shot (shown instead of the filmstrip). */
  thumb?: string | null;
}

export interface StudioTextItem {
  key: string;
  kind: string;
  label: string;
  start: number;
  end: number;
}

export interface StudioOverlayTrack {
  key: string;
  label: string;
  colors: string[];
  start: number;
  end: number;
  overlay: PlanOverlay;
}

/** A timed block of the live FX / Music rows. */
export interface StudioLiveItem {
  key: string;
  label: string;
  start: number;
  end: number;
}

/** Extra info of a timeline that is being built live by the agents (job running). */
export interface StudioLiveInfo {
  /** FX blocks split into non-overlapping lanes (drawn as "FX 1", "FX 2"). */
  fxLanes: StudioLiveItem[][];
  music: StudioLiveItem[];
  /** Colour chip text ("warm", "LUT teal_orange") or null. */
  color: string | null;
  /** Where the glowing build cursor sweeps to (seconds). */
  buildEnd: number;
  /** Changes whenever any live track changes (restarts the build animation). */
  revision: string;
  /** Blocks in the track the agents filled last (how long the cursor sweep takes). */
  buildCount: number;
  /** Queued / working / rendering / reviewing (defaults to working when the job is unknown). */
  phase: LivePhase;
  /** One line: what the agent is doing right now. */
  ticker: string;
  /** Edits ahead of this one while queued. */
  queuePosition: number | null;
  /** The project's raw clips end-to-end (shown dimmed on Main until the cut lands, and as the cut's source). */
  raw: RawClip[];
  /** Total length of the raw footage (seconds). */
  rawTotal: number;
  /** Source range of each live shot on the raw strip (only shots whose clip is known). */
  kept: KeptRange[];
  /** Parts of the raw clips the agent cut away. */
  gaps: RawRange[];
  /** Raw-strip times where the agent cut (✂ marks). */
  cutPoints: number[];
  /** Changes only when the video track changes (replays the cut animation). */
  videoSig: string;
  /** Render state drawn on the Main track. */
  render: RenderProgress;
}

/** One raw clip laid out on the raw-footage strip. */
export interface RawClip {
  clipId: string;
  label: string;
  /** Position on the raw strip (seconds). */
  start: number;
  end: number;
}

export interface RawRange {
  start: number;
  end: number;
}

/** A live shot's source range: where it sits on the raw strip and where it lands in the edit. */
export interface KeptRange {
  /** Index of the shot in the live video track (= its Main segment). */
  index: number;
  clipId: string;
  rawStart: number;
  rawEnd: number;
  outStart: number;
  outEnd: number;
}

/** Raw clips laid end-to-end (clips without a duration are left out). */
export function rawLayout(clips: Clip[]): RawClip[] {
  let t = 0;
  return clips
    .filter((c) => c.duration > 0)
    .map((c) => {
      const r = { clipId: c.id, label: c.filename, start: t, end: t + c.duration };
      t += c.duration;
      return r;
    });
}

/** Where each shot's in..out sits on the raw strip (clamped to its clip); shots of unknown clips are skipped. */
export function keptRanges(
  raw: RawClip[],
  shots: Pick<StudioSegment, 'clipId' | 'in' | 'out' | 'start' | 'end'>[],
): KeptRange[] {
  const byId = new Map(raw.map((r) => [r.clipId, r]));
  const out: KeptRange[] = [];
  shots.forEach((s, index) => {
    const r = byId.get(s.clipId);
    if (!r) return;
    const len = r.end - r.start;
    const a = Math.max(0, Math.min(len, s.in));
    const b = Math.max(a, Math.min(len, s.out));
    if (b - a <= 1e-6) return;
    out.push({ index, clipId: s.clipId, rawStart: r.start + a, rawEnd: r.start + b, outStart: s.start, outEnd: s.end });
  });
  return out;
}

function mergeRanges(ranges: RawRange[]): RawRange[] {
  const sorted = [...ranges].sort((x, y) => x.start - y.start);
  const merged: RawRange[] = [];
  for (const r of sorted) {
    const last = merged[merged.length - 1];
    if (last && r.start <= last.end + 1e-6) last.end = Math.max(last.end, r.end);
    else merged.push({ ...r });
  }
  return merged;
}

/** The parts of each raw clip that no shot uses (what was cut away); slivers under `minLen` s are ignored. */
export function cutGaps(raw: RawClip[], kept: KeptRange[], minLen = 0.05): RawRange[] {
  const gaps: RawRange[] = [];
  for (const r of raw) {
    const used = mergeRanges(kept.filter((k) => k.clipId === r.clipId).map((k) => ({ start: k.rawStart, end: k.rawEnd })));
    if (!used.length) continue; // a clip the agent did not use at all stays plain raw (not "cut")
    let t = r.start;
    for (const u of used) {
      if (u.start - t >= minLen) gaps.push({ start: t, end: u.start });
      t = Math.max(t, u.end);
    }
    if (r.end - t >= minLen) gaps.push({ start: t, end: r.end });
  }
  return gaps;
}

/** Raw-strip times where a cut happens: the edges of the kept parts that are not a clip's own start / end. */
export function cutPointsOf(raw: RawClip[], kept: KeptRange[], eps = 0.05): number[] {
  const pts: number[] = [];
  for (const r of raw) {
    const used = mergeRanges(kept.filter((k) => k.clipId === r.clipId).map((k) => ({ start: k.rawStart, end: k.rawEnd })));
    for (const u of used) {
      if (u.start - r.start > eps) pts.push(u.start);
      if (r.end - u.end > eps) pts.push(u.end);
    }
  }
  return pts.sort((a, b) => a - b).filter((p, i, all) => i === 0 || p - all[i - 1] > eps);
}

/** Timing (ms) of the cut animation: highlight the kept parts, drop the rest, then slide each shot into the edit. */
export interface CutSchedule {
  /** Kept part i lights up at highlightAt(i); the cut-away parts dim and ✂ marks pop during the highlight. */
  highlightStep: number;
  highlightMs: number;
  /** Shot i starts sliding at highlightMs + i * step and takes morphMs; its edited block pops in at the end. */
  step: number;
  morphMs: number;
  /** When the whole animation is over (last block popped in). */
  doneMs: number;
}

/** ~150-250 ms per shot, squeezed so the whole cut animation stays within `budgetMs` (≈ 4 s). */
export function cutSchedule(shots: number, budgetMs = 4000, popMs = 340): CutSchedule {
  const highlightMs = shots > 0 ? 700 : 0;
  const morphMs = 450;
  if (shots <= 0) return { highlightStep: 0, highlightMs: 0, step: 0, morphMs, doneMs: 0 };
  const room = Math.max(0, budgetMs - highlightMs - morphMs - popMs);
  const step = shots <= 1 ? 0 : Math.floor(Math.min(220, room / (shots - 1)));
  const highlightStep = shots <= 1 ? 0 : Math.round(Math.min(60, 450 / (shots - 1)));
  return { highlightStep, highlightMs, step, morphMs, doneMs: highlightMs + (shots - 1) * step + morphMs + popMs };
}

/** When shot i's edited block pops in (ms after the cut animation starts). */
export function shotPopAt(s: CutSchedule, i: number): number {
  return s.highlightMs + i * s.step + Math.round(s.morphMs * 0.85);
}

/**
 * Reveal order of the effects after the cut: the colour grade, the song, then text and FX blocks left → right,
 * one after another (≤ 260 ms apart, the whole row within `budgetMs`). Returns ms offsets by block key
 * (`'color'` for the colour chip), counted from `startMs` (the end of the cut animation).
 */
export function revealOffsets(
  model: Pick<StudioTimelineModel, 'text'> & { live?: Pick<StudioLiveInfo, 'fxLanes' | 'music' | 'color'> },
  startMs: number,
  budgetMs = 3000,
): Record<string, number> {
  const keys: string[] = [];
  if (model.live?.color) keys.push('color');
  for (const m of model.live?.music ?? []) keys.push(m.key);
  const timed = [
    ...model.text.map((t) => ({ key: t.key, start: t.start })),
    ...(model.live?.fxLanes.flat() ?? []).map((x) => ({ key: x.key, start: x.start })),
  ].sort((a, b) => a.start - b.start);
  keys.push(...timed.map((x) => x.key));
  const step = keys.length <= 1 ? 0 : Math.min(260, budgetMs / (keys.length - 1));
  const out: Record<string, number> = {};
  keys.forEach((k, i) => {
    out[k] = Math.round(startMs + i * step);
  });
  return out;
}

/** Short chip of an FX block ("⚡ flash", "✨ zoom"). */
export function fxChipLabel(type: string): string {
  const t = type.toLowerCase();
  const glyph = /flash|strobe|glitch/.test(t)
    ? '⚡'
    : /shake|wobble/.test(t)
      ? '〰'
      : /bw|b&w|black|mono|gray|grey/.test(t)
        ? '◐'
        : /fade|dissolve|wipe|slide|xfade|transition|whip/.test(t)
          ? '⇄'
          : /slow|speed|ramp|stutter/.test(t)
            ? '⏱'
            : '✨';
  return `${glyph} ${type}`;
}

/** Music block name without the file extension ("calm_80bpm"). */
export function songLabel(name: string): string {
  return name.replace(/\.[a-z0-9]{2,4}$/i, '');
}

export interface StudioTimelineModel {
  segments: StudioSegment[];
  text: StudioTextItem[];
  overlays: StudioOverlayTrack[];
  /** Output duration in seconds. */
  total: number;
  source: 'plan' | 'clips' | 'empty' | 'live';
  /** Present only while a job builds the edit live. */
  live?: StudioLiveInfo;
}

/**
 * Output timing exactly like the renderer: each segment lasts (out - in) / speed and the next
 * segment starts early by the duration of the transition whose `after` is the previous segment's
 * index (transitions with after -1 / -2 — intro / outro — never overlap). The overlap is capped
 * at the shorter of the two neighbouring segments.
 */
export function buildStudioTimeline(plan: EditPlan | null | undefined, clips: Clip[]): StudioTimelineModel {
  const byId = new Map(clips.map((c) => [c.id, c]));
  const labelOf = (id: string) => byId.get(id)?.filename ?? id;

  let segments: StudioSegment[] = [];
  let source: StudioTimelineModel['source'] = 'empty';

  if (plan && Array.isArray(plan.clips) && plan.clips.length > 0) {
    const sorted = [...plan.clips].sort((a, b) => a.order - b.order);
    const transitions = plan.transitions ?? [];
    const overlapAfter = (index: number) =>
      transitions.filter((t) => t.after === index).reduce((sum, t) => sum + Math.max(0, t.duration || 0), 0);
    let prevEnd = 0;
    let prevDur = 0;
    sorted.forEach((pc, i) => {
      const speed = pc.speed > 0 ? pc.speed : 1;
      const dur = Math.max(0, (pc.out - pc.in) / speed);
      if (dur <= 0) return;
      const idx = segments.length;
      const overlap = idx === 0 ? 0 : Math.min(overlapAfter(idx - 1), prevDur, dur);
      const start = Math.max(0, prevEnd - overlap);
      const end = start + dur;
      segments.push({
        key: `s${i}`,
        clipId: pc.source,
        label: labelOf(pc.source),
        in: pc.in,
        out: pc.out,
        speed,
        start,
        end,
        clipDuration: byId.get(pc.source)?.duration ?? 0,
      });
      prevEnd = end;
      prevDur = dur;
    });
    if (segments.length) source = 'plan';
  }

  if (!segments.length) {
    let t = 0;
    segments = clips
      .filter((c) => c.duration > 0)
      .map((c) => {
        const seg: StudioSegment = {
          key: `c${c.id}`,
          clipId: c.id,
          label: c.filename,
          in: 0,
          out: c.duration,
          speed: 1,
          start: t,
          end: t + c.duration,
          clipDuration: c.duration,
        };
        t += c.duration;
        return seg;
      });
    source = segments.length ? 'clips' : 'empty';
  }

  const total = segments.reduce((m, s) => Math.max(m, s.end), 0);
  const clamp = (start: number, end: number): [number, number] => {
    const s = Math.max(0, Math.min(start || 0, total));
    let e = Number.isFinite(end) && end > s ? Math.min(end, total) : total;
    if (e <= s) e = total;
    return [s, e];
  };

  const text: StudioTextItem[] =
    source === 'plan'
      ? (plan?.text ?? []).map((t, i) => {
          const [start, end] = clamp(t.start, t.end);
          return { key: `t${i}`, kind: t.kind, label: t.text, start, end };
        })
      : [];

  const overlays: StudioOverlayTrack[] =
    source === 'plan'
      ? (plan?.overlays ?? []).map((o, i) => {
          const [start, end] = clamp(o.start, o.end);
          return { key: `o${i}`, label: o.label, colors: o.colors ?? [], start, end, overlay: o };
        })
      : [];

  return { segments, text, overlays, total, source };
}

export interface Span {
  x: number;
  width: number;
}

/** Pixels per second for a track area `width` px wide at `zoom` (1 = whole edit fits). */
export function pxPerSecond(total: number, width: number, zoom = 1): number {
  if (total <= 0 || width <= 0) return 0;
  return (width / total) * Math.max(1, zoom);
}

/** Horizontal span of a [start, end] item. */
export function spanOf(start: number, end: number, pps: number, minWidth = 2): Span {
  return { x: start * pps, width: Math.max(minWidth, (end - start) * pps) };
}

/**
 * Crop of a clip's filmstrip (frames covering the whole source clip) for a segment drawn
 * `segWidth` px wide: the strip is scaled so the in..out part fills the segment exactly.
 */
export function filmstripCrop(
  seg: Pick<StudioSegment, 'in' | 'out' | 'clipDuration'>,
  segWidth: number,
): { stripWidth: number; offsetX: number } {
  const len = seg.out - seg.in;
  if (len <= 0 || seg.clipDuration <= 0) return { stripWidth: segWidth, offsetX: 0 };
  const stripWidth = (segWidth * seg.clipDuration) / len;
  return { stripWidth, offsetX: -(seg.in / seg.clipDuration) * stripWidth };
}

/** Peaks covering the segment's in..out range of the source clip. */
export function slicePeaks(peaks: number[], duration: number, inPoint: number, outPoint: number): number[] {
  if (!peaks.length || duration <= 0) return [];
  const n = peaks.length;
  const a = Math.max(0, Math.min(n, Math.floor((inPoint / duration) * n)));
  const b = Math.max(a, Math.min(n, Math.ceil((outPoint / duration) * n)));
  return peaks.slice(a, b);
}

/** "MM:SS" timecode. */
export function formatTimecode(seconds: number): string {
  const total = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

/** Ruler ticks: a labelled tick every `step` seconds, where step keeps labels ≥ `minGapPx` apart. */
export function rulerTicks(total: number, pps: number, minGapPx = 70): { t: number; label: string }[] {
  if (total <= 0 || pps <= 0) return [];
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300];
  const step = steps.find((s) => s * pps >= minGapPx) ?? 600;
  const ticks: { t: number; label: string }[] = [];
  for (let t = 0; t <= total + 1e-6; t += step) ticks.push({ t, label: formatTimecode(t) });
  return ticks;
}

/** Snap `t` to the nearest segment edge / text / overlay boundary within `thresholdSec`. */
export function snapTime(model: StudioTimelineModel, t: number, thresholdSec: number): number {
  const edges = [0, model.total];
  for (const s of model.segments) edges.push(s.start, s.end);
  for (const x of model.text) edges.push(x.start, x.end);
  for (const o of model.overlays) edges.push(o.start, o.end);
  for (const x of [...(model.live?.fxLanes.flat() ?? []), ...(model.live?.music ?? [])]) edges.push(x.start, x.end);
  let best = t;
  let bestD = thresholdSec;
  for (const e of edges) {
    const d = Math.abs(e - t);
    if (d <= bestD) {
      best = e;
      bestD = d;
    }
  }
  return best;
}

/**
 * Greedy lane split: each item goes into the first lane whose last item ended before it starts; when all
 * `maxLanes` lanes are busy it goes into the lane that frees up first. Items keep their start order.
 */
export function assignLanes<T extends { start: number; end: number }>(items: T[], maxLanes = 2): T[][] {
  const lanes: T[][] = [];
  const sorted = [...items].sort((a, b) => a.start - b.start);
  for (const it of sorted) {
    const free = lanes.find((l) => l[l.length - 1].end <= it.start + 1e-6);
    if (free) free.push(it);
    else if (lanes.length < maxLanes) lanes.push([it]);
    else lanes.reduce((a, b) => (a[a.length - 1].end <= b[b.length - 1].end ? a : b)).push(it);
  }
  return lanes;
}

/** Short signature of a track's items (keys only), used for the live `revision`. */
function trackSig(tracks: LiveTimeline, track: keyof LiveTimeline): string {
  const items = (tracks[track] ?? []) as unknown as ({ start: number; dur: number } & Record<string, unknown>)[];
  if (track === 'color') return colorLabel(tracks.color) ?? '';
  return `${items.length}:${items.map((x, i) => blockKey(track, x, i)).join('|')}`;
}

/**
 * The studio timeline model of an edit the agents are building right now (job `timeline` events /
 * snapshot): Main = the live shots (one block per shot, with its frame), Text = the live text items,
 * FX lanes and a Music row from the live `fx` / `music` tracks. Total = the live total (end of the cut).
 */
export function buildLiveStudioTimeline(
  state: Pick<LiveState, 'tracks' | 'lastTrack'> & Partial<Pick<LiveState, 'thoughts' | 'renderStep' | 'stage' | 'started'>>,
  clips: Clip[],
  job?: Partial<Pick<Job, 'status' | 'stage' | 'queue_position'>> | null,
): StudioTimelineModel {
  const { tracks } = state;
  const byId = new Map(clips.map((c) => [c.id, c]));
  const hasAny = (['video', 'text', 'fx', 'music'] as const).some((t) => (tracks[t]?.length ?? 0) > 0);
  const raw = rawLayout(clips);
  const rawTotal = raw.length ? raw[raw.length - 1].end : 0;
  const hasVideo = (tracks.video ?? []).some((v) => v.dur > 0);
  // before the cut lands the Main track shows the raw footage, so the ruler spans it
  const total = hasVideo ? liveTotal(tracks) : rawTotal > 0 ? Math.max(rawTotal, hasAny ? liveTotal(tracks) : 0) : hasAny ? liveTotal(tracks) : 0;

  const segments: StudioSegment[] = (tracks.video ?? [])
    .filter((v) => v.dur > 0)
    .map((v, i) => {
      const speed = v.speed && v.speed > 0 ? v.speed : 1;
      const inPoint = typeof v.in === 'number' && Number.isFinite(v.in) ? v.in : 0;
      const outPoint = typeof v.out === 'number' && Number.isFinite(v.out) && v.out > inPoint ? v.out : inPoint + v.dur * speed;
      return {
        key: `live-${blockKey('video', v as unknown as { start: number; dur: number } & Record<string, unknown>, i)}`,
        clipId: v.clip_id,
        label: byId.get(v.clip_id)?.filename ?? v.filename ?? v.clip_id,
        in: inPoint,
        out: outPoint,
        speed,
        start: v.start,
        end: v.start + v.dur,
        clipDuration: byId.get(v.clip_id)?.duration ?? 0,
        thumb: v.thumb ?? null,
      };
    });

  const timed = <T extends { start: number; dur: number }>(track: 'text' | 'fx' | 'music', items: T[] | undefined, label: (x: T) => string) =>
    (items ?? []).map((x, i) => ({
      key: `live-${blockKey(track, x as unknown as { start: number; dur: number } & Record<string, unknown>, i)}`,
      label: label(x),
      start: Math.min(x.start, total),
      end: Math.min(x.start + Math.max(x.dur, 0), total),
    }));

  const text: StudioTextItem[] = (tracks.text ?? []).map((x, i) => ({
    key: `live-${blockKey('text', x as unknown as { start: number; dur: number } & Record<string, unknown>, i)}`,
    kind: x.kind,
    label: x.text,
    start: Math.min(x.start, total),
    end: Math.min(x.start + Math.max(x.dur, 0), total),
  }));

  const revision = (['video', 'text', 'fx', 'music', 'color'] as const).map((t) => trackSig(tracks, t)).join('#');
  const phase = livePhase(job, { stage: state.stage, renderStep: state.renderStep, started: state.started });
  const kept = keptRanges(raw, segments);

  return {
    segments,
    text,
    overlays: [],
    total,
    source: 'live',
    live: {
      fxLanes: assignLanes(timed('fx', tracks.fx, (x) => x.type), 2),
      music: timed('music', tracks.music, (x) => x.name),
      color: colorLabel(tracks.color),
      buildEnd: Math.min(liveBuildEnd(state), total),
      revision,
      buildCount:
        state.lastTrack && state.lastTrack !== 'color' ? (tracks[state.lastTrack]?.length ?? 0) : segments.length,
      phase,
      ticker: tickerText(phase, { thoughts: state.thoughts ?? [], renderStep: state.renderStep ?? null, stage: state.stage }),
      queuePosition: typeof job?.queue_position === 'number' ? job.queue_position : null,
      raw,
      rawTotal,
      kept,
      gaps: cutGaps(raw, kept),
      cutPoints: cutPointsOf(raw, kept),
      videoSig: trackSig(tracks, 'video'),
      render: renderProgress(phase, state.renderStep, segments.length),
    },
  };
}

/** Animation delay (ms) of the i-th block of a track of `n` blocks: left → right, the whole row in ~1.2 s. */
export function staggerDelay(i: number, n: number, perBlock = 90, maxTotal = 1200): number {
  if (n <= 1) return 0;
  return Math.round(i * Math.min(perBlock, maxTotal / (n - 1)));
}
