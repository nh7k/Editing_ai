import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { ApiError, api } from '../src/api/client';
import { StudioEditor } from '../src/screens/StudioEditor';
import { saveVideo, shareVideo } from '../src/utils/media';
import { emptyMemory, fxCatalog, project, projectMemory, runningJob, screenProps, studioPlan, studioStyles, variationsJob } from './fixtures';

jest.mock('../src/utils/media', () => ({
  saveVideo: jest.fn(async () => ({ message: 'Download started.' })),
  shareVideo: jest.fn(async () => ({ message: 'Link copied to clipboard.' })),
}));

type Props = Parameters<typeof StudioEditor>[0];

async function renderStudio() {
  const props = screenProps({ projectId: 'p1' });
  await render(<StudioEditor {...(props as unknown as Props)} />);
  await screen.findByTestId('studio-editor');
  return props;
}

describe('StudioEditor', () => {
  let getJob: jest.SpyInstance;

  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockResolvedValue(studioPlan);
    getJob = jest.spyOn(api, 'getJob').mockResolvedValue(variationsJob);
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [0.1, 0.5, 0.9, 0.4], duration: 12 });
    jest.spyOn(api, 'listStyles').mockResolvedValue({ styles: studioStyles });
    jest.spyOn(api, 'getProjectMemory').mockResolvedValue(emptyMemory);
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    (saveVideo as jest.Mock).mockClear();
    (shareVideo as jest.Mock).mockClear();
  });
  afterEach(() => jest.restoreAllMocks());

  it('renders the top bar, icon rail, media panel, preview, chat and timeline', async () => {
    await renderStudio();
    for (const id of ['studio-topbar', 'icon-rail', 'media-panel', 'preview-stage', 'chat-panel', 'studio-timeline']) {
      expect(screen.getByTestId(id)).toBeTruthy();
    }
    expect(screen.getByText('CutMind')).toBeTruthy();
    expect(screen.getByTestId('studio-title').props.children).toBe('Lisbon reel');
    // media grid
    expect(screen.getByTestId('clip-card-c1')).toBeTruthy();
    expect(screen.getByTestId('clip-card-c2')).toBeTruthy();
    expect(screen.getByText('00:12')).toBeTruthy();
    expect(screen.getAllByText('Ready')).toHaveLength(2);
    // rail
    for (const label of ['Media', 'Effects', 'Images', 'Sounds', 'Captions', 'Text', 'Overlays', 'More']) {
      expect(screen.getByTestId(`rail-${label.toLowerCase()}`)).toBeTruthy();
    }
    // overlays section + timeline tracks from the plan
    expect(await screen.findByText('2 overlays')).toBeTruthy();
    expect(screen.getAllByText('On timeline')).toHaveLength(2);
    expect(screen.getAllByTestId('graphic-track')).toHaveLength(2);
    expect(screen.getByText('Graphic track 1')).toBeTruthy();
    expect(screen.getByText('Graphic track 2')).toBeTruthy();
    expect(screen.getByText(/Lisbon$/)).toBeTruthy();
    expect(screen.getByTestId('segment-s0')).toBeTruthy();
    expect(screen.getByTestId('segment-s1')).toBeTruthy();
    expect(screen.getByTestId('video-view')).toBeTruthy();
    expect(api.getWaveform).toHaveBeenCalledWith('p1', 'c1', 200);
    expect(api.getWaveform).toHaveBeenCalledWith('p1', 'c2', 200);
    // never shows another product's name
    expect(screen.queryByText(/Stanley/i)).toBeNull();
  });

  it('lists the variations in the chat and "Use this" calls api.chooseVariant', async () => {
    const choose = jest.spyOn(api, 'chooseVariant').mockResolvedValue({ ok: true, chosen: 1 });
    await renderStudio();
    expect(await screen.findByText('Created 3 versions, ranked best first:')).toBeTruthy();
    expect(screen.getByText('Midnight Drift')).toBeTruthy();
    expect(screen.getByText('Violet Authority')).toBeTruthy();
    expect(screen.getByText('Cyan Kinetic')).toBeTruthy();
    expect(screen.getByText('In use')).toBeTruthy();
    expect(screen.queryByTestId('use-variant-0')).toBeNull();

    await fireEvent.press(screen.getByTestId('use-variant-1'));
    await waitFor(() => expect(choose).toHaveBeenCalledWith('j1', 1));
    await waitFor(() => expect(screen.getByTestId('use-variant-0')).toBeTruthy());
    expect(screen.queryByTestId('use-variant-1')).toBeNull();
  });

  it('clicking a variation previews it', async () => {
    await renderStudio();
    await fireEvent.press(await screen.findByTestId('play-variant-2'));
    expect(await screen.findByText('Previewing: Cyan Kinetic')).toBeTruthy();
  });

  it('shows agent step statuses and the running hint while polling', async () => {
    getJob.mockResolvedValue({
      ...runningJob,
      agents: [...runningJob.agents, { name: 'Captioner', status: 'failed', progress: 0, score: 0, attempts: 1, message: 'No transcript' }],
    });
    await renderStudio();
    expect(await screen.findByTestId('step-Analyzer')).toBeTruthy();
    expect(screen.getByText('✓')).toBeTruthy();
    expect(screen.getByText('No transcript')).toBeTruthy();
    expect(screen.getByText('This edit is still running…')).toBeTruthy();
    expect(screen.getByText('duration check failed')).toBeTruthy();
  });

  it('while a job runs: live edit in the bottom timeline, thoughts in the chat, a progress card over the preview', async () => {
    getJob.mockResolvedValue({
      ...runningJob,
      review: null,
      stage: 'Cutting & arranging clips',
      thoughts: [{ t: 1, agent: 'Cutter', text: 'Picked 2 shots from 2 clips' }],
      timeline: {
        video: [
          { clip_id: 'c1', filename: 'beach.mp4', start: 0, dur: 3, thumb: '/projects/p1/clips/c1/frame?t=1' },
          { clip_id: 'c2', filename: 'city.mp4', start: 3, dur: 2, thumb: null },
        ],
        color: [{ preset: 'warm', lut: null }],
      },
    });
    await renderStudio();
    expect(await screen.findByTestId('timeline-live-badge')).toBeTruthy();
    expect(screen.getByTestId('build-cursor')).toBeTruthy();
    // the old plan's segments / overlays are replaced by the live shots
    expect(screen.queryByTestId('segment-s0')).toBeNull();
    expect(screen.queryAllByTestId('graphic-track')).toHaveLength(0);
    expect(screen.getAllByTestId(/^live-thumb-/)).toHaveLength(1);
    expect(screen.getByText('3.0s · beach.mp4')).toBeTruthy();
    // centre: preview + compact card, no big live view; the side panel stays
    expect(screen.getByTestId('preview-stage')).toBeTruthy();
    expect(screen.getByTestId('live-progress-card')).toBeTruthy();
    expect(screen.getByText('Colour: warm')).toBeTruthy();
    expect(screen.queryByTestId('live-edit-view')).toBeNull();
    expect(screen.getByTestId('media-panel')).toBeTruthy();
    // chat
    expect(screen.getByText('Picked 2 shots from 2 clips')).toBeTruthy();
    expect(screen.getByTestId('chat-thought-typing')).toBeTruthy();
  });

  it('Export dropdown disables formats not in output.extras', async () => {
    await renderStudio();
    await screen.findByText('Created 3 versions, ranked best first:');
    await fireEvent.press(screen.getByTestId('export'));
    expect(screen.getByTestId('export-mp4')).toBeEnabled();
    expect(screen.getByTestId('export-gif')).toBeEnabled();
    expect(screen.getByTestId('export-mp3')).toBeDisabled();

    await fireEvent.press(screen.getByTestId('export-gif'));
    await waitFor(() => expect(saveVideo).toHaveBeenCalled());
    const [url, name] = (saveVideo as jest.Mock).mock.calls[0];
    expect(url).toContain('/projects/p1/output?v=j1');
    expect(url).toContain('format=gif');
    expect(name).toBe('Lisbon_reel.gif');
  });

  it('Share uses the shared helper with the output URL', async () => {
    await renderStudio();
    await fireEvent.press(screen.getByTestId('share-button'));
    await waitFor(() => expect(shareVideo).toHaveBeenCalled());
    expect((shareVideo as jest.Mock).mock.calls[0][0]).toContain('/projects/p1/output');
    expect(await screen.findByText('Link copied to clipboard.')).toBeTruthy();
  });

  it('sends one fast version by default and 3 variations when the chip is on', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j2', status: 'queued' });
    await renderStudio();
    await fireEvent.changeText(screen.getByTestId('studio-prompt'), 'Make it punchy');
    await fireEvent.press(screen.getByTestId('studio-send'));
    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'Make it punchy' }));
    expect(await screen.findByText('Make it punchy')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('variations-toggle'));
    await fireEvent.changeText(screen.getByTestId('studio-prompt'), 'Shorter');
    await fireEvent.press(screen.getByTestId('studio-send'));
    await waitFor(() => expect(startEdit).toHaveBeenLastCalledWith('p1', { prompt: 'Shorter', variations: 3 }));
  });

  it('one-tap chips send a ready-made prompt (auto edit, arrange)', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j2', status: 'queued' });
    await renderStudio();
    await fireEvent.press(screen.getByTestId('one-tap-auto'));
    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'mast sa edit kar do' }));
    await fireEvent.press(screen.getByTestId('one-tap-arrange'));
    await waitFor(() =>
      expect(startEdit).toHaveBeenLastCalledWith('p1', { prompt: 'arrange the clips in the right order' }),
    );
  });

  it('the mic explains that voice input needs the web app on native', async () => {
    const transcribe = jest.spyOn(api, 'transcribeVoice');
    await renderStudio();
    await fireEvent.press(screen.getByTestId('chat-mic'));
    expect((await screen.findByTestId('voice-status')).props.children).toBe('Voice input works in the web app for now.');
    expect(transcribe).not.toHaveBeenCalled();
  });

  it('Overlays rail shows styles; picking one starts an edit with that style', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j3', status: 'queued' });
    await renderStudio();
    await fireEvent.press(screen.getByTestId('rail-overlays'));
    expect(screen.getByTestId('overlays-panel')).toBeTruthy();
    await fireEvent.press(await screen.findByTestId('style-cyan_kinetic'));
    await waitFor(() =>
      expect(startEdit).toHaveBeenCalledWith('p1', expect.objectContaining({ style: 'cyan_kinetic', variations: 1 })),
    );
  });

  it('other rail items show a coming-soon panel', async () => {
    await renderStudio();
    await fireEvent.press(screen.getByTestId('rail-images'));
    expect(screen.getByTestId('coming-soon-panel')).toBeTruthy();
    expect(screen.queryByTestId('media-panel')).toBeNull();
  });

  it('"+" in the media panel opens the clip import flow', async () => {
    const props = await renderStudio();
    await fireEvent.press(screen.getByTestId('media-add'));
    expect(props.navigation.navigate).toHaveBeenCalledWith('Import', { projectId: 'p1', projectName: 'Lisbon reel' });
  });
  it('Effects rail in "Apply now" mode applies the card directly (no AI) and shows it as a turn', async () => {
    const manual = jest.spyOn(api, 'manualEdit').mockResolvedValue({ job_id: 'm1', status: 'queued' });
    const startEdit = jest.spyOn(api, 'startEdit');
    await renderStudio();
    await fireEvent.press(screen.getByTestId('rail-effects'));
    expect(await screen.findByText('112 effects')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('fx-card-glitch'));
    await waitFor(() => expect(manual).toHaveBeenCalledWith('p1', [{ op: 'add_effect', type: 'glitch' }]));
    expect(startEdit).not.toHaveBeenCalled();
    expect(await screen.findByText('⚡ Glitch (applied)')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('fx-tab-color'));
    const look = screen.getAllByTestId(/fx-card-/)[0];
    await fireEvent.press(look);
    await waitFor(() => expect(manual).toHaveBeenLastCalledWith('p1', [expect.objectContaining({ op: 'set_look' })]));
  });

  it('Text rail adds text that follows a person, applied directly', async () => {
    jest.spyOn(api, 'getTextStyles').mockResolvedValue({
      fonts: [{ id: 'anton', family: 'Anton', look: 'tall' }],
      presets: [{ id: 'neon', name: 'Neon Glow', font: 'monoton', color: '#22D3EE', outline_color: '#7C5CFF', box_color: null, uppercase: false }],
      colors: [{ word: 'yellow', hex: '#FFE600' }],
      animations: [{ id: 'spin_in', description: 'spins in' }],
    });
    const manual = jest.spyOn(api, 'manualEdit').mockResolvedValue({ job_id: 'm2', status: 'queued' });
    await renderStudio();
    await fireEvent.press(screen.getByTestId('rail-text'));
    await fireEvent.changeText(await screen.findByTestId('text-input'), 'RIYA');
    await fireEvent.press(screen.getByTestId('preset-neon'));
    await fireEvent.press(screen.getByTestId('anim-spin_in'));
    await fireEvent.press(screen.getByTestId('track-person'));
    await fireEvent.press(screen.getByTestId('text-apply'));
    await waitFor(() => expect(manual).toHaveBeenCalledWith('p1', [
      { op: 'add_text', text: 'RIYA', position: 'top', track: 'person', preset: 'neon', animation: 'spin_in' },
    ]));
  });

  it('More rail lists pro templates; one tap sends the brief', async () => {
    jest.spyOn(api, 'getPrompts').mockResolvedValue({
      prompts: [{ id: 'party_reel', title: '🎉 Party reel', genre: 'party', prompt: 'Party reel for Instagram, 30 seconds', does: 'Beat cuts' }],
      genres: [], platforms: [], skills: 33,
    });
    jest.spyOn(api, 'getReference').mockResolvedValue(null);
    jest.spyOn(api, 'understand').mockRejectedValue(new Error('offline'));
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j9', status: 'queued' });
    await renderStudio();
    await fireEvent.press(screen.getByTestId('rail-more'));
    await fireEvent.press(await screen.findByTestId('template-party_reel'));
    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'Party reel for Instagram, 30 seconds' }));
  });

  it('Effects rail: clicking a card appends the phrase to the chat input, which is then sent', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j4', status: 'queued' });
    await renderStudio();
    await fireEvent.press(screen.getByTestId('rail-effects'));
    expect(screen.getByTestId('effects-panel')).toBeTruthy();
    expect(screen.queryByTestId('media-panel')).toBeNull();
    expect(await screen.findByText('112 effects')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('fx-mode-prompt')); // "add to prompt" instead of applying right away
    await fireEvent.changeText(screen.getByTestId('studio-prompt'), 'Make it punchy');
    await fireEvent.press(screen.getByTestId('fx-card-glitch'));
    expect(screen.getByTestId('studio-prompt').props.value).toBe('Make it punchy, Glitch effect');
    expect(screen.getByTestId('fx-added')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('fx-tab-transition'));
    await fireEvent.press(screen.getByTestId('fx-card-pixelize'));
    expect(screen.getByTestId('studio-prompt').props.value).toBe('Make it punchy, Glitch effect, Pixelize transitions');

    await fireEvent.press(screen.getByTestId('studio-send'));
    await waitFor(() =>
      expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'Make it punchy, Glitch effect, Pixelize transitions' }),
    );
    expect(screen.getByTestId('studio-prompt').props.value).toBe('');
  });

  it('undo asks the backend for the previous version and the chat explains what changed', async () => {
    const restored = { ...variationsJob, id: 'j_undo', variations: [], prompt: 'Undo (back to v1)',
      explain: { summary: 'Back to v1 (warm colour).', warnings: [] } };
    const undo = jest.spyOn(api, 'undo').mockResolvedValue({ job_id: 'j_undo' });
    getJob.mockResolvedValue(restored);
    await renderStudio();
    await fireEvent.press(await screen.findByTestId('topbar-undo'));
    await waitFor(() => expect(undo).toHaveBeenCalledWith('p1'));
    expect(await screen.findByText('↶ Undo')).toBeTruthy();
    expect(await screen.findByText('Back to v1 (warm colour).')).toBeTruthy();
  });

  it('the answer card offers next tweaks (tap = send) and a 👍/👎 rating that trains the taste', async () => {
    const done = { ...variationsJob, id: 'j_card', variations: [], prompt: 'Undo (back to v1)',
      explain: { summary: 'Changed: colour.', warnings: [], suggestions: ['captions laga do', 'thoda fast karo'] } };
    jest.spyOn(api, 'undo').mockResolvedValue({ job_id: 'j_card' });
    getJob.mockResolvedValue(done);
    const feedback = jest.spyOn(api, 'sendFeedback').mockResolvedValue({ ok: true } as never);
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j_next', status: 'queued' });
    await renderStudio();
    await fireEvent.press(await screen.findByTestId('topbar-undo'));
    await fireEvent.press(await screen.findByTestId('agent-suggestion-captions laga do'));
    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', expect.objectContaining({ prompt: 'captions laga do' })));
    await fireEvent.press(screen.getAllByTestId('agent-rate-up')[0]);
    await waitFor(() => expect(feedback).toHaveBeenCalledWith('j_card', { rating: 'up' }));
    expect(await screen.findByTestId('agent-rated')).toBeTruthy();
  });

  it('the message shows at once and a not-understood answer appears in the chat (no silent default edit)', async () => {
    let reject: (e: unknown) => void = () => {};
    jest.spyOn(api, 'startEdit').mockImplementation(() => new Promise((_res, rej) => { reject = rej; }));
    await renderStudio();
    await fireEvent.changeText(screen.getByTestId('studio-prompt'), 'asdf qwerty');
    await fireEvent.press(screen.getByTestId('studio-send'));
    expect(await screen.findByText('asdf qwerty')).toBeTruthy();
    expect(await screen.findByTestId('agent-thinking')).toBeTruthy();
    reject(new ApiError('not_understood', 'Ye samajh nahi aaya: "asdf qwerty". Edit nahi kiya.', 422));
    expect(await screen.findByTestId('agent-error')).toBeTruthy();
    expect(screen.getByText(/Ye samajh nahi aaya/)).toBeTruthy();
    expect(screen.queryByTestId('agent-thinking')).toBeNull();
  });

  it('memory quick chips fill the chat input and memory is fetched for the project', async () => {
    await renderStudio();
    expect(api.getProjectMemory).toHaveBeenCalledWith('p1');
    expect(await screen.findByTestId('memory-card')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('memory-toggle')); // the card starts folded (more room for the chat)
    await fireEvent.press(screen.getByTestId('memory-same-as-before'));
    expect(screen.getByTestId('studio-prompt').props.value).toBe('same as before but ');

    await fireEvent.changeText(screen.getByTestId('studio-prompt'), 'add karaoke captions');
    await fireEvent.press(screen.getByTestId('memory-in-my-style'));
    expect(screen.getByTestId('studio-prompt').props.value).toBe('in my style, add karaoke captions');
  });

  it('refetches memory after a job finishes', async () => {
    getJob.mockResolvedValueOnce(runningJob).mockResolvedValue(variationsJob);
    await renderStudio();
    await screen.findByText('Created 3 versions, ranked best first:', {}, { timeout: 10000 });
    await waitFor(() => expect((api.getProjectMemory as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(2));
  });
  it('shows remembered preferences in the chat panel', async () => {
    (api.getProjectMemory as jest.Mock).mockResolvedValue(projectMemory);
    await renderStudio();
    await fireEvent.press(await screen.findByTestId('memory-toggle'));
    expect(await screen.findByText(projectMemory.summary)).toBeTruthy();
    expect(screen.getByText('★ Violet Authority')).toBeTruthy();
    expect(screen.getByText('Usually 9:16')).toBeTruthy();
    expect(screen.getByTestId('memory-history-h4')).toBeTruthy();
  });

  it('a memory error is shown in the card without breaking the studio', async () => {
    (api.getProjectMemory as jest.Mock)
      .mockReset()
      .mockRejectedValueOnce(new ApiError('project_not_found', 'No such project', 404))
      .mockResolvedValue(emptyMemory);
    getJob.mockResolvedValue({ ...runningJob, status: 'running' });
    await renderStudio();
    await fireEvent.press(await screen.findByTestId('memory-toggle'));
    expect(await screen.findByText('Could not load memory: No such project')).toBeTruthy();
    expect(screen.getByTestId('chat-panel')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('memory-retry'));
    expect(await screen.findByText(/No edits remembered yet/)).toBeTruthy();
  });

  it('Effects panel shows an error state in the studio when /fx fails', async () => {
    (api.getFxCatalog as jest.Mock).mockRejectedValue(new ApiError('http_500', 'Catalog broken', 500));
    await renderStudio();
    await fireEvent.press(screen.getByTestId('rail-effects'));
    expect(await screen.findByText('Could not load effects: Catalog broken')).toBeTruthy();
  });
});
