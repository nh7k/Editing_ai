import type { JobEvent } from '../src/api/types';
import {
  EMPTY_LIVE,
  applyLiveEvent,
  blockGeometry,
  blockKey,
  buildLiveState,
  colorLabel,
  hasLiveContent,
  liveTotal,
  pxPerSecond,
  secondsLabel,
  workingAgent,
} from '../src/utils/liveTimeline';
import { runningJob } from './fixtures';

const ev = (seq: number, type: string, extra: Record<string, unknown> = {}): JobEvent => ({ seq, t: seq * 0.5, type, ...extra });

const video1 = [
  { clip_id: 'c1', filename: 'a.mp4', start: 0, dur: 4, in: 12.3, out: 16.3, speed: 1, thumb: '/projects/p1/clips/c1/frame?t=14.3' },
  { clip_id: 'c2', filename: 'b.mp4', start: 4, dur: 2, thumb: '/projects/p1/clips/c2/frame?t=1' },
];

describe('liveTimeline reducer', () => {
  it('appends thoughts one by one and ignores other events', () => {
    let s = applyLiveEvent(EMPTY_LIVE, ev(1, 'thought', { agent: 'Cutter', text: 'Picked 9 shots of ~4 s from 3 clips' }));
    s = applyLiveEvent(s, ev(2, 'node_started', { node: 'color' }));
    s = applyLiveEvent(s, ev(3, 'thought', { agent: 'Color', text: 'Warm look' }));
    expect(s.thoughts.map((t) => [t.agent, t.text])).toEqual([
      ['Cutter', 'Picked 9 shots of ~4 s from 3 clips'],
      ['Color', 'Warm look'],
    ]);
    expect(s.lastSeq).toBe(3);
  });

  it('skips events already applied (same or older seq)', () => {
    const s1 = applyLiveEvent(EMPTY_LIVE, ev(5, 'thought', { agent: 'A', text: 'one' }));
    expect(applyLiveEvent(s1, ev(5, 'thought', { agent: 'A', text: 'one' }))).toBe(s1);
    expect(applyLiveEvent(s1, ev(4, 'thought', { agent: 'A', text: 'old' }))).toBe(s1);
  });

  it('a later timeline event for a track REPLACES that track; others stay', () => {
    let s = applyLiveEvent(EMPTY_LIVE, ev(1, 'timeline', { track: 'video', items: video1 }));
    s = applyLiveEvent(s, ev(2, 'timeline', { track: 'text', items: [{ start: 1, dur: 1.5, text: 'RONALDO', kind: 'title' }] }));
    expect(s.tracks.video).toHaveLength(2);
    s = applyLiveEvent(s, ev(3, 'timeline', { track: 'video', items: [{ clip_id: 'c3', filename: 'c.mp4', start: 0, dur: 3 }] }));
    expect(s.tracks.video).toHaveLength(1);
    expect(s.tracks.video?.[0].clip_id).toBe('c3');
    expect(s.tracks.text?.[0].text).toBe('RONALDO');
  });

  it('ignores unknown tracks and cleans junk items', () => {
    let s = applyLiveEvent(EMPTY_LIVE, ev(1, 'timeline', { track: 'weird', items: [{ start: 0, dur: 1 }] }));
    expect(s.tracks).toEqual({});
    s = applyLiveEvent(s, ev(2, 'timeline', { track: 'fx', items: [null, 'x', { start: '3', dur: 0.3, type: 'flash' }] }));
    expect(s.tracks.fx).toEqual([{ start: 3, dur: 0.3, type: 'flash' }]);
  });

  it('accepts event data nested under `data`', () => {
    const s = applyLiveEvent(EMPTY_LIVE, ev(1, 'thought', { data: { agent: 'Audio', text: 'Song: calm_80bpm' } }));
    expect(s.thoughts[0]).toMatchObject({ agent: 'Audio', text: 'Song: calm_80bpm' });
  });
});

describe('buildLiveState (SSE events + polled snapshot)', () => {
  it('works from the polled snapshot alone', () => {
    const s = buildLiveState(
      {
        timeline: { video: video1, music: [{ start: 0, dur: 30, name: 'calm_80bpm.m4a' }], color: [{ preset: 'warm', lut: null }] },
        thoughts: [
          { t: 1, agent: 'Director', text: 'Fast fan edit, 15 s' },
          { t: 2, agent: 'Cutter', text: 'Picked 9 shots' },
        ],
      },
      [],
    );
    expect(s.thoughts.map((t) => t.text)).toEqual(['Fast fan edit, 15 s', 'Picked 9 shots']);
    expect(s.tracks.video).toHaveLength(2);
    expect(colorLabel(s.tracks.color)).toBe('warm');
    expect(hasLiveContent(s)).toBe(true);
  });

  it('events win over the snapshot for the tracks they filled; snapshot fills the rest', () => {
    const s = buildLiveState(
      { timeline: { video: video1, text: [{ start: 0, dur: 1, text: 'HI', kind: 'title' }] }, thoughts: [] },
      [ev(2, 'timeline', { track: 'video', items: [{ clip_id: 'c9', filename: 'z.mp4', start: 0, dur: 5 }] })],
    );
    expect(s.tracks.video?.map((v) => v.clip_id)).toEqual(['c9']);
    expect(s.tracks.text?.[0].text).toBe('HI');
  });

  it('orders events by seq and uses whichever source knows more thoughts', () => {
    const events = [ev(3, 'thought', { agent: 'B', text: 'second' }), ev(1, 'thought', { agent: 'A', text: 'first' })];
    expect(buildLiveState(null, events).thoughts.map((t) => t.text)).toEqual(['first', 'second']);
    const snap = { thoughts: [1, 2, 3].map((i) => ({ t: i, agent: 'X', text: `s${i}` })) };
    expect(buildLiveState(snap, events).thoughts.map((t) => t.text)).toEqual(['s1', 's2', 's3']);
  });

  it('is empty without anything', () => {
    expect(hasLiveContent(buildLiveState(null, []))).toBe(false);
  });
});

describe('width math', () => {
  it('total = end of the video track, else the longest other track, never below 1 s', () => {
    expect(liveTotal({ video: video1, music: [{ start: 0, dur: 30, name: 'm' }] })).toBe(6);
    expect(liveTotal({ text: [{ start: 2, dur: 1.5, text: 'x', kind: 'title' }] })).toBe(3.5);
    expect(liveTotal({})).toBe(1);
  });

  it('pixels per second fit the width, with a floor so long edits scroll', () => {
    expect(pxPerSecond(10, 400)).toBe(40);
    expect(pxPerSecond(100, 400)).toBe(8);
    expect(pxPerSecond(0, 400)).toBe(8);
  });

  it('block width is proportional to dur and clipped to the total', () => {
    expect(blockGeometry(0, 4, 40)).toEqual({ left: 0, width: 160 });
    expect(blockGeometry(4, 2, 40)).toEqual({ left: 160, width: 80 });
    // a 30 s song on a 6 s cut is clipped to 6 s
    expect(blockGeometry(0, 30, 40, 6)).toEqual({ left: 0, width: 240 });
    // tiny fx still visible
    expect(blockGeometry(3, 0.01, 40)).toEqual({ left: 120, width: 3 });
  });

  it('block keys change when a block changes (so replaced blocks animate in)', () => {
    const a = blockKey('video', { ...video1[0] }, 0);
    expect(blockKey('video', { ...video1[0] }, 0)).toBe(a);
    expect(blockKey('video', { ...video1[0], dur: 3 }, 0)).not.toBe(a);
  });

  it('labels', () => {
    expect(secondsLabel(65.4)).toBe('1:05');
    expect(colorLabel([{ preset: null, lut: 'teal' }])).toBe('LUT teal');
    expect(colorLabel(undefined)).toBeNull();
  });
});

describe('workingAgent', () => {
  it('is the running agent, else the latest thought author, and null when the job is over', () => {
    expect(workingAgent(runningJob, [])).toBe('Cutter'); // status "retrying"
    const idle = { ...runningJob, agents: [] };
    expect(workingAgent(idle, [{ key: 'k', t: 0, agent: 'Audio', text: 'x' }])).toBe('Audio');
    expect(workingAgent({ ...runningJob, status: 'done' }, [])).toBeNull();
  });
});
