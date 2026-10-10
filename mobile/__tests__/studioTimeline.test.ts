import type { EditPlan } from '../src/api/types';
import {
  buildStudioTimeline,
  filmstripCrop,
  formatTimecode,
  pxPerSecond,
  rulerTicks,
  slicePeaks,
  snapTime,
  spanOf,
} from '../src/utils/studioTimeline';
import { clipA, clipB, studioPlan } from './fixtures';

const clips = [clipA, clipB];

describe('buildStudioTimeline', () => {
  it('computes output timing with speed and transition overlap (after == index)', () => {
    const m = buildStudioTimeline(studioPlan, clips);
    expect(m.source).toBe('plan');
    // seg0: (8-2)/1 = 6s -> 0..6 ; crossfade after 0 overlaps 1s ; seg1: (8-0)/2 = 4s -> 5..9
    expect(m.segments.map((s) => [s.clipId, s.start, s.end])).toEqual([
      ['c1', 0, 6],
      ['c2', 5, 9],
    ]);
    expect(m.total).toBe(9);
    expect(m.segments[0].clipDuration).toBe(12);
    expect(m.segments[0].label).toBe('beach.mp4');
  });

  it('ignores intro / outro transitions (after -1 / -2) for overlap', () => {
    const plan: EditPlan = {
      ...studioPlan,
      transitions: [
        { type: 'fade', after: -1, duration: 1 },
        { type: 'fade', after: -2, duration: 1 },
      ],
    };
    const m = buildStudioTimeline(plan, clips);
    expect(m.segments.map((s) => [s.start, s.end])).toEqual([
      [0, 6],
      [6, 10],
    ]);
    expect(m.total).toBe(10);
  });

  it('sorts by order and caps overlap at the shorter neighbour', () => {
    const plan: EditPlan = {
      ...studioPlan,
      clips: [
        { source: 'c2', in: 0, out: 1, order: 1, speed: 1, volume: 1 },
        { source: 'c1', in: 0, out: 4, order: 0, speed: 1, volume: 1 },
      ],
      transitions: [{ type: 'crossfade', after: 0, duration: 3 }],
    };
    const m = buildStudioTimeline(plan, clips);
    expect(m.segments.map((s) => s.clipId)).toEqual(['c1', 'c2']);
    expect(m.segments[1].start).toBe(3);
    expect(m.segments[1].end).toBe(4);
  });

  it('builds text and graphic tracks clamped to the output duration', () => {
    const m = buildStudioTimeline(studioPlan, clips);
    expect(m.text.map((t) => [t.kind, t.label, t.start, t.end])).toEqual([
      ['title', 'Lisbon', 0, 2],
      ['caption', 'Hello world', 3, 5],
    ]);
    expect(m.overlays.map((o) => [o.label, o.start, o.end])).toEqual([
      ['Cyan Indigo Glow', 0, 9],
      ['Violet Wash', 1, 9],
    ]);
    expect(m.overlays[0].colors).toEqual(['#22D3EE', '#6366F1']);
  });

  it('an overlay with end <= start spans to the end of the edit', () => {
    const plan: EditPlan = { ...studioPlan, overlays: [{ ...studioPlan.overlays![0], start: 2, end: 0 }] };
    const m = buildStudioTimeline(plan, clips);
    expect([m.overlays[0].start, m.overlays[0].end]).toEqual([2, 9]);
  });

  it('falls back to raw clips (no text / overlay tracks) without a plan', () => {
    const m = buildStudioTimeline(null, clips);
    expect(m.source).toBe('clips');
    expect(m.segments.map((s) => [s.start, s.end])).toEqual([
      [0, 12],
      [12, 20],
    ]);
    expect(m.text).toEqual([]);
    expect(m.overlays).toEqual([]);
    expect(buildStudioTimeline(null, []).source).toBe('empty');
  });
});

describe('studio timeline pixel math', () => {
  it('maps seconds to pixels with zoom', () => {
    expect(pxPerSecond(10, 500)).toBe(50);
    expect(pxPerSecond(10, 500, 2)).toBe(100);
    expect(pxPerSecond(0, 500)).toBe(0);
    expect(spanOf(2, 5, 50)).toEqual({ x: 100, width: 150 });
    expect(spanOf(2, 2, 50).width).toBe(2);
  });

  it('crops the filmstrip to the segment in/out proportionally', () => {
    // 12s clip, using 3..9 (half of it) drawn 300px wide: the strip is 600px, shifted left by 3/12 of it.
    expect(filmstripCrop({ in: 3, out: 9, clipDuration: 12 }, 300)).toEqual({ stripWidth: 600, offsetX: -150 });
    const full = filmstripCrop({ in: 0, out: 12, clipDuration: 12 }, 240);
    expect(full.stripWidth).toBe(240);
    expect(full.offsetX).toBeCloseTo(0);
    expect(filmstripCrop({ in: 0, out: 5, clipDuration: 0 }, 100)).toEqual({ stripWidth: 100, offsetX: 0 });
  });

  it('slices waveform peaks for the segment', () => {
    const peaks = Array.from({ length: 10 }, (_, i) => i / 10);
    expect(slicePeaks(peaks, 10, 2, 5)).toEqual([0.2, 0.3, 0.4]);
    expect(slicePeaks([], 10, 0, 5)).toEqual([]);
  });

  it('formats timecodes and ruler ticks', () => {
    expect(formatTimecode(0)).toBe('00:00');
    expect(formatTimecode(14.7)).toBe('00:14');
    expect(formatTimecode(75)).toBe('01:15');
    expect(rulerTicks(5, 100).map((t) => t.label)).toEqual(['00:00', '00:01', '00:02', '00:03', '00:04', '00:05']);
    expect(rulerTicks(20, 20).map((t) => t.t)).toEqual([0, 5, 10, 15, 20]);
  });

  it('snaps to nearby segment / track boundaries', () => {
    const m = buildStudioTimeline(studioPlan, clips);
    expect(snapTime(m, 5.1, 0.2)).toBe(5);
    expect(snapTime(m, 7.5, 0.2)).toBe(7.5);
  });
});
