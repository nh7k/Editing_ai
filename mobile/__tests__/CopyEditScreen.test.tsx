import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { api, ApiError, toCopyEditState } from '../src/api/client';
import type { Blueprint, UploadFile } from '../src/api/types';
import { openEditorWithJob } from '../src/navigation/openEditor';
import { CopyEditScreen, shotBadges } from '../src/screens/CopyEditScreen';
import { DEFAULT_BASE_URL } from '../src/store/settings';
import { screenProps } from './fixtures';

// first render in a cold worker can be slow when the whole suite runs in parallel
jest.setTimeout(60_000);

type Props = Parameters<typeof CopyEditScreen>[0];

const blueprint: Blueprint = {
  name: 'liked.mp4',
  duration: 21.4,
  aspect: '9:16',
  song: 'liked_sound.m4a',
  shots: [
    { start: 0, dur: 1.2, bw: false, flash: false, zoom: false, motion: 0.6, bright: 0.5, text: false },
    { start: 1.2, dur: 0.4, bw: true, flash: true, zoom: false },
    { start: 1.6, dur: 3.1, bw: false, flash: false, zoom: true },
  ],
  summary: ['21s 9:16', '17 shots, 0.4–3.1 s', 'cuts follow its soundtrack (92 bpm)', '2 white flashes'],
  color: { preset: 'warm' },
  thumbs: ['/projects/p1/copy-edit/thumb/0', '/projects/p1/copy-edit/thumb/1', '/projects/p1/copy-edit/thumb/2'],
  texts: [{ start: 1, end: 2.5, text: 'RONALDO', position: 'center', size: 0.12 }],
};
const ready = { status: 'ready' as const, blueprint };

const file: UploadFile = { uri: 'file:///liked.mp4', name: 'liked.mp4', type: 'video/mp4' };

function navWithEditorBelow() {
  const props = screenProps({ projectId: 'p1', projectName: 'Lisbon reel' });
  const navigation = {
    ...props.navigation,
    popTo: jest.fn(),
    replace: jest.fn(),
    getState: () => ({
      type: 'stack',
      index: 2,
      routes: [{ name: 'Tabs' }, { name: 'Editor', params: { projectId: 'p1' } }, { name: 'CopyEdit', params: { projectId: 'p1' } }],
    }),
  };
  return { ...props, navigation };
}

async function renderScreen(props: ReturnType<typeof navWithEditorBelow>, pickFile?: () => Promise<UploadFile | null>) {
  await render(<CopyEditScreen {...(props as unknown as Props)} pickFile={pickFile} />);
  return props;
}

describe('CopyEditScreen', () => {
  afterEach(() => jest.restoreAllMocks());

  it('picks the liked video, polls while the agent watches it (progress + step), then shows the blueprint', async () => {
    const get = jest
      .spyOn(api, 'getCopyEdit')
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ status: 'analyzing', progress: 0.4, step: 'Reading on-screen text…' })
      .mockResolvedValue(ready);
    const upload = jest.spyOn(api, 'uploadCopyEdit').mockResolvedValue({ status: 'analyzing', progress: 0 });
    await renderScreen(navWithEditorBelow(), async () => file);

    await fireEvent.press(await screen.findByTestId('copy-pick'));
    expect(upload).toHaveBeenCalledWith('p1', file, expect.any(Function));
    expect(await screen.findByText('Agent aapka video dekh raha hai…')).toBeTruthy();
    expect(screen.getByText('0%')).toBeTruthy();

    expect(await screen.findByText('Reading on-screen text…', {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.getByText('40%')).toBeTruthy();

    expect(await screen.findByTestId('copy-blueprint', {}, { timeout: 4000 })).toBeTruthy();
    expect(get).toHaveBeenCalledTimes(3);
    expect(screen.queryByTestId('copy-watching')).toBeNull();
    for (const line of blueprint.summary) expect(screen.getByText(line)).toBeTruthy();
    expect(screen.getByTestId('copy-shot-0')).toBeTruthy();
    expect(screen.getByTestId('copy-shot-2')).toBeTruthy();
    expect(screen.getByText('0.4s')).toBeTruthy();
    expect(screen.getByTestId('copy-shot-1-badge-B&W')).toBeTruthy();
    expect(screen.getByTestId('copy-shot-1-badge-Flash')).toBeTruthy();
    expect(screen.getByTestId('copy-shot-2-badge-Zoom')).toBeTruthy();
    expect(screen.queryByTestId('copy-shot-0-badge-B&W')).toBeNull();
    expect(screen.getByLabelText('Shot 1').props.source).toEqual({ uri: `${DEFAULT_BASE_URL}/projects/p1/copy-edit/thumb/0` });
    expect(screen.getByTestId('copy-text-0')).toBeTruthy();
    expect(screen.getByText('RONALDO')).toBeTruthy();
    expect(screen.getByText('0:01–0:03')).toBeTruthy();
    expect(screen.getByTestId('copy-song').props.children).toBe('♫ Gaana: liked_sound.m4a');
  });

  it('shows a failed analysis with a button to try another video', async () => {
    jest.spyOn(api, 'getCopyEdit').mockResolvedValue({ status: 'failed', error: 'No video stream' });
    await renderScreen(navWithEditorBelow(), async () => file);
    expect(await screen.findByTestId('copy-failed')).toBeTruthy();
    expect(screen.getByText('No video stream')).toBeTruthy();
    expect(screen.getByTestId('copy-pick')).toBeTruthy();
  });

  it('toCopyEditState normalises the responses (and a bare blueprint counts as ready)', () => {
    expect(toCopyEditState({ status: 'analyzing', progress: 0.3, step: 'x' })).toEqual({ status: 'analyzing', progress: 0.3, step: 'x' });
    expect(toCopyEditState({ status: 'analyzing' })).toEqual({ status: 'analyzing', progress: 0, step: null });
    expect(toCopyEditState(ready)).toEqual(ready);
    expect(toCopyEditState(blueprint)).toEqual(ready);
    expect(toCopyEditState({ status: 'failed', error: 'bad' })).toEqual({ status: 'failed', error: 'bad' });
  });

  it('shows an existing blueprint directly; run sends the extra prompt and returns to the editor with the job', async () => {
    jest.spyOn(api, 'getCopyEdit').mockResolvedValue(ready);
    const run = jest.spyOn(api, 'runCopyEdit').mockResolvedValue({ job_id: 'j42', status: 'queued' });
    const props = await renderScreen(navWithEditorBelow());

    expect(await screen.findByTestId('copy-blueprint')).toBeTruthy();
    expect(screen.getByTestId('copy-replace')).toBeTruthy();
    expect(screen.queryByTestId('copy-pick')).toBeNull();

    await fireEvent.changeText(screen.getByTestId('copy-extra-prompt'), ' captions bhi laga ');
    await fireEvent.press(screen.getByTestId('copy-run'));
    await waitFor(() => expect(run).toHaveBeenCalledWith('p1', { prompt: 'captions bhi laga', keep_sound: true }));
    expect(props.navigation.popTo).toHaveBeenCalledWith(
      'Editor',
      expect.objectContaining({ projectId: 'p1', jobId: 'j42' }),
      { merge: true },
    );
  });

  it('keep-sound toggle is sent as keep_sound: false', async () => {
    jest.spyOn(api, 'getCopyEdit').mockResolvedValue(ready);
    const run = jest.spyOn(api, 'runCopyEdit').mockResolvedValue({ job_id: 'j42', status: 'queued' });
    await renderScreen(navWithEditorBelow());
    await fireEvent.press(await screen.findByTestId('copy-keep-sound'));
    await fireEvent.press(screen.getByTestId('copy-run'));
    await waitFor(() => expect(run).toHaveBeenCalledWith('p1', { keep_sound: false }));
  });

  it('saves the blueprint as my template under the given name', async () => {
    jest.spyOn(api, 'getCopyEdit').mockResolvedValue(ready);
    const save = jest.spyOn(api, 'saveCopyEditTemplate').mockResolvedValue({
      id: 'tpl_mine1', name: 'My liked edit', category: 'Mine', kind: 'mine', description: '', tags: [], prompt: '',
      duration: 21, aspect: '9:16', colors: [], preview_url: '/templates/tpl_mine1/preview',
    });
    await renderScreen(navWithEditorBelow());
    await fireEvent.press(await screen.findByTestId('copy-save-template'));
    await fireEvent.changeText(screen.getByTestId('copy-template-name'), 'My liked edit');
    await fireEvent.press(screen.getByTestId('copy-template-save'));
    await waitFor(() => expect(save).toHaveBeenCalledWith('p1', 'My liked edit'));
    expect(await screen.findByTestId('copy-template-saved')).toBeTruthy();
  });

  it('shows the upload / analysis error', async () => {
    jest.spyOn(api, 'getCopyEdit').mockResolvedValue(null);
    jest.spyOn(api, 'uploadCopyEdit').mockRejectedValue(new ApiError('unsupported_file', 'Unsupported file type', 415));
    await renderScreen(navWithEditorBelow(), async () => file);
    await fireEvent.press(await screen.findByTestId('copy-pick'));
    expect(await screen.findByText(/Unsupported file type/)).toBeTruthy();
    expect(screen.getByTestId('copy-pick')).toBeTruthy();
  });

  it('shotBadges', () => {
    expect(shotBadges({ start: 0, dur: 1, bw: true, flash: true, zoom: true })).toEqual(['B&W', 'Flash', 'Zoom']);
    expect(shotBadges({ start: 0, dur: 1, bw: false, flash: false, zoom: false })).toEqual([]);
  });
});

describe('openEditorWithJob', () => {
  const params = { projectId: 'p1', jobId: 'j1' };
  it('goes back to the same project editor below', () => {
    const nav = navWithEditorBelow().navigation;
    expect(openEditorWithJob(nav, params)).toBe('popTo');
  });
  it('replaces the stack screen when the editor below is another project (or none)', () => {
    const nav = navWithEditorBelow().navigation;
    expect(openEditorWithJob(nav, { ...params, projectId: 'p2' })).toBe('replace');
    expect(nav.replace).toHaveBeenCalledWith('Editor', { ...params, projectId: 'p2' });
  });
  it('pushes from a tab', () => {
    const navigate = jest.fn();
    const nav = { navigate, getState: () => ({ type: 'tab', index: 1, routes: [{ name: 'Projects' }, { name: 'Templates' }] }) };
    expect(openEditorWithJob(nav, params)).toBe('navigate');
    expect(navigate).toHaveBeenCalledWith('Editor', params);
  });
});
