import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { api } from '../src/api/client';
import type { JobEvent } from '../src/api/types';
import { LiveActivity, activityRows } from '../src/components/studio/LiveActivity';
import { StudioEditor } from '../src/screens/StudioEditor';
import { emptyMemory, fxCatalog, project, runningJob, screenProps, studioPlan, studioStyles } from './fixtures';

let seq = 0;
const ev = (type: string, extra: Partial<JobEvent> = {}): JobEvent => ({ seq: ++seq, t: seq / 10, type, ...extra });

describe('LiveActivity', () => {
  beforeEach(() => {
    seq = 0;
  });

  it('builds rows only from real node events (nothing is shown as running without one)', () => {
    const events = [
      ev('node_started', { node: 'understand' }),
      ev('agents_selected', { agents: [{ id: 'transcriber', name: 'Transcriber', category: 'transcript' }] }),
      ev('node_completed', { node: 'understand', ms: 12 }),
      ev('node_started', { node: 'analyze' }),
    ];
    const rows = activityRows(events);
    expect(rows.find((r) => r.node === 'understand')).toMatchObject({ state: 'done', ms: 12 });
    expect(rows.find((r) => r.node === 'analyze')?.state).toBe('running');
    expect(rows.find((r) => r.node === 'render')?.state).toBe('pending');
    expect(rows.some((r) => r.node === 'fix')).toBe(false); // the fix loop only appears when it really runs
  });

  it('a manual change shows only the steps that really run (no AI steps)', () => {
    const rows = activityRows([ev('node_started', { node: 'apply' }), ev('node_completed', { node: 'apply', ms: 40 }),
      ev('node_started', { node: 'render' })]);
    expect(rows.map((r) => r.node)).toEqual(['apply', 'render', 'review']);
    expect(rows[0].state).toBe('done');
    expect(rows[1].state).toBe('running');
  });

  it('shows retries, the reviewer score, specialists and the log', async () => {
    const events = [
      ev('node_started', { node: 'understand' }),
      ev('agents_selected', { agents: [{ id: 'caption_writer', name: 'Caption Writer', category: 'caption' }] }),
      ev('node_completed', { node: 'understand', ms: 8 }),
      ev('node_started', { node: 'review' }),
      ev('review_completed', { match_percent: 72 }),
      ev('node_completed', { node: 'review', ms: 900 }),
      ev('node_started', { node: 'fix' }),
      ev('node_completed', { node: 'fix', ms: 30 }),
      ev('node_started', { node: 'review' }),
      ev('review_completed', { match_percent: 96 }),
      ev('node_completed', { node: 'review', ms: 1500 }),
      ev('log', { agent: 'cutter', level: 'info', msg: '12 segments, 15.00s' }),
    ];
    await render(<LiveActivity events={events} job={null} />);
    expect(screen.getByText(/Reviewing the result \(×2\)/)).toBeTruthy();
    expect(screen.getByText('match 96%')).toBeTruthy();
    expect(screen.getByText(/Fixing what the reviewer flagged/)).toBeTruthy();
    expect(screen.getByText(/1 specialists picked: Caption Writer/)).toBeTruthy();
    expect(screen.getByText('1.5 s')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('activity-log-toggle'));
    expect(screen.getByText('cutter: 12 segments, 15.00s')).toBeTruthy();
  });
});

describe('Prompt coach in the studio', () => {
  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockResolvedValue(studioPlan);
    jest.spyOn(api, 'getJob').mockResolvedValue({ ...runningJob, events: [] });
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [0.1, 0.5], duration: 12 });
    jest.spyOn(api, 'listStyles').mockResolvedValue({ styles: studioStyles });
    jest.spyOn(api, 'getProjectMemory').mockResolvedValue(emptyMemory);
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
  });
  afterEach(() => jest.restoreAllMocks());

  it('sends the own words of the user and shows "Samajh gaya" with what was understood', async () => {
    jest.spyOn(api, 'understand').mockResolvedValue({
      solid_prompt: 'Zoom in for the first 3 seconds. Zoom out after 3 seconds. Bass boost.',
      understood: ['zoom in for the first 3 seconds', 'zoom out after 3 seconds', 'bass boost + zoom punch on every beat'],
      changed: true,
      auto: false,
    });
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j9', status: 'queued' });
    const props = screenProps({ projectId: 'p1' });
    await render(<StudioEditor {...(props as unknown as Parameters<typeof StudioEditor>[0])} />);
    await screen.findByTestId('studio-editor');
    await fireEvent.changeText(screen.getByTestId('studio-prompt'), 'starting ki 3s me zoom ho phir zoom out, base ki tarah effect');
    await fireEvent.press(screen.getByTestId('studio-send'));
    await waitFor(() =>
      expect(startEdit).toHaveBeenCalledWith('p1', {
        prompt: 'starting ki 3s me zoom ho phir zoom out, base ki tarah effect',
      }),
    );
    expect(await screen.findByText(/English prompt: Zoom in for the first 3 seconds/)).toBeTruthy();
    expect(await screen.findByTestId('coach-card')).toBeTruthy();
    expect(screen.getByText(/Samajh gaya/)).toBeTruthy();
    expect(screen.getByText('• bass boost + zoom punch on every beat')).toBeTruthy();
    // the user's own words stay visible in their bubble
    expect(screen.getByText('starting ki 3s me zoom ho phir zoom out, base ki tarah effect')).toBeTruthy();
  });

  it('falls back to the original words when the coach is unreachable', async () => {
    jest.spyOn(api, 'understand').mockRejectedValue(new Error('offline'));
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j9', status: 'queued' });
    const props = screenProps({ projectId: 'p1' });
    await render(<StudioEditor {...(props as unknown as Parameters<typeof StudioEditor>[0])} />);
    await screen.findByTestId('studio-editor');
    await fireEvent.changeText(screen.getByTestId('studio-prompt'), 'mast sa edit kar do');
    await fireEvent.press(screen.getByTestId('studio-send'));
    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'mast sa edit kar do' }));
    expect(screen.queryByTestId('coach-card')).toBeNull();
  });
});
