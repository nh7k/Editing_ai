import { fireEvent, render, screen } from '@testing-library/react-native';

import type { Job, LiveTimeline } from '../src/api/types';
import { ChatPanel, type ChatTurn } from '../src/components/studio/ChatPanel';
import { LiveProgressCard } from '../src/components/studio/LiveProgressCard';
import { StudioTimeline } from '../src/components/studio/StudioTimeline';
import { DEFAULT_BASE_URL } from '../src/store/settings';
import { buildLiveStudioTimeline, buildStudioTimeline } from '../src/utils/studioTimeline';
import { clipA, clipB, doneJob, runningJob, studioPlan } from './fixtures';

// first render in a cold worker can be slow when the whole suite runs in parallel
jest.setTimeout(60_000);

const tracks: LiveTimeline = {
  video: [
    { clip_id: 'c1', filename: 'a.mp4', start: 0, dur: 4, thumb: '/projects/p1/clips/c1/frame?t=4' },
    { clip_id: 'c2', filename: 'b.mp4', start: 4, dur: 2, thumb: '/projects/p1/clips/c2/frame?t=1' },
  ],
  text: [{ start: 1, dur: 1.5, text: 'RONALDO', kind: 'title' }],
  fx: [{ start: 3, dur: 1, type: 'flash' }],
  music: [{ start: 0, dur: 30, name: 'calm_80bpm.m4a' }],
  color: [{ preset: 'warm', lut: null }],
};

const thoughts = [
  { t: 1, agent: 'Director', text: 'Fast fan edit, about 15 s, 9:16' },
  { t: 2, agent: 'Cutter', text: 'Picked 9 shots of ~4 s from 3 clips' },
];

const liveJob: Job = {
  ...runningJob,
  stage: 'Cutting & arranging clips',
  progress: 40,
  agents: [{ name: 'Cutter', status: 'running', progress: 50, score: null, attempts: 1, message: '' }],
  review: null,
  thoughts,
  timeline: tracks,
};

function timelineProps(model: ReturnType<typeof buildStudioTimeline>) {
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

function widthOf(id: string): number | undefined {
  const style = [screen.getByTestId(id).props.style].flat(5).filter(Boolean) as { width?: number }[];
  return style.reduce<number | undefined>((acc, s) => (s.width !== undefined ? s.width : acc), undefined);
}

describe('StudioTimeline live mode', () => {
  it('draws the live shots (with their frames), text, fx, music, the AI badge and the build cursor', async () => {
    const model = buildLiveStudioTimeline({ tracks }, [clipA, clipB]);
    await render(<StudioTimeline {...timelineProps(model)} />);
    await fireEvent(screen.getByTestId('timeline-view'), 'layout', { nativeEvent: { layout: { width: 600, height: 200 } } });

    expect(screen.getByTestId('timeline-live-badge')).toBeTruthy();
    expect(screen.getByText('AI editing…')).toBeTruthy();
    expect(screen.getByTestId('timeline-live-color')).toBeTruthy();
    expect(screen.getByTestId('build-cursor')).toBeTruthy();
    expect(screen.queryByTestId('playhead')).toBeNull();

    const [s0, s1] = model.segments;
    expect(screen.getByTestId(`live-thumb-${s0.key}`).props.source).toEqual({
      uri: `${DEFAULT_BASE_URL}/projects/p1/clips/c1/frame?t=4`,
    });
    expect(screen.queryByTestId(`filmstrip-${s0.key}`)).toBeNull();
    // 6 s over 600 px → 100 px/s, widths follow each shot's duration
    expect(widthOf(`segment-${s0.key}`)).toBe(400);
    expect(widthOf(`segment-${s1.key}`)).toBe(200);
    expect(screen.getByText('4.0s · beach.mp4')).toBeTruthy();

    expect(screen.getByTestId('live-text-0')).toBeTruthy();
    expect(screen.getByText(/RONALDO/)).toBeTruthy();
    expect(screen.getByText('FX track')).toBeTruthy();
    expect(screen.getByTestId('live-fx-0-0')).toBeTruthy();
    expect(screen.getByText('flash')).toBeTruthy();
    expect(screen.getByText('Music')).toBeTruthy();
    expect(screen.getByTestId('live-music-0')).toBeTruthy();
    expect(screen.getByText('00:06')).toBeTruthy(); // duration follows the live total
  });

  it('a re-cut replaces the main track blocks', async () => {
    const model = buildLiveStudioTimeline({ tracks }, []);
    const { rerender } = await render(<StudioTimeline {...timelineProps(model)} />);
    expect(screen.getAllByTestId(/^segment-/)).toHaveLength(2);
    const recut = buildLiveStudioTimeline({ tracks: { ...tracks, video: [{ clip_id: 'c3', filename: 'c.mp4', start: 0, dur: 3, thumb: null }] } }, []);
    await rerender(<StudioTimeline {...timelineProps(recut)} />);
    expect(screen.getAllByTestId(/^segment-/)).toHaveLength(1);
    expect(screen.getByTestId(`segment-${recut.segments[0].key}`)).toBeTruthy();
  });

  it('shows a cutting hint before the first shot arrives', async () => {
    await render(<StudioTimeline {...timelineProps(buildLiveStudioTimeline({ tracks: {} }, []))} />);
    expect(screen.getByTestId('live-main-empty')).toBeTruthy();
    expect(screen.getByTestId('timeline-live-badge')).toBeTruthy();
  });

  it('plan mode has no live parts', async () => {
    await render(<StudioTimeline {...timelineProps(buildStudioTimeline(studioPlan, [clipA, clipB]))} />);
    await fireEvent(screen.getByTestId('timeline-view'), 'layout', { nativeEvent: { layout: { width: 600, height: 200 } } });
    expect(screen.queryByTestId('timeline-live-badge')).toBeNull();
    expect(screen.queryByTestId('build-cursor')).toBeNull();
    expect(screen.queryByTestId('live-fx-track-0')).toBeNull();
    expect(screen.getByTestId('playhead')).toBeTruthy();
  });
});

function chatProps(turns: ChatTurn[], running: boolean) {
  return {
    turns,
    running,
    onSend: jest.fn(),
    threeVariations: false,
    onToggleThree: jest.fn(),
    onNewChat: jest.fn(),
    onAttach: jest.fn(),
    playingVariant: null,
    onPlayVariant: jest.fn(),
    onChosen: jest.fn(),
  };
}

describe('ChatPanel agent thoughts', () => {
  it('lists the thoughts one by one with agent chips and a typing indicator while the job runs', async () => {
    await render(<ChatPanel {...chatProps([{ key: 't1', prompt: 'mast edit', job: liveJob }], true)} />);
    expect(screen.getByTestId('chat-thoughts')).toBeTruthy();
    expect(screen.getByText('Fast fan edit, about 15 s, 9:16')).toBeTruthy();
    expect(screen.getByText('Picked 9 shots of ~4 s from 3 clips')).toBeTruthy();
    expect(screen.getByText('director')).toBeTruthy();
    expect(screen.getAllByText('cutter').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId('chat-thought-typing')).toBeTruthy();
    // the step list stays
    expect(screen.getByTestId('step-Cutter')).toBeTruthy();
    expect(screen.queryByTestId('chat-thoughts-toggle')).toBeNull();
  });

  it('appends thoughts from streamed events passed with the turn', async () => {
    const job: Job = { ...liveJob, thoughts: [] };
    const { rerender } = await render(<ChatPanel {...chatProps([{ key: 't1', prompt: 'x', job, events: [] }], true)} />);
    expect(screen.getByText('Agents tayyar ho rahe hain')).toBeTruthy();
    await rerender(
      <ChatPanel
        {...chatProps([{ key: 't1', prompt: 'x', job, events: [{ seq: 1, t: 0.5, type: 'thought', agent: 'Audio', text: 'Song: calm_80bpm' }] }], true)}
      />,
    );
    expect(screen.getByText('Song: calm_80bpm')).toBeTruthy();
    expect(screen.getByText('audio')).toBeTruthy();
  });

  it('folds the thoughts under "Agent ne kya socha (N)" once the job is done (also for older turns)', async () => {
    await render(
      <ChatPanel
        {...chatProps(
          [
            { key: 'old', prompt: 'pehla', job: { ...doneJob, id: 'j0', thoughts } },
            { key: 'new', prompt: 'doosra', job: { ...doneJob, thoughts: [] } },
          ],
          false,
        )}
      />,
    );
    expect(screen.getAllByTestId('chat-thoughts-toggle')).toHaveLength(1);
    expect(screen.getByText(/Agent ne kya socha \(2\)/)).toBeTruthy();
    expect(screen.queryByText('Fast fan edit, about 15 s, 9:16')).toBeNull();
    expect(screen.queryByTestId('chat-thought-typing')).toBeNull();
    await fireEvent.press(screen.getByTestId('chat-thoughts-toggle'));
    expect(screen.getByText('Fast fan edit, about 15 s, 9:16')).toBeTruthy();
  });
});

describe('LiveProgressCard', () => {
  it('shows the stage, percent and colour chip', async () => {
    await render(<LiveProgressCard job={liveJob} look="warm" />);
    expect(screen.getByText('Agent edit kar raha hai')).toBeTruthy();
    expect(screen.getByTestId('live-card-stage').props.children).toBe('Cutting & arranging clips');
    expect(screen.getByText('40%')).toBeTruthy();
    expect(screen.getByText('Colour: warm')).toBeTruthy();
  });

  it('queued jobs show their place in line', async () => {
    await render(<LiveProgressCard job={{ ...liveJob, status: 'queued', queue_position: 2 }} look={null} />);
    expect(screen.getByTestId('live-card-stage').props.children).toBe('Line me hai · 2 edit aage');
    expect(screen.getByText('Colour: —')).toBeTruthy();
  });
});

describe('ChatPanel: an unclear request is never a dead end', () => {
  const choices = [
    { id: 'restore_normal', label: 'Yaha ka effect hata ke normal karo (grade hatega)', calls: [{ id: 'restore_normal' }] },
    { id: 'flash', label: '4.3s par white flash (0.3 sec)', calls: [{ id: 'flash', time: { mode: 'at_time', at: 4.3 } }] },
  ];
  it('shows the readings as chips (best guess first, starred) and a tap sends that choice', async () => {
    const props = { ...chatProps([{ key: 't1', prompt: 'yaha screen white kar do nomal jasia tha', job: null, error: 'ek se zyada matlab', choices }], false), onPickChoice: jest.fn() };
    await render(<ChatPanel {...props} />);
    expect(screen.getByTestId('agent-choices')).toBeTruthy();
    expect(screen.getByText(/★ Yaha ka effect hata ke normal karo/)).toBeTruthy();
    await fireEvent.press(screen.getByTestId('agent-choice-1'));
    expect(props.onPickChoice).toHaveBeenCalledWith('t1', choices[1]);
  });
  it('says what it did when the reading was applied directly', async () => {
    await render(<ChatPanel {...chatProps([{ key: 't1', prompt: 'is jagah flash', job: null, did: '1.0s par white flash (0.3 sec)' }], false)} />);
    expect(screen.getByText(/Kiya: 1.0s par white flash/)).toBeTruthy();
  });
});

describe('ChatPanel: act, show, undo', () => {
  const alts = [{ id: 'flash', label: '4.3s par white flash (0.3 sec)', calls: [{ id: 'flash' }] }];
  it('shows what was done and the other readings as one-tap chips', async () => {
    const props = { ...chatProps([{ key: 't1', prompt: 'yaha screen white kar do nomal jasia tha', job: null, did: 'Maine ye kiya: Yaha ka effect hata ke normal karo', choices: alts, choiceMode: 'replace' as const }], false), onPickChoice: jest.fn() };
    await render(<ChatPanel {...props} />);
    expect(screen.getByText(/Maine ye kiya: Yaha ka effect hata ke normal karo/)).toBeTruthy();
    expect(screen.getByText('Ya ye chahiye tha?')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('agent-alt-0'));
    expect(props.onPickChoice).toHaveBeenCalledWith('t1', alts[0]);
  });
  it('lists the parts not done as chips that add to the edit', async () => {
    await render(<ChatPanel {...chatProps([{ key: 't1', prompt: 'warm, vignette aur chehra jawan', job: null, did: 'Kiya: warm + vignette', choices: alts, choiceMode: 'add' as const }], false)} />);
    expect(screen.getByText('Ye nahi hua — chahiye to tap karo:')).toBeTruthy();
  });
  it('answers a greeting as a message, not an error', async () => {
    await render(<ChatPanel {...chatProps([{ key: 't1', prompt: 'hello bhai', job: null, reply: '🙏 Main aapki video edit karta hoon' }], false)} />);
    expect(screen.getByTestId('agent-reply')).toBeTruthy();
    expect(screen.queryByTestId('agent-error')).toBeNull();
  });
});
