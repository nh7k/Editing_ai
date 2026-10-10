import { fireEvent, render, screen } from '@testing-library/react-native';

import type { Job } from '../src/api/types';
import { LiveEditView, LiveTracks } from '../src/components/LiveEditView';
import { DEFAULT_BASE_URL } from '../src/store/settings';
import { doneJob, runningJob } from './fixtures';

// first render in a cold worker can be slow when the whole suite runs in parallel
jest.setTimeout(60_000);

const liveJob: Job = {
  ...runningJob,
  stage: 'Cutting & arranging clips',
  progress: 40,
  agents: [{ name: 'Cutter', status: 'running', progress: 50, score: null, attempts: 1, message: '' }],
  thoughts: [
    { t: 1, agent: 'Director', text: 'Fast fan edit, about 15 s, 9:16' },
    { t: 2, agent: 'Audio', text: 'Song: calm_80bpm, drop at 6.2 s' },
  ],
  timeline: {
    video: [
      { clip_id: 'c1', filename: 'a.mp4', start: 0, dur: 4, thumb: '/projects/p1/clips/c1/frame?t=14.3' },
      { clip_id: 'c2', filename: 'b.mp4', start: 4, dur: 2, thumb: '/projects/p1/clips/c2/frame?t=1' },
    ],
    text: [{ start: 1, dur: 1.5, text: 'RONALDO', kind: 'title' }],
    music: [{ start: 0, dur: 30, name: 'calm_80bpm.m4a' }],
    color: [{ preset: 'warm', lut: null }],
  },
};

describe('LiveEditView', () => {
  it('shows the thoughts, the progress, the working agent and the multi-track timeline from the polled job', async () => {
    const onOpen = jest.fn();
    await render(<LiveEditView jobId="j1" job={liveJob} onOpenActivity={onOpen} />);
    expect(screen.getByTestId('live-edit-view')).toBeTruthy();
    expect(screen.getByText('Fast fan edit, about 15 s, 9:16')).toBeTruthy();
    expect(screen.getByText('Song: calm_80bpm, drop at 6.2 s')).toBeTruthy();
    expect(screen.getByTestId('live-stage').props.children).toBe('Cutting & arranging clips');
    expect(screen.getByText('40%')).toBeTruthy();
    // typing indicator on the running agent
    expect(screen.getByTestId('live-typing')).toBeTruthy();
    expect(screen.getByText('kaam kar raha hai')).toBeTruthy();
    // tracks
    for (const t of ['video', 'text', 'fx', 'music']) expect(screen.getByTestId(`live-track-${t}`)).toBeTruthy();
    expect(screen.getByTestId('live-block-video-0')).toBeTruthy();
    expect(screen.getByTestId('live-block-video-1')).toBeTruthy();
    expect(screen.getByTestId('live-thumb-0').props.source).toEqual({ uri: `${DEFAULT_BASE_URL}/projects/p1/clips/c1/frame?t=14.3` });
    expect(screen.getByText('RONALDO')).toBeTruthy();
    expect(screen.getByText('Colour: warm')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('live-open-activity'));
    expect(onOpen).toHaveBeenCalled();
  });

  it('video block widths are proportional to dur', async () => {
    await render(<LiveTracks tracks={liveJob.timeline!} initialWidth={56 + 12 + 600} />);
    const w = (id: string) => {
      const style = [screen.getByTestId(id).props.style].flat(5).filter(Boolean) as { width?: number }[];
      return style.reduce<number | undefined>((acc, s) => (s.width !== undefined ? s.width : acc), undefined);
    };
    // 6 s of video over 600 px → 100 px/s
    expect(w('live-block-video-0')).toBe(400);
    expect(w('live-block-video-1')).toBe(200);
  });

  it('applies timeline / thought events as they arrive; a later event replaces the track', async () => {
    const base: Job = { ...liveJob, timeline: {}, thoughts: [], events: [] };
    const { rerender } = await render(<LiveEditView jobId="j1" job={base} />);
    expect(screen.getByTestId('live-feed-empty')).toBeTruthy();

    const withEvents: Job = {
      ...base,
      events: [
        { seq: 1, t: 0.5, type: 'thought', agent: 'Cutter', text: 'Picked 9 shots of ~4 s from 3 clips' },
        { seq: 2, t: 0.9, type: 'timeline', track: 'video', items: liveJob.timeline!.video },
      ],
    };
    await rerender(<LiveEditView jobId="j1" job={withEvents} />);
    expect(screen.getByText('Picked 9 shots of ~4 s from 3 clips')).toBeTruthy();
    expect(screen.getByTestId('live-block-video-1')).toBeTruthy();

    const recut: Job = {
      ...withEvents,
      events: [
        ...withEvents.events!,
        { seq: 3, t: 2, type: 'timeline', track: 'video', items: [{ clip_id: 'c3', filename: 'c.mp4', start: 0, dur: 3, thumb: null }] },
      ],
    };
    await rerender(<LiveEditView jobId="j1" job={recut} />);
    expect(screen.getByTestId('live-block-video-0')).toBeTruthy();
    expect(screen.queryByTestId('live-block-video-1')).toBeNull();
  });

  it('shows no typing indicator once the job is finished', async () => {
    await render(<LiveEditView jobId="j1" job={{ ...doneJob, thoughts: liveJob.thoughts }} />);
    expect(screen.queryByTestId('live-typing')).toBeNull();
  });
});
