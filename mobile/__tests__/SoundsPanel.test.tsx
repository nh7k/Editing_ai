import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { api } from '../src/api/client';
import type { SongsResponse, TextStylesResponse } from '../src/api/types';
import { SoundsPanel } from '../src/components/studio/SoundsPanel';
import { TextPanel } from '../src/components/studio/TextPanel';
import { EDIT_TO_SONG_PROMPT, StudioEditor } from '../src/screens/StudioEditor';
import { emptyMemory, fxCatalog, project, runningJob, screenProps, studioPlan, studioStyles } from './fixtures';

const songs: SongsResponse = {
  selected: 'mine.mp3',
  project: [{ name: 'mine.mp3', source: 'project', selected: true, duration: 61, tempo: 92, feel: 'medium', drop: 10.8 }],
  library: [{ name: 'chill.mp3', source: 'library', selected: false, duration: 40, tempo: 70.4, feel: 'slow', drop: null }],
};

const textStyles: TextStylesResponse = {
  fonts: [{ id: 'inter', family: 'Inter', look: 'clean' }],
  presets: [],
  colors: [],
  animations: [],
};

describe('SoundsPanel', () => {
  beforeEach(() => {
    jest.spyOn(api, 'listSongs').mockResolvedValue(songs);
  });
  afterEach(() => jest.restoreAllMocks());

  const renderPanel = async (over: Partial<Parameters<typeof SoundsPanel>[0]> = {}) => {
    const onApply = jest.fn();
    const onEditToSong = jest.fn();
    const utils = await render(
      <SoundsPanel projectId="p1" hasPlan audio={{ music: 'mine.mp3', music_volume: 0.25, voice_volume: 1, mute: false }}
        onApply={onApply} onEditToSong={onEditToSong} {...over} />,
    );
    return { onApply, onEditToSong, utils };
  };

  it('lists your songs and the library with feel, tempo and drop', async () => {
    await renderPanel();
    expect(await screen.findByTestId('song-mine.mp3')).toBeTruthy();
    expect(screen.getByTestId('song-chill.mp3')).toBeTruthy();
    expect(screen.getByText('medium')).toBeTruthy();
    expect(screen.getByText('slow')).toBeTruthy();
    expect(screen.getByText(/92 bpm · drop at 10\.8s/)).toBeTruthy();
    expect(screen.getByText(/70 bpm/)).toBeTruthy();
    expect(screen.getByText('✓ In use')).toBeTruthy();
    // library songs can't be deleted
    expect(screen.getByTestId('song-delete-mine.mp3')).toBeTruthy();
    expect(screen.queryByTestId('song-delete-chill.mp3')).toBeNull();
    // current values of the edit are highlighted
    expect(screen.getByTestId('music-vol-25').props.accessibilityState.selected).toBe(true);
    expect(screen.getByTestId('voice-vol-100').props.accessibilityState.selected).toBe(true);
  });

  it('"Use" selects the song and "Edit to this beat" asks for an AI edit', async () => {
    const select = jest.spyOn(api, 'selectSong').mockResolvedValue({ selected: 'chill.mp3' });
    const { onEditToSong } = await renderPanel();
    await fireEvent.press(await screen.findByTestId('song-use-chill.mp3'));
    await waitFor(() => expect(select).toHaveBeenCalledWith('p1', 'chill.mp3'));
    await fireEvent.press(screen.getByTestId('song-edit-chill.mp3'));
    expect(onEditToSong).toHaveBeenCalledWith('chill.mp3');
  });

  it('mute toggle, volume steps, remove and "use here" send set_audio ops', async () => {
    const { onApply } = await renderPanel();
    await screen.findByTestId('song-mine.mp3');
    await fireEvent.press(screen.getByTestId('audio-mute-toggle'));
    expect(onApply).toHaveBeenLastCalledWith([{ op: 'set_audio', mute: true }], expect.any(String));
    await fireEvent.press(screen.getByTestId('music-vol-75'));
    expect(onApply).toHaveBeenLastCalledWith([{ op: 'set_audio', music_volume: 0.75 }], expect.any(String));
    await fireEvent.press(screen.getByTestId('voice-vol-150'));
    expect(onApply).toHaveBeenLastCalledWith([{ op: 'set_audio', voice_volume: 1.5 }], expect.any(String));
    await fireEvent.press(screen.getByTestId('audio-remove-song'));
    expect(onApply).toHaveBeenLastCalledWith([{ op: 'set_audio', no_music: true }], expect.any(String));
    await fireEvent.press(screen.getByTestId('song-here-chill.mp3'));
    expect(onApply).toHaveBeenLastCalledWith([{ op: 'set_audio', music: 'chill.mp3' }], expect.any(String));
  });

  it('hides the edit controls when there is no plan yet', async () => {
    await renderPanel({ hasPlan: false, audio: null });
    await screen.findByTestId('song-mine.mp3');
    expect(screen.queryByTestId('audio-mute-toggle')).toBeNull();
    expect(screen.queryByTestId('song-here-mine.mp3')).toBeNull();
  });

  it('uploads the picked file and refreshes the list', async () => {
    const blob = new Blob(['x'], { type: 'audio/mpeg' });
    const file = { uri: '', name: 'new.mp3', type: 'audio/mpeg', file: blob };
    const upload = jest.spyOn(api, 'uploadSong').mockResolvedValue({ name: 'new.mp3', source: 'project', selected: true });
    await renderPanel({ pickFile: async () => file });
    await screen.findByTestId('song-mine.mp3');
    await fireEvent.press(screen.getByTestId('sounds-upload'));
    await waitFor(() => expect(upload).toHaveBeenCalledWith('p1', file));
    expect(await screen.findByText(/“new\.mp3” added and selected/)).toBeTruthy();
    expect(api.listSongs).toHaveBeenCalledTimes(2);
  });

  it('shows the upload error', async () => {
    jest.spyOn(api, 'uploadSong').mockRejectedValue(new Error('unsupported_file'));
    await renderPanel({ pickFile: async () => ({ uri: '', name: 'x.txt', type: 'text/plain' }) });
    await screen.findByTestId('song-mine.mp3');
    await fireEvent.press(screen.getByTestId('sounds-upload'));
    expect(await screen.findByText(/Upload failed: unsupported_file/)).toBeTruthy();
  });

  it('on native (no picker) explains that songs are uploaded from the web app', async () => {
    const upload = jest.spyOn(api, 'uploadSong');
    await renderPanel();
    await screen.findByTestId('song-mine.mp3');
    await fireEvent.press(screen.getByTestId('sounds-upload'));
    expect(screen.getByText(/Upload songs from the web app for now/)).toBeTruthy();
    expect(upload).not.toHaveBeenCalled();
  });
});

describe('Sounds in the studio', () => {
  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockResolvedValue({ ...studioPlan, audio: { music: null, music_volume: 0.5, mute: true } });
    jest.spyOn(api, 'getJob').mockResolvedValue({ ...runningJob, events: [] });
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [0.1, 0.5], duration: 12 });
    jest.spyOn(api, 'listStyles').mockResolvedValue({ styles: studioStyles });
    jest.spyOn(api, 'getProjectMemory').mockResolvedValue(emptyMemory);
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    jest.spyOn(api, 'listSongs').mockResolvedValue(songs);
    jest.spyOn(api, 'understand').mockRejectedValue(new Error('offline'));
  });
  afterEach(() => jest.restoreAllMocks());

  it('"Edit to this beat" starts an AI edit with the song; mute goes through the manual endpoint', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j9', status: 'queued' });
    const manualEdit = jest.spyOn(api, 'manualEdit').mockResolvedValue({ job_id: 'j10', status: 'queued' });
    const props = screenProps({ projectId: 'p1' });
    await render(<StudioEditor {...(props as unknown as Parameters<typeof StudioEditor>[0])} />);
    await screen.findByTestId('studio-editor');
    await fireEvent.press(screen.getByLabelText('Sounds'));
    await fireEvent.press(await screen.findByTestId('song-edit-mine.mp3'));
    await waitFor(() =>
      expect(startEdit).toHaveBeenCalledWith('p1', { prompt: EDIT_TO_SONG_PROMPT, music_track: 'mine.mp3' }),
    );
    // plan has mute: true → the toggle turns the original sound back on
    await fireEvent.press(await screen.findByTestId('audio-mute-toggle'));
    await waitFor(() => expect(manualEdit).toHaveBeenCalledWith('p1', [{ op: 'set_audio', mute: false }]));
  });
});

describe('TextPanel "Behind person"', () => {
  beforeEach(() => {
    jest.spyOn(api, 'getTextStyles').mockResolvedValue(textStyles);
  });
  afterEach(() => jest.restoreAllMocks());

  it('sends behind: true with add_text', async () => {
    const onApply = jest.fn();
    await render(<TextPanel mode="text" onApply={onApply} />);
    await fireEvent.changeText(await screen.findByTestId('text-input'), 'GOA');
    await fireEvent.press(screen.getByTestId('text-behind-toggle'));
    expect(screen.getByTestId('text-behind-toggle').props.accessibilityState.checked).toBe(true);
    await fireEvent.press(screen.getByTestId('text-apply'));
    expect(onApply).toHaveBeenCalledWith(
      [{ op: 'add_text', text: 'GOA', position: 'top', track: 'none', behind: true }],
      expect.stringContaining('behind the person'),
    );
  });

  it('updates a selected text of the edit with behind', async () => {
    const onApply = jest.fn();
    await render(<TextPanel mode="text" onApply={onApply} texts={studioPlan.text} />);
    await fireEvent.press(await screen.findByTestId('text-item-0'));
    expect(screen.queryByTestId('text-item-1')).toBeNull(); // captions are not listed
    await fireEvent.press(screen.getByTestId('text-behind-toggle'));
    await fireEvent.press(screen.getByTestId('text-apply'));
    expect(onApply).toHaveBeenCalledWith([{ op: 'update_text', index: 0, behind: true }], expect.any(String));
  });
});
