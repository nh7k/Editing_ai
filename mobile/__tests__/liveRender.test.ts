import type { Job, JobEvent, LiveTimeline } from '../src/api/types';
import {
  EMPTY_LIVE,
  agentGlyph,
  applyLiveEvent,
  buildLiveState,
  isRenderStage,
  livePhase,
  parseRenderStep,
  queueLabel,
  renderProgress,
  shortThought,
  tickerText,
} from '../src/utils/liveTimeline';
import {
  buildLiveStudioTimeline,
  cutGaps,
  cutPointsOf,
  cutSchedule,
  fxChipLabel,
  keptRanges,
  rawLayout,
  revealOffsets,
  shotPopAt,
  songLabel,
} from '../src/utils/studioTimeline';
import { clipA, clipB, runningJob } from './fixtures';

const ev = (seq: number, type: string, extra: Record<string, unknown> = {}): JobEvent => ({ seq, t: seq * 0.5, type, ...extra });

// clipA = beach.mp4 (12 s), clipB = city.mp4 (8 s) → raw strip 0..12 | 12..20
const video: LiveTimeline['video'] = [
  { clip_id: 'c1', filename: 'beach.mp4', start: 0, dur: 2, in: 3, out: 5, speed: 1, thumb: null },
  { clip_id: 'c2', filename: 'city.mp4', start: 2, dur: 1.5, in: 0, out: 1.5, speed: 1, thumb: null },
  { clip_id: 'c1', filename: 'beach.mp4', start: 3.5, dur: 1, in: 10, out: 11, speed: 1, thumb: null },
];

describe('render steps', () => {
  it('parses render_step events and renderer messages (the job stage while rendering)', () => {
    expect(parseRenderStep({ step: 'segment', done: 4, total: 9, text: 'rendering segment 4/9' })).toEqual({
      step: 'segment',
      done: 4,
      total: 9,
      text: 'rendering segment 4/9',
    });
    expect(parseRenderStep('retry 1: rendering segment 2/7')).toMatchObject({ step: 'segment', done: 2, total: 7 });
    expect(parseRenderStep('rendering 9 segments')).toMatchObject({ step: 'segment', done: 0, total: 9 });
    expect(parseRenderStep({ step: 'start', done: null, total: null, text: 'rendering 9 segments' })).toMatchObject({
      step: 'segment',
      done: 0,
      total: 9,
    });
    expect(parseRenderStep('joining segments')?.step).toBe('join');
    expect(parseRenderStep('adding text, music and final encode')?.step).toBe('finish');
    expect(parseRenderStep('exporting GIF')?.step).toBe('finish');
    expect(parseRenderStep('reusing the cut (only text / audio changed)')?.step).toBe('reuse');
    expect(parseRenderStep('render complete')?.step).toBe('done');
    expect(parseRenderStep('re-rendering (retry 1)')?.step).toBe('start');
    expect(parseRenderStep('cutter agent')).toBeNull();
    expect(parseRenderStep(null)).toBeNull();
  });

  it('knows render stages', () => {
    expect(isRenderStage('rendering')).toBe(true);
    expect(isRenderStage('retry 1: joining segments')).toBe(true);
    expect(isRenderStage('reviewing')).toBe(false);
    expect(isRenderStage('cutter agent')).toBe(false);
    expect(isRenderStage(undefined)).toBe(false);
  });
});

describe('live reducer: render_step / progress / queue', () => {
  it('keeps the latest render step (flat or nested under data) and marks the job started', () => {
    let s = applyLiveEvent(EMPTY_LIVE, ev(1, 'render_step', { step: 'segment', done: 1, total: 9, text: 'rendering segment 1/9', round: 0 }));
    expect(s.renderStep).toEqual({ step: 'segment', done: 1, total: 9, text: 'rendering segment 1/9', round: 0 });
    expect(s.started).toBe(true);
    s = applyLiveEvent(s, ev(2, 'render_step', { data: { step: 'join', done: null, total: null, text: 'joining segments' } }));
    expect(s.renderStep?.step).toBe('join');
    expect(s.lastSeq).toBe(2);
  });

  it('a newer timeline event (a re-cut) or a non-render stage clears the render step', () => {
    let s = applyLiveEvent(EMPTY_LIVE, ev(1, 'render_step', { step: 'segment', done: 9, total: 9, text: 'rendering segment 9/9' }));
    s = applyLiveEvent(s, ev(2, 'timeline', { track: 'video', items: video }));
    expect(s.renderStep).toBeNull();
    s = applyLiveEvent(s, ev(3, 'progress', { stage: 'rendering segment 3/9', progress: 60 }));
    expect(s.stage).toBe('rendering segment 3/9');
    expect(s.renderStep).toMatchObject({ step: 'segment', done: 3, total: 9 });
    s = applyLiveEvent(s, ev(4, 'progress', { stage: 'reviewing', progress: 88 }));
    expect(s.stage).toBe('reviewing');
    expect(s.renderStep).toBeNull();
  });

  it('a plain "rendering" stage does not wipe a known step', () => {
    let s = applyLiveEvent(EMPTY_LIVE, ev(1, 'render_step', { step: 'segment', done: 2, total: 9, text: 'rendering segment 2/9' }));
    s = applyLiveEvent(s, ev(2, 'progress', { stage: 'rendering' }));
    expect(s.renderStep).toMatchObject({ step: 'segment', done: 2 });
  });

  it('polling fallback: stage first, job.render_step only while the stage is a render stage', () => {
    const base = { timeline: {}, thoughts: [] };
    expect(buildLiveState({ ...base, status: 'running', stage: 'rendering segment 5/9' }, []).renderStep).toMatchObject({
      step: 'segment',
      done: 5,
    });
    expect(
      buildLiveState(
        { ...base, status: 'running', stage: 'rendering', render_step: { step: 'segment', done: 3, total: 9, text: 'rendering segment 3/9' } },
        [],
      ).renderStep,
    ).toMatchObject({ step: 'segment', done: 3 });
    // after the render (a retry's agents are working) the snapshot's old render step is ignored
    const stale = buildLiveState(
      { ...base, status: 'running', stage: 'cutter agent', render_step: { step: 'done', done: null, total: null, text: 'render complete' } },
      [],
    );
    expect(stale.renderStep).toBeUndefined();
    expect(stale.stage).toBe('cutter agent');
    expect(stale.started).toBe(true);
    expect(buildLiveState({ ...base, status: 'queued', stage: 'queued' }, []).started).toBeUndefined();
  });

  it('events win over the polled stage', () => {
    const s = buildLiveState({ timeline: {}, thoughts: [], status: 'running', stage: 'effects agent' }, [
      ev(1, 'progress', { stage: 'joining segments' }),
    ]);
    expect(s.stage).toBe('joining segments');
    expect(s.renderStep?.step).toBe('join');
  });
});

describe('livePhase', () => {
  it('queued → working → rendering → reviewing', () => {
    expect(livePhase({ status: 'queued', stage: 'queued' }, {})).toBe('queued');
    expect(livePhase({ status: 'queued', stage: 'queued' }, { started: true, stage: 'analyzing clips' })).toBe('working');
    expect(livePhase({ status: 'running', stage: 'cutter agent' }, {})).toBe('working');
    expect(livePhase({ status: 'running', stage: 'rendering segment 1/9' }, {})).toBe('rendering');
    expect(livePhase({ status: 'running', stage: 'retry 1: adding text, music and final encode' }, {})).toBe('rendering');
    expect(livePhase({ status: 'running', stage: 'reviewing' }, {})).toBe('reviewing');
    // the stage in the events is fresher than the polled one
    expect(livePhase({ status: 'running', stage: 'effects agent' }, { stage: 'reviewing' })).toBe('reviewing');
    expect(livePhase(null, { renderStep: { step: 'join', done: null, total: null, text: 'joining segments' } })).toBe('rendering');
  });
});

describe('ticker text', () => {
  const thought = (agent: string, text: string) => ({ key: 'k', t: 1, agent, text });
  it('prefixes the latest thought by agent and strips the reason', () => {
    expect(tickerText('working', { thoughts: [thought('cutter', 'Picked 9 shots of ~4 s from 3 clips — fast pace asked')], renderStep: null })).toBe(
      '✂ Picked 9 shots of ~4 s from 3 clips',
    );
    expect(tickerText('working', { thoughts: [thought('color', 'Warm look (whole edit).')], renderStep: null })).toBe('🎨 Warm look (whole edit)');
    expect(tickerText('working', { thoughts: [], renderStep: null })).toBe('🧠 Prompt samajh raha hai');
  });

  it('agent glyphs', () => {
    expect(['cutter', 'Color', 'effects', 'audio', 'render', 'review', 'director', 'analyzer', 'Agent'].map(agentGlyph)).toEqual([
      '✂',
      '🎨',
      '✨',
      '♪',
      '🎬',
      '👀',
      '🧠',
      '🧠',
      '🧠',
    ]);
  });

  it('shortens long thoughts', () => {
    const s = shortThought('x'.repeat(200));
    expect(s.length).toBe(64);
    expect(s.endsWith('…')).toBe(true);
    expect(shortThought('Cut silences; kept 12 s')).toBe('Cut silences');
  });

  it('render steps, review and queue', () => {
    const step = (s: string, done: number | null = null, total: number | null = null) => ({ step: s, done, total, text: '' });
    expect(tickerText('rendering', { thoughts: [], renderStep: step('segment', 4, 9) })).toBe('🎬 Shot 4/9 ban gaya');
    expect(tickerText('rendering', { thoughts: [], renderStep: step('segment', 0, 9) })).toBe('🎬 9 shots render ho rahe hain');
    expect(tickerText('rendering', { thoughts: [], renderStep: step('join') })).toBe('🎬 Shots jod raha hai');
    expect(tickerText('rendering', { thoughts: [], renderStep: step('finish') })).toBe('🎬 Text + gaana + final encode');
    expect(tickerText('rendering', { thoughts: [], renderStep: step('reuse') })).toBe('🎬 Cut wahi hai, sirf text/gaana');
    expect(tickerText('rendering', { thoughts: [], renderStep: null })).toBe('🎬 Video render ho raha hai');
    expect(tickerText('reviewing', { thoughts: [thought('cutter', 'x')], renderStep: null })).toBe('👀 Result dekh raha hai');
    expect(tickerText('queued', { thoughts: [], renderStep: null })).toMatch(/^⏳/);
    expect(queueLabel(2)).toBe('Line me hai — 2 edit aage');
    expect(queueLabel(0)).toBe('Line me hai — agla number aapka');
    expect(queueLabel(undefined)).toBe('Line me hai — agla number aapka');
  });
});

describe('renderProgress (render steps → ✓ on the Main blocks)', () => {
  const step = (s: string, done: number | null = null, total: number | null = null) => ({ step: s, done, total, text: '' });
  it('fills the first `done` blocks, scaled when the renderer counts differently', () => {
    expect(renderProgress('rendering', step('segment', 4, 9), 9)).toEqual({ doneCount: 4, shimmer: false, reuse: false });
    expect(renderProgress('rendering', step('segment', 5, 10), 4)).toEqual({ doneCount: 2, shimmer: false, reuse: false });
    expect(renderProgress('rendering', step('segment', 12, 9), 9).doneCount).toBe(9);
  });
  it('join / finish: all ✓ + shimmer; reuse: all ✓ at once; review: all ✓; otherwise nothing', () => {
    expect(renderProgress('rendering', step('join'), 9)).toEqual({ doneCount: 9, shimmer: true, reuse: false });
    expect(renderProgress('rendering', step('finish'), 9)).toEqual({ doneCount: 9, shimmer: true, reuse: false });
    expect(renderProgress('rendering', step('reuse'), 9)).toEqual({ doneCount: 9, shimmer: true, reuse: true });
    expect(renderProgress('rendering', step('done'), 9)).toEqual({ doneCount: 9, shimmer: false, reuse: false });
    expect(renderProgress('reviewing', null, 9).doneCount).toBe(9);
    expect(renderProgress('working', step('segment', 4, 9), 9).doneCount).toBe(0);
    expect(renderProgress('rendering', step('segment', 4, 9), 0).doneCount).toBe(0);
  });
});

describe('raw footage → kept ranges → cuts', () => {
  const raw = rawLayout([clipA, { ...clipB }, { ...clipB, id: 'cx', duration: 0 }]);
  const segs = buildLiveStudioTimeline({ tracks: { video } }, [clipA, clipB]).segments;

  it('lays the raw clips end-to-end (no-duration clips left out)', () => {
    expect(raw).toEqual([
      { clipId: 'c1', label: 'beach.mp4', start: 0, end: 12 },
      { clipId: 'c2', label: 'city.mp4', start: 12, end: 20 },
    ]);
  });

  it('maps each shot to its source range on the raw strip', () => {
    expect(keptRanges(raw, segs)).toEqual([
      { index: 0, clipId: 'c1', rawStart: 3, rawEnd: 5, outStart: 0, outEnd: 2 },
      { index: 1, clipId: 'c2', rawStart: 12, rawEnd: 13.5, outStart: 2, outEnd: 3.5 },
      { index: 2, clipId: 'c1', rawStart: 10, rawEnd: 11, outStart: 3.5, outEnd: 4.5 },
    ]);
    // unknown clip skipped, out point clamped to the clip
    expect(
      keptRanges(raw, [
        { clipId: 'zz', in: 0, out: 1, start: 0, end: 1 },
        { clipId: 'c2', in: 7, out: 30, start: 1, end: 2 },
      ]),
    ).toEqual([{ index: 1, clipId: 'c2', rawStart: 19, rawEnd: 20, outStart: 1, outEnd: 2 }]);
  });

  it('the cut-away parts and the ✂ points', () => {
    const kept = keptRanges(raw, segs);
    expect(cutGaps(raw, kept)).toEqual([
      { start: 0, end: 3 },
      { start: 5, end: 10 },
      { start: 11, end: 12 },
      { start: 13.5, end: 20 },
    ]);
    // 13.5 only: c2 starts at its own beginning (12 = clip edge, not a cut)
    expect(cutPointsOf(raw, kept)).toEqual([3, 5, 10, 11, 13.5]);
    // overlapping / touching shots merge
    const twice = keptRanges(raw, [
      { clipId: 'c1', in: 2, out: 4, start: 0, end: 2 },
      { clipId: 'c1', in: 4, out: 6, start: 2, end: 4 },
    ]);
    expect(cutPointsOf(raw, twice)).toEqual([2, 6]);
    // a clip that is not used at all is not "cut"
    expect(cutGaps(raw, twice)).toEqual([
      { start: 0, end: 2 },
      { start: 6, end: 12 },
    ]);
  });
});

describe('cut animation schedule + effects reveal', () => {
  it('~220 ms per shot, the whole animation within ~4 s however many shots', () => {
    const nine = cutSchedule(9);
    expect(nine.step).toBe(220);
    expect(nine.doneMs).toBeLessThanOrEqual(4000);
    const many = cutSchedule(60);
    expect(many.step).toBeLessThan(220);
    expect(many.doneMs).toBeLessThanOrEqual(4000);
    expect(cutSchedule(0).doneMs).toBe(0);
    expect(cutSchedule(1).step).toBe(0);
    // blocks pop in order, after their slide started
    expect(shotPopAt(nine, 1)).toBeGreaterThan(shotPopAt(nine, 0));
    expect(shotPopAt(nine, 0)).toBeGreaterThan(nine.highlightMs);
    expect(shotPopAt(nine, 8)).toBeLessThan(nine.doneMs);
  });

  it('colour, song, then text / fx by time, one after another after the cut', () => {
    const m = buildLiveStudioTimeline(
      {
        tracks: {
          video,
          text: [{ start: 2, dur: 1, text: 'Goa Trip', kind: 'title' }],
          fx: [
            { start: 3, dur: 0.3, type: 'flash' },
            { start: 0.5, dur: 1, type: 'zoom' },
          ],
          music: [{ start: 0, dur: 4.5, name: 'calm_80bpm.m4a' }],
          color: [{ preset: 'warm', lut: null }],
        },
      },
      [clipA, clipB],
    );
    const r = revealOffsets(m, 1000);
    const order = Object.entries(r)
      .sort((a, b) => a[1] - b[1])
      .map(([k]) => (k === 'color' ? 'color' : k.split('-')[1]));
    expect(order).toEqual(['color', 'music', 'fx', 'text', 'fx']);
    expect(r.color).toBe(1000);
    expect(Math.max(...Object.values(r))).toBe(1000 + 4 * 260);
  });

  it('chip labels', () => {
    expect(fxChipLabel('flash')).toBe('⚡ flash');
    expect(fxChipLabel('zoom')).toBe('✨ zoom');
    expect(songLabel('calm_80bpm.m4a')).toBe('calm_80bpm');
  });
});

describe('buildLiveStudioTimeline live info', () => {
  it('queued, before the cut: raw footage spans the timeline, queue position and ticker', () => {
    const job: Pick<Job, 'status' | 'stage' | 'queue_position'> = { status: 'queued', stage: 'queued', queue_position: 2 };
    const m = buildLiveStudioTimeline({ tracks: {}, thoughts: [] }, [clipA, clipB], job);
    expect(m.total).toBe(20);
    expect(m.segments).toEqual([]);
    expect(m.live).toMatchObject({ phase: 'queued', queuePosition: 2, rawTotal: 20, kept: [], cutPoints: [] });
    expect(m.live?.ticker).toMatch(/^⏳/);
  });

  it('rendering: render progress from the state; total follows the cut', () => {
    const m = buildLiveStudioTimeline(
      { tracks: { video }, thoughts: [], renderStep: { step: 'segment', done: 2, total: 3, text: '' }, stage: 'rendering segment 2/3' },
      [clipA, clipB],
      { ...runningJob, stage: 'rendering segment 2/3' },
    );
    expect(m.total).toBe(4.5);
    expect(m.live?.phase).toBe('rendering');
    expect(m.live?.render.doneCount).toBe(2);
    expect(m.live?.ticker).toBe('🎬 Shot 2/3 ban gaya');
    expect(m.live?.kept).toHaveLength(3);
    expect(m.live?.videoSig).toMatch(/^3:/);
  });
});
