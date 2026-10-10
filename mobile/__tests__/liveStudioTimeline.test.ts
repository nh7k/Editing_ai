import type { JobEvent, LiveTimeline } from '../src/api/types';
import { buildLiveState, liveBuildEnd } from '../src/utils/liveTimeline';
import { assignLanes, buildLiveStudioTimeline, snapTime, staggerDelay } from '../src/utils/studioTimeline';
import { clipA, clipB } from './fixtures';

const tracks: LiveTimeline = {
  video: [
    { clip_id: 'c1', filename: 'a.mp4', start: 0, dur: 4, in: 2, out: 6, speed: 1, thumb: '/projects/p1/clips/c1/frame?t=4' },
    { clip_id: 'c2', filename: 'b.mp4', start: 4, dur: 2, thumb: null },
  ],
  text: [{ start: 1, dur: 1.5, text: 'RONALDO', kind: 'title' }],
  fx: [
    { start: 0, dur: 1, type: 'flash' },
    { start: 0.5, dur: 1, type: 'zoom' },
    { start: 3, dur: 0.3, type: 'shake' },
  ],
  music: [{ start: 0, dur: 30, name: 'calm_80bpm.m4a' }],
  color: [{ preset: 'warm', lut: null }],
};

const ev = (seq: number, type: string, extra: Record<string, unknown> = {}): JobEvent => ({ seq, t: seq, type, ...extra });

describe('buildLiveStudioTimeline (live state → the studio timeline model)', () => {
  it('maps live shots to Main segments with thumbs, text to the Text track, fx to lanes, music to a row', () => {
    const m = buildLiveStudioTimeline({ tracks }, [clipA, clipB]);
    expect(m.source).toBe('live');
    expect(m.total).toBe(6);
    expect(m.segments.map((s) => [s.clipId, s.start, s.end, s.in, s.out])).toEqual([
      ['c1', 0, 4, 2, 6],
      ['c2', 4, 6, 0, 2],
    ]);
    // the project clip's name wins; the live filename is the fallback
    expect(m.segments[0].label).toBe('beach.mp4');
    expect(m.segments[0].thumb).toBe('/projects/p1/clips/c1/frame?t=4');
    expect(m.segments[1].thumb).toBeNull();
    expect(m.text).toEqual([expect.objectContaining({ label: 'RONALDO', kind: 'title', start: 1, end: 2.5 })]);
    expect(m.overlays).toEqual([]);
    // overlapping flash + zoom need two lanes; shake fits back into lane 1
    expect(m.live?.fxLanes.map((l) => l.map((x) => x.label))).toEqual([['flash', 'shake'], ['zoom']]);
    // a 30 s song on a 6 s cut is clipped to the cut
    expect(m.live?.music).toEqual([expect.objectContaining({ label: 'calm_80bpm.m4a', start: 0, end: 6 })]);
    expect(m.live?.color).toBe('warm');
    expect(m.live?.buildEnd).toBe(6);
  });

  it('is empty (total 0) before any track arrives, with the cursor at 0', () => {
    const m = buildLiveStudioTimeline({ tracks: {} }, []);
    expect(m.segments).toEqual([]);
    expect(m.total).toBe(0);
    expect(m.live?.buildEnd).toBe(0);
    expect(m.live?.fxLanes).toEqual([]);
  });

  it('the build cursor goes to the end of the track filled last', () => {
    const s = buildLiveState(null, [
      ev(1, 'timeline', { track: 'video', items: tracks.video }),
      ev(2, 'timeline', { track: 'text', items: tracks.text }),
    ]);
    expect(s.lastTrack).toBe('text');
    expect(liveBuildEnd(s)).toBe(2.5);
    expect(buildLiveStudioTimeline(s, []).live?.buildEnd).toBe(2.5);
    expect(buildLiveStudioTimeline(s, []).live?.buildCount).toBe(1);
    // colour has no times → end of the whole cut
    const c = buildLiveState(null, [ev(1, 'timeline', { track: 'video', items: tracks.video }), ev(2, 'timeline', { track: 'color', items: tracks.color })]);
    expect(liveBuildEnd(c)).toBe(6);
  });

  it('a re-cut changes the revision and the segment keys (so blocks animate in again)', () => {
    const a = buildLiveStudioTimeline({ tracks }, []);
    const same = buildLiveStudioTimeline({ tracks: { ...tracks } }, []);
    expect(same.live?.revision).toBe(a.live?.revision);
    expect(same.segments.map((s) => s.key)).toEqual(a.segments.map((s) => s.key));
    const recut = buildLiveStudioTimeline({ tracks: { ...tracks, video: [{ clip_id: 'c3', filename: 'c.mp4', start: 0, dur: 3 }] } }, []);
    expect(recut.live?.revision).not.toBe(a.live?.revision);
    expect(recut.segments[0].key).not.toBe(a.segments[0].key);
    expect(recut.total).toBe(3);
  });

  it('snapping also knows the live fx / music edges', () => {
    const m = buildLiveStudioTimeline({ tracks }, []);
    expect(snapTime(m, 3.05, 0.1)).toBe(3);
  });
});

describe('assignLanes / staggerDelay', () => {
  it('splits overlapping items into lanes, at most maxLanes', () => {
    const items = [
      { start: 0, end: 2 },
      { start: 1, end: 3 },
      { start: 1.5, end: 4 },
      { start: 2, end: 5 },
    ];
    const lanes = assignLanes(items, 2);
    expect(lanes).toHaveLength(2);
    expect(lanes.flat()).toHaveLength(4);
    expect(lanes[0][0]).toEqual({ start: 0, end: 2 });
    expect(lanes[0][1]).toEqual({ start: 1.5, end: 4 });
  });

  it('staggers blocks left → right within ~1.2 s', () => {
    expect(staggerDelay(0, 1)).toBe(0);
    expect(staggerDelay(3, 5)).toBe(270);
    expect(staggerDelay(99, 100)).toBe(1200);
  });
});
