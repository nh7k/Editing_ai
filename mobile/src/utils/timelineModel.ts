import type { Clip, EditPlan } from '../api/types';
import { segmentColors } from '../theme';

export interface TimelineSegment {
  key: string;
  label: string;
  /** Output start time in seconds. */
  start: number;
  /** Output duration in seconds. */
  duration: number;
  color: string;
}

export interface TimelineModel {
  segments: TimelineSegment[];
  total: number;
  source: 'plan' | 'clips' | 'empty';
}

/**
 * Build timeline segments from the latest edit plan when available,
 * otherwise from the raw clip durations (in import order).
 */
export function buildTimeline(plan: EditPlan | null | undefined, clips: Clip[]): TimelineModel {
  const clipIndex = new Map(clips.map((c, i) => [c.id, i]));
  const nameOf = (id: string) => {
    const c = clips.find((x) => x.id === id);
    return c ? c.filename : id;
  };

  if (plan && Array.isArray(plan.clips) && plan.clips.length > 0) {
    const sorted = [...plan.clips].sort((a, b) => a.order - b.order);
    let t = 0;
    const segments: TimelineSegment[] = [];
    sorted.forEach((pc, i) => {
      const speed = pc.speed > 0 ? pc.speed : 1;
      const duration = Math.max(0, (pc.out - pc.in) / speed);
      if (duration <= 0) return;
      const colorIdx = clipIndex.get(pc.source) ?? i;
      segments.push({
        key: `p${i}`,
        label: nameOf(pc.source),
        start: t,
        duration,
        color: segmentColors[colorIdx % segmentColors.length],
      });
      t += duration;
    });
    if (segments.length > 0) return { segments, total: t, source: 'plan' };
  }

  let t = 0;
  const segments: TimelineSegment[] = [];
  clips.forEach((c, i) => {
    const duration = Math.max(0, c.duration);
    if (duration <= 0) return;
    segments.push({
      key: `c${c.id}`,
      label: c.filename,
      start: t,
      duration,
      color: segmentColors[i % segmentColors.length],
    });
    t += duration;
  });
  return { segments, total: t, source: segments.length ? 'clips' : 'empty' };
}

export interface SegmentRect {
  x: number;
  width: number;
  color: string;
  key: string;
}

/** Map segments to pixel rects within `width`, leaving `gap` px between neighbours. */
export function layoutSegments(model: TimelineModel, width: number, gap = 3): SegmentRect[] {
  if (model.total <= 0 || width <= 0) return [];
  const usable = Math.max(0, width - gap * Math.max(0, model.segments.length - 1));
  let x = 0;
  return model.segments.map((s) => {
    const w = Math.max(2, (s.duration / model.total) * usable);
    const rect = { x, width: w, color: s.color, key: s.key };
    x += w + gap;
    return rect;
  });
}
