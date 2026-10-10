import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { ApiError, api } from '../src/api/client';
import type { ReferenceInfo } from '../src/api/types';
import { EDIT_LIKE_REFERENCE_PROMPT, ReferencePanel } from '../src/components/studio/ReferencePanel';
import { StudioEditor } from '../src/screens/StudioEditor';
import { emptyMemory, fxCatalog, project, runningJob, screenProps, studioPlan, studioStyles } from './fixtures';

const reference: ReferenceInfo = {
  name: 'their_edit.mp4',
  summary: ['16s 9:16', '18 shots, median 0.67s', '67% of cuts on the beat (92 bpm)', '32% black & white', 'warm', '2 white flash(es)'],
  recipe: { song: 'their_edit_sound.mp3' },
};

describe('ReferencePanel', () => {
  afterEach(() => jest.restoreAllMocks());

  const renderPanel = async (over: Partial<Parameters<typeof ReferencePanel>[0]> = {}) => {
    const onEditLikeReference = jest.fn();
    await render(<ReferencePanel projectId="p1" onEditLikeReference={onEditLikeReference} {...over} />);
    return { onEditLikeReference };
  };

  it('shows the upload button when there is no reference yet', async () => {
    jest.spyOn(api, 'getReference').mockResolvedValue(null);
    await renderPanel();
    expect(await screen.findByTestId('reference-upload')).toBeTruthy();
    expect(screen.getByText('Edit like a video')).toBeTruthy();
    expect(screen.getByText(/Upload reference video/)).toBeTruthy();
    expect(screen.queryByTestId('reference-summary')).toBeNull();
    expect(screen.queryByTestId('reference-edit')).toBeNull();
  });

  it('uploads the picked video and shows its summary; "Edit my video like this" calls the prop', async () => {
    jest.spyOn(api, 'getReference').mockResolvedValue(null);
    const file = { uri: '', name: 'their_edit.mp4', type: 'video/mp4', file: new Blob(['x'], { type: 'video/mp4' }) };
    const upload = jest.spyOn(api, 'uploadReference').mockResolvedValue(reference);
    const { onEditLikeReference } = await renderPanel({ pickFile: async () => file });
    await fireEvent.press(await screen.findByTestId('reference-upload'));
    await waitFor(() => expect(upload).toHaveBeenCalledWith('p1', file));
    expect(await screen.findByTestId('reference-summary')).toBeTruthy();
    expect(screen.getByText(/their_edit\.mp4/)).toBeTruthy();
    for (const line of reference.summary) expect(screen.getByText(line)).toBeTruthy();
    expect(screen.getByText(/their_edit_sound\.mp3/)).toBeTruthy();
    await fireEvent.press(screen.getByTestId('reference-edit'));
    expect(onEditLikeReference).toHaveBeenCalledTimes(1);
  });

  it('shows the upload error', async () => {
    jest.spyOn(api, 'getReference').mockResolvedValue(null);
    jest.spyOn(api, 'uploadReference').mockRejectedValue(new ApiError('unsupported_file', 'Unsupported file type', 415));
    await renderPanel({ pickFile: async () => ({ uri: '', name: 'x.txt', type: 'text/plain' }) });
    await fireEvent.press(await screen.findByTestId('reference-upload'));
    expect(await screen.findByText(/Upload failed: Unsupported file type/)).toBeTruthy();
  });

  it('remove deletes the reference and shows the upload button again', async () => {
    jest.spyOn(api, 'getReference').mockResolvedValue(reference);
    const del = jest.spyOn(api, 'deleteReference').mockResolvedValue({ ok: true });
    await renderPanel();
    await fireEvent.press(await screen.findByTestId('reference-remove'));
    await waitFor(() => expect(del).toHaveBeenCalledWith('p1'));
    await waitFor(() => expect(screen.queryByTestId('reference-summary')).toBeNull());
    expect(screen.getByText(/Upload reference video/)).toBeTruthy();
  });

  it('on native (no picker) explains that the reference is uploaded from the web app', async () => {
    jest.spyOn(api, 'getReference').mockResolvedValue(null);
    const upload = jest.spyOn(api, 'uploadReference');
    await renderPanel();
    await fireEvent.press(await screen.findByTestId('reference-upload'));
    expect(screen.getByText(/Upload from the web app for now/)).toBeTruthy();
    expect(upload).not.toHaveBeenCalled();
  });
});

describe('getReference', () => {
  afterEach(() => jest.restoreAllMocks());

  it('returns null on 404 no_reference', async () => {
    jest.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ error: { code: 'no_reference', message: 'No reference video' } }),
    } as unknown as Response);
    await expect(api.getReference('p1')).resolves.toBeNull();
  });
});

describe('Edit like a video in the studio', () => {
  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockResolvedValue(studioPlan);
    jest.spyOn(api, 'getJob').mockResolvedValue({ ...runningJob, events: [] });
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [0.1, 0.5], duration: 12 });
    jest.spyOn(api, 'listStyles').mockResolvedValue({ styles: studioStyles });
    jest.spyOn(api, 'getProjectMemory').mockResolvedValue(emptyMemory);
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    jest.spyOn(api, 'getPrompts').mockResolvedValue({ prompts: [], genres: [], platforms: [], skills: 0 });
    jest.spyOn(api, 'getReference').mockResolvedValue(reference);
    jest.spyOn(api, 'understand').mockRejectedValue(new Error('offline'));
  });
  afterEach(() => jest.restoreAllMocks());

  it('"Edit my video like this" starts an AI edit with the reference prompt and shows it in the chat', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j9', status: 'queued' });
    const props = screenProps({ projectId: 'p1' });
    await render(<StudioEditor {...(props as unknown as Parameters<typeof StudioEditor>[0])} />);
    await screen.findByTestId('studio-editor');
    await fireEvent.press(screen.getByTestId('rail-more'));
    expect(screen.getByTestId('templates-panel')).toBeTruthy();
    await fireEvent.press(await screen.findByTestId('reference-edit'));
    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', { prompt: EDIT_LIKE_REFERENCE_PROMPT }));
    expect(EDIT_LIKE_REFERENCE_PROMPT).toBe('is reference video jaisa mera video edit karo');
    expect(await screen.findByText(EDIT_LIKE_REFERENCE_PROMPT)).toBeTruthy();
  });
});
