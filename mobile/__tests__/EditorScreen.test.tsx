import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { api, ApiError } from '../src/api/client';
import { FEATURE_PROMPTS, QUICK_PROMPTS } from '../src/components/ChatInput';
import { EditorScreen } from '../src/screens/EditorScreen';
import { project, runningJob, screenProps } from './fixtures';

type Props = Parameters<typeof EditorScreen>[0];

async function renderEditor() {
  const props = screenProps({ projectId: 'p1' });
  await render(<EditorScreen {...(props as unknown as Props)} />);
  return props;
}

describe('Editor chat input', () => {
  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockRejectedValue(new ApiError('plan_not_found', 'No plan yet', 404));
    jest.spyOn(api, 'getJob').mockResolvedValue(runningJob);
  });
  afterEach(() => jest.restoreAllMocks());

  it('fills the input when a quick-prompt chip is pressed', async () => {
    await renderEditor();
    await screen.findByTestId('prompt-input');

    await fireEvent.press(screen.getByText(QUICK_PROMPTS[1]));
    expect(screen.getByTestId('prompt-input').props.value).toBe('Trim to 15s');

    await fireEvent.press(screen.getByText(QUICK_PROMPTS[0]));
    expect(screen.getByTestId('prompt-input').props.value).toBe(QUICK_PROMPTS[0]);
  });

  it('keeps the classic chips and adds feature chips that fill the input with parseable prompts', async () => {
    await renderEditor();
    await screen.findByTestId('prompt-input');

    for (const p of QUICK_PROMPTS) expect(screen.getByText(p)).toBeTruthy();

    const expected: [string, string][] = [
      ['✨ Auto edit', 'mast sa edit kar do'],
      ['Arrange clips', 'arrange the clips in the right order'],
      ['Rotate 90° & mirror', 'rotate 90 and mirror it'],
      ['Play backwards', 'play the video backwards'],
      ['Sepia + vignette', 'sepia color with vignette'],
      ['Mute + calm music', 'mute the sound and add calm music'],
      ['Remove idle parts', 'remove idle parts'],
      ['Export GIF & MP3', 'export gif and mp3'],
      ['Louder + sharpen', 'make it louder and sharpen'],
    ];
    expect(FEATURE_PROMPTS.map((c) => [c.label, c.prompt])).toEqual(expected);
    for (const [label, prompt] of expected) {
      await fireEvent.press(screen.getByText(label));
      expect(screen.getByTestId('prompt-input').props.value).toBe(prompt);
    }
  });

  it('sends a feature chip prompt to the backend', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j1', status: 'queued' });
    await renderEditor();
    await screen.findByTestId('prompt-input');

    await fireEvent.press(screen.getByText('Export GIF & MP3'));
    await fireEvent.press(screen.getByTestId('send-button'));
    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'export gif and mp3' }));
  });

  it('sends the prompt via api.startEdit, shows the live view, and the agent activity sheet stays reachable', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j1', status: 'queued' });
    await renderEditor();
    await screen.findByTestId('prompt-input');

    await fireEvent.press(screen.getByText('Add captions'));
    await fireEvent.press(screen.getByTestId('send-button'));

    await waitFor(() => expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'Add captions' }));
    // the live view takes the main area while the job runs (instead of the preview / plan timeline)
    expect(await screen.findByTestId('live-edit-view')).toBeTruthy();
    expect(screen.queryByTestId('timeline')).toBeNull();
    await fireEvent.press(screen.getByTestId('live-open-activity'));
    expect(await screen.findByText('Agent Activity')).toBeTruthy();
    expect(await screen.findByTestId('agent-Cutter')).toBeTruthy();
  });

  it('picks up a job started elsewhere (route param jobId) and shows its live view', async () => {
    const props = screenProps({ projectId: 'p1', jobId: 'j9' });
    await render(<EditorScreen {...(props as unknown as Props)} />);
    expect(await screen.findByTestId('live-edit-view')).toBeTruthy();
    await waitFor(() => expect(api.getJob).toHaveBeenCalledWith('j9'));
  });

  it('opens Copy an Edit and the template gallery for this project', async () => {
    const { navigation } = await renderEditor();
    await fireEvent.press(await screen.findByTestId('editor-copy-edit'));
    expect(navigation.navigate).toHaveBeenCalledWith('CopyEdit', { projectId: 'p1', projectName: 'Lisbon reel' });
    await fireEvent.press(screen.getByTestId('editor-templates'));
    expect(navigation.navigate).toHaveBeenCalledWith('TemplatesGallery', { projectId: 'p1', projectName: 'Lisbon reel' });
  });

  it('shows the backend error when starting the edit fails', async () => {
    jest.spyOn(api, 'startEdit').mockRejectedValue(new ApiError('no_clips', 'Upload clips first', 400));
    await renderEditor();
    await screen.findByTestId('prompt-input');

    await fireEvent.changeText(screen.getByTestId('prompt-input'), 'Remove silence');
    await fireEvent.press(screen.getByTestId('send-button'));
    expect(await screen.findByText('Upload clips first')).toBeTruthy();
  });

  it('shows the voice placeholder message', async () => {
    await renderEditor();
    await screen.findByTestId('prompt-input');
    await fireEvent.press(screen.getByTestId('mic-button'));
    expect(screen.getByText('Voice input coming soon')).toBeTruthy();
  });

  it('renders the timeline from clip durations when no plan exists', async () => {
    await renderEditor();
    expect(await screen.findByTestId('timeline')).toBeTruthy();
    expect(screen.getByText('beach.mp4')).toBeTruthy();
    expect(screen.getByText('city.mp4')).toBeTruthy();
  });
});
