import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { ApiError, api } from '../src/api/client';
import type { Understood } from '../src/api/types';
import { StudioEditor } from '../src/screens/StudioEditor';
import { emptyMemory, fxCatalog, project, runningJob, screenProps, studioPlan, studioStyles } from './fixtures';

const PROMPT = 'purani film jaisa bana aur jhakaas kar';

const withUnclear: Understood = {
  solid_prompt: 'Make it look like an old film.',
  understood: ['old film look'],
  changed: true,
  auto: false,
  unclear: [
    {
      text: 'jhakaas',
      suggestions: [
        { command: 'Faded film look.', label: 'Faded film look', score: 0.62 },
        { command: 'Add energetic beat cuts.', label: 'Energetic beat cuts', score: 0.41 },
      ],
    },
  ],
};

const plain: Understood = { solid_prompt: 'Faded film look.', understood: ['faded film look'], changed: false, auto: false, unclear: [] };

async function sendPrompt() {
  const props = screenProps({ projectId: 'p1' });
  await render(<StudioEditor {...(props as unknown as Parameters<typeof StudioEditor>[0])} />);
  await screen.findByTestId('studio-editor');
  await fireEvent.changeText(screen.getByTestId('studio-prompt'), PROMPT);
  await fireEvent.press(screen.getByTestId('studio-send'));
  return screen.findByTestId('coach-unclear');
}

describe('Unclear parts of a prompt', () => {
  let startEdit: jest.SpyInstance;
  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockResolvedValue(studioPlan);
    jest.spyOn(api, 'getJob').mockResolvedValue({ ...runningJob, events: [] });
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [0.1, 0.5], duration: 12 });
    jest.spyOn(api, 'listStyles').mockResolvedValue({ styles: studioStyles });
    jest.spyOn(api, 'getProjectMemory').mockResolvedValue(emptyMemory);
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    jest.spyOn(api, 'understand').mockResolvedValueOnce(withUnclear).mockResolvedValue(plain);
    startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j9', status: 'queued' });
  });
  afterEach(() => jest.restoreAllMocks());

  it('lists what was not understood with its guesses and an ignore chip', async () => {
    await sendPrompt();
    expect(screen.getByText('Ye samajh nahi aaya:')).toBeTruthy();
    expect(screen.getByText('“jhakaas”')).toBeTruthy();
    expect(screen.getByTestId('unclear-chip-0-0')).toBeTruthy();
    expect(screen.getByText('Faded film look')).toBeTruthy();
    expect(screen.getByText('Energetic beat cuts')).toBeTruthy();
    expect(screen.getByTestId('unclear-ignore-0')).toBeTruthy();
    expect(screen.getByText('Kuch aur / ignore')).toBeTruthy();
  });

  it('teaches the phrase on tap and can apply the command as a new edit', async () => {
    const teach = jest.spyOn(api, 'teachPhrase').mockResolvedValue({ ok: true, phrase: 'jhakaas', command: 'Faded film look.' });
    await sendPrompt();
    await fireEvent.press(screen.getByTestId('unclear-chip-0-0'));
    expect(teach).toHaveBeenCalledWith('jhakaas', 'Faded film look.');
    expect(await screen.findByTestId('unclear-learned-0')).toBeTruthy();
    expect(screen.getByText('Seekh liya ✓ — agli baar samajh jaunga')).toBeTruthy();
    expect(screen.queryByTestId('unclear-chip-0-0')).toBeNull();

    await fireEvent.press(screen.getByTestId('unclear-apply-0'));
    await waitFor(() => expect(startEdit).toHaveBeenLastCalledWith('p1', { prompt: 'Faded film look.' }));
    expect(startEdit).toHaveBeenCalledTimes(2);
    // the new edit shows up as its own chat bubble
    expect(await screen.findByText('Faded film look.')).toBeTruthy();
  });

  it('hides an item when ignored', async () => {
    const teach = jest.spyOn(api, 'teachPhrase');
    await sendPrompt();
    await fireEvent.press(screen.getByTestId('unclear-ignore-0'));
    expect(screen.queryByText('“jhakaas”')).toBeNull();
    expect(screen.queryByTestId('unclear-chip-0-0')).toBeNull();
    expect(teach).not.toHaveBeenCalled();
  });

  it('shows the error inline when teaching fails', async () => {
    jest.spyOn(api, 'teachPhrase').mockRejectedValue(new ApiError('unknown_command', 'That command is not known', 422));
    await sendPrompt();
    await fireEvent.press(screen.getByTestId('unclear-chip-0-1'));
    expect(await screen.findByTestId('unclear-error-0')).toBeTruthy();
    expect(screen.getByText('That command is not known')).toBeTruthy();
    expect(screen.queryByTestId('unclear-learned-0')).toBeNull();
    // the guesses stay so the user can pick another one
    expect(screen.getByTestId('unclear-chip-0-0')).toBeTruthy();
  });
});
