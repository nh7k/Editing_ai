import { act, fireEvent, render, screen } from '@testing-library/react-native';

import type { Job, LiveTimeline, RenderStep } from '../src/api/types';
import { StudioTimeline } from '../src/components/studio/StudioTimeline';
import { DEFAULT_BASE_URL } from '../src/store/settings';
import { buildLiveStudioTimeline } from '../src/utils/studioTimeline';
import { clipA, clipB, runningJob } from './fixtures';

// first render in a cold worker can be slow when the whole suite runs in parallel
jest.setTimeout(60_000);

const video: LiveTimeline['video'] = [
  { clip_id: 'c1', filename: 'beach.mp4', start: 0, dur: 2, in: 3, out: 5, speed: 1, thumb: '/projects/p1/clips/c1/frame?t=4' },
  { clip_id: 'c2', filename: 'city.mp4', start: 2, dur: 1.5, in: 0, out: 1.5, speed: 1, thumb: null },
  { clip_id: 'c1', filename: 'beach.mp4', start: 3.5, dur: 1, in: 10, out: 11, speed: 1, thumb: null },
];
const tracks: LiveTimeline = {
  video,
  text: [{ start: 2, dur: 1, text: 'Goa Trip', kind: 'title' }],
  fx: [{ start: 0.5, dur: 0.3, type: 'flash' }],
  music: [{ start: 0, dur: 4.5, name: 'calm_80bpm.m4a' }],
  color: [{ preset: 'warm', lut: null }],
};
const thoughts = [{ key: 'e1', t: 1, agent: 'cutter', text: 'Picked 3 shots from 2 clips — fast pace asked' }];

function props(model: ReturnType<typeof buildLiveStudioTimeline>) {
  return {
    projectId: 'p1',
    model,
    currentTime: 0,
    duration: model.total,
    playing: false,
    onTogglePlay: jest.fn(),
    onSeek: jest.fn(),
    waveforms: {},
  };
}

async function layout() {
  await fireEvent(screen.getByTestId('timeline-view'), 'layout', { nativeEvent: { layout: { width: 900, height: 200 } } });
}

const job = (stage: string, extra: Partial<Job> = {}): Job => ({ ...runningJob, stage, ...extra });
const step = (s: string, done: number | null = null, total: number | null = null): RenderStep => ({ step: s, done, total, text: '' });

describe('StudioTimeline live states', () => {
  it('queued: raw footage dimmed on Main, queue position and a ticker in the header', async () => {
    const model = buildLiveStudioTimeline({ tracks: {}, thoughts: [] }, [clipA, clipB], job('queued', { status: 'queued', queue_position: 2 }));
    await render(<StudioTimeline {...props(model)} />);
    await layout();

    expect(screen.getByTestId('timeline-queue')).toBeTruthy();
    expect(screen.getByText('Line me hai — 2 edit aage')).toBeTruthy();
    expect(screen.getByTestId('timeline-ticker')).toBeTruthy();
    expect(screen.getByText(/^⏳/)).toBeTruthy();
    expect(screen.getByTestId('live-raw-track')).toBeTruthy();
    expect(screen.getByTestId('live-raw-clip-0')).toBeTruthy();
    expect(screen.getByTestId('live-raw-clip-1')).toBeTruthy();
    expect(screen.getByTestId('live-raw-film-0').props.source).toEqual({
      uri: `${DEFAULT_BASE_URL}/projects/p1/clips/c1/filmstrip?frames=10`,
    });
    expect(screen.getByText('Raw footage · line me')).toBeTruthy();
    expect(screen.queryByTestId('live-main-empty')).toBeNull();
    expect(screen.queryByTestId('live-cut-mark-0')).toBeNull();
    // the ruler spans the raw footage (12 s + 8 s)
    expect(screen.getByText('00:20')).toBeTruthy();
  });

  it('working, before the cut: raw footage, the latest thought in the ticker, no queue chip, the cursor scans', async () => {
    const model = buildLiveStudioTimeline({ tracks: {}, thoughts }, [clipA, clipB], job('analyzing clips'));
    await render(<StudioTimeline {...props(model)} />);
    await layout();
    expect(screen.queryByTestId('timeline-queue')).toBeNull();
    expect(screen.getByText('✂ Picked 3 shots from 2 clips')).toBeTruthy();
    expect(screen.getByText('Raw footage')).toBeTruthy();
    expect(screen.getByTestId('build-cursor').props.accessibilityLabel).toBe('AI watching the raw footage');
  });

  it('cut: kept ranges light up, cut points get ✂, kept pieces slide into the edited blocks; effects get chips', async () => {
    const model = buildLiveStudioTimeline({ tracks, thoughts }, [clipA, clipB], job('effects agent'));
    await render(<StudioTimeline {...props(model)} />);
    await layout();

    for (const i of [0, 1, 2]) {
      expect(screen.getByTestId(`live-kept-${i}`)).toBeTruthy();
      expect(screen.getByTestId(`live-ghost-${i}`)).toBeTruthy();
      expect(screen.getByTestId(`segment-${model.segments[i].key}`)).toBeTruthy();
    }
    // ✂ at 3, 5, 10, 11 (beach) and 13.5 (city)
    expect(screen.getAllByTestId(/^live-cut-mark-/)).toHaveLength(5);
    expect(screen.getAllByTestId(/^live-cut-gap-/)).toHaveLength(4);
    // raw strip is 20 s over 900 px (45 px/s): ✂ 0 sits at 3 s
    const markStyle = [screen.getByTestId('live-cut-mark-0').props.style].flat(5).filter(Boolean) as { left?: number }[];
    expect(markStyle.find((s) => s.left !== undefined)?.left).toBe(3 * 45 - 7);

    // effect chips (decorative, hidden from screen readers)
    const hidden = { includeHiddenElements: true };
    expect(screen.getByTestId('live-chip-fx-0-0', hidden)).toBeTruthy();
    expect(screen.getByText('⚡ flash', hidden)).toBeTruthy();
    expect(screen.getByText('T Goa Trip', hidden)).toBeTruthy();
    expect(screen.getByText('♪ calm_80bpm', hidden)).toBeTruthy();
    expect(screen.getByTestId('timeline-live-color')).toBeTruthy();
    expect(screen.getByText('🎨 warm')).toBeTruthy();
    expect(screen.queryByTestId('live-render-done-0')).toBeNull();
  });

  it('a re-cut replaces the kept ranges, ghosts and blocks (the cut animation replays)', async () => {
    const model = buildLiveStudioTimeline({ tracks, thoughts }, [clipA, clipB], job('cutter agent'));
    const { rerender } = await render(<StudioTimeline {...props(model)} />);
    await layout();
    expect(screen.getAllByTestId(/^live-ghost-/)).toHaveLength(3);
    const recut = buildLiveStudioTimeline(
      { tracks: { ...tracks, video: [{ clip_id: 'c2', filename: 'city.mp4', start: 0, dur: 2, in: 4, out: 6, speed: 1 }] }, thoughts },
      [clipA, clipB],
      job('cutter agent'),
    );
    await rerender(<StudioTimeline {...props(recut)} />);
    expect(screen.getAllByTestId(/^live-ghost-/)).toHaveLength(1);
    expect(screen.getAllByTestId(/^live-kept-/)).toHaveLength(1);
    expect(screen.getAllByTestId(/^live-cut-mark-/)).toHaveLength(2); // 16 and 18 on the raw strip
    expect(screen.getByTestId(`segment-${recut.segments[0].key}`)).toBeTruthy();
  });

  it('rendering: the first `done` shots get ✓, the ticker says which shot is ready', async () => {
    const model = buildLiveStudioTimeline(
      { tracks, thoughts, renderStep: step('segment', 2, 3), stage: 'rendering segment 2/3' },
      [clipA, clipB],
      job('rendering segment 2/3'),
    );
    await render(<StudioTimeline {...props(model)} />);
    await layout();
    expect(screen.getByText('🎬 Shot 2/3 ban gaya')).toBeTruthy();
    expect(screen.getByTestId('live-render-done-0')).toBeTruthy();
    expect(screen.getByTestId('live-render-done-1')).toBeTruthy();
    expect(screen.queryByTestId('live-render-done-2')).toBeNull();
    expect(screen.queryByTestId('timeline-render-shimmer')).toBeNull();
    expect(screen.getByTestId('build-cursor').props.accessibilityLabel).toBe('AI render cursor');
  });

  it('rendering: join → all ✓ + shimmer; reuse → all ✓ with the "cut wahi hai" note', async () => {
    const join = buildLiveStudioTimeline({ tracks, thoughts, renderStep: step('join'), stage: 'joining segments' }, [clipA, clipB], job('joining segments'));
    const { rerender } = await render(<StudioTimeline {...props(join)} />);
    await layout();
    expect(screen.getAllByTestId(/^live-render-done-/)).toHaveLength(3);
    expect(screen.getByTestId('timeline-render-shimmer')).toBeTruthy();
    expect(screen.queryByTestId('live-render-reuse')).toBeNull();

    const reuse = buildLiveStudioTimeline(
      { tracks, thoughts, renderStep: step('reuse'), stage: 'reusing the cut (only text / audio changed)' },
      [clipA, clipB],
      job('reusing the cut (only text / audio changed)'),
    );
    await rerender(<StudioTimeline {...props(reuse)} />);
    expect(screen.getAllByTestId(/^live-render-done-/)).toHaveLength(3);
    expect(screen.getByTestId('live-render-reuse')).toBeTruthy();
    expect(screen.getByText('✓ cut wahi hai, sirf text/gaana')).toBeTruthy();
    // the ticker swaps to the new line on its next tick
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(screen.getByText('🎬 Cut wahi hai, sirf text/gaana')).toBeTruthy();
  });

  it('reviewing: all shots ✓, "Result dekh raha hai", the cursor sweeps the whole timeline', async () => {
    const model = buildLiveStudioTimeline({ tracks, thoughts, stage: 'reviewing' }, [clipA, clipB], job('reviewing'));
    await render(<StudioTimeline {...props(model)} />);
    await layout();
    expect(screen.getByText('👀 Result dekh raha hai')).toBeTruthy();
    expect(screen.getAllByTestId(/^live-render-done-/)).toHaveLength(3);
    expect(screen.getByTestId('build-cursor').props.accessibilityLabel).toBe('AI review sweep');
  });

  it('rendering a styled version (no shot step): cursor sweeps, Main glows, shimmer, the chip names the version', async () => {
    const versionTracks: LiveTimeline = { ...tracks, color: [{ preset: 'none', lut: null, name: 'Violet Authority' }] };
    const stage = 'rendering version 2/3: Violet Authority';
    const model = buildLiveStudioTimeline({ tracks: versionTracks, thoughts, stage }, [clipA, clipB], job(stage));
    await render(<StudioTimeline {...props(model)} />);
    await layout();
    expect(screen.getByTestId('build-cursor').props.accessibilityLabel).toBe('AI render sweep');
    expect(screen.getByTestId('live-main-rendering')).toBeTruthy();
    expect(screen.getByTestId('timeline-render-shimmer')).toBeTruthy();
    expect(screen.getByText('🎨 Violet Authority')).toBeTruthy(); // "none" is not shown as a colour
    expect(screen.getByText('🎬 Version 2/3 ban raha hai: Violet Authority')).toBeTruthy();
  });

  it('agents still deciding: empty Text / FX lanes say who is working; rendering removes those notes', async () => {
    const onlyCut: LiveTimeline = { video, music: tracks.music };
    const working = buildLiveStudioTimeline({ tracks: onlyCut, thoughts }, [clipA, clipB], job('effects agent'));
    const { rerender } = await render(<StudioTimeline {...props(working)} />);
    await layout();
    expect(screen.getByTestId('live-text-working')).toBeTruthy();
    expect(screen.getByTestId('live-fx-working-0')).toBeTruthy();
    expect(screen.getByText('✦  Effects agent kaam kar raha hai…')).toBeTruthy();

    const rendering = buildLiveStudioTimeline({ tracks: onlyCut, thoughts, stage: 'rendering' }, [clipA, clipB], job('rendering'));
    await rerender(<StudioTimeline {...props(rendering)} />);
    expect(screen.queryByTestId('live-text-working')).toBeNull();
    expect(screen.queryByTestId('live-fx-working-0')).toBeNull();
    expect(screen.getByTestId('live-main-rendering')).toBeTruthy();
  });

  it('the ticker animates to new text; a burst of lines is shown one by one', async () => {
    jest.useFakeTimers();
    try {
      const withThoughts = (extra: { agent: string; text: string }[]) =>
        buildLiveStudioTimeline(
          { tracks, thoughts: [...thoughts, ...extra.map((x, i) => ({ key: `x${i}`, t: 2 + i, ...x }))] },
          [clipA, clipB],
          job('effects agent'),
        );
      const { rerender } = await render(<StudioTimeline {...props(withThoughts([]))} />);
      expect(screen.getByText('✂ Picked 3 shots from 2 clips')).toBeTruthy();
      const zoom = { agent: 'effects', text: 'Zoom punch on the drop' };
      const warm = { agent: 'color', text: 'Warm look — beach footage' };
      await rerender(<StudioTimeline {...props(withThoughts([zoom]))} />);
      await rerender(<StudioTimeline {...props(withThoughts([zoom, warm]))} />);
      await act(async () => {
        jest.advanceTimersByTime(50);
      });
      expect(screen.getByText('✨ Zoom punch on the drop')).toBeTruthy();
      // the second line waits its turn instead of replacing the first at once
      expect(screen.queryByText('🎨 Warm look')).toBeNull();
      await act(async () => {
        jest.advanceTimersByTime(1000);
      });
      expect(screen.getByText('🎨 Warm look')).toBeTruthy();
    } finally {
      jest.useRealTimers();
    }
  });
});
