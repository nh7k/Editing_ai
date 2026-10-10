import type { EditPlan } from '../src/api/types';
import { buildTimeline, layoutSegments } from '../src/utils/timelineModel';
import { clipA, clipB } from './fixtures';

const plan: EditPlan = {
  version: '1.0',
  canvas: { aspect_ratio: '9:16', resolution: 720, fps: 30, reframe: 'crop' },
  clips: [
    { source: 'c2', in: 0, out: 4, order: 1, speed: 2, volume: 1 },
    { source: 'c1', in: 2, out: 8, order: 0, speed: 1, volume: 1 },
  ],
};

describe('timeline model', () => {
  it('uses the edit plan when available (ordered, speed-adjusted)', () => {
    const m = buildTimeline(plan, [clipA, clipB]);
    expect(m.source).toBe('plan');
    expect(m.segments.map((s) => [s.label, s.start, s.duration])).toEqual([
      ['beach.mp4', 0, 6],
      ['city.mp4', 6, 2],
    ]);
    expect(m.total).toBe(8);
  });

  it('falls back to clip durations without a plan', () => {
    const m = buildTimeline(null, [clipA, clipB]);
    expect(m.source).toBe('clips');
    expect(m.total).toBe(20);
    expect(m.segments.map((s) => s.duration)).toEqual([12, 8]);
  });

  it('is empty without clips', () => {
    expect(buildTimeline(undefined, []).source).toBe('empty');
  });

  it('lays out rects proportional to duration', () => {
    const rects = layoutSegments(buildTimeline(null, [clipA, clipB]), 203, 3);
    expect(rects).toHaveLength(2);
    expect(rects[0].x).toBe(0);
    expect(rects[0].width).toBeCloseTo(120);
    expect(rects[1].x).toBeCloseTo(123);
    expect(rects[1].width).toBeCloseTo(80);
  });
});
