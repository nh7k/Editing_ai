import { act, fireEvent, render, screen } from '@testing-library/react-native';

import { api } from '../src/api/client';
import { StudioEditor } from '../src/screens/StudioEditor';
import { emptyMemory, fxCatalog, project, screenProps, studioPlan, studioStyles, variationsJob } from './fixtures';

// a player that can tell the screen it stopped (as the real one does when a new version loads, or the browser pauses)
const mockListeners: ((p: { isPlaying: boolean }) => void)[] = [];
const mockPlayer = {
  play: jest.fn(),
  pause: jest.fn(),
  seekBy: jest.fn(),
  currentTime: 2,
  loop: false,
  addListener: (_event: string, cb: (p: { isPlaying: boolean }) => void) => {
    mockListeners.push(cb);
    return { remove: () => mockListeners.splice(mockListeners.indexOf(cb), 1) };
  },
};
jest.mock('expo-video', () => {
  const { View } = require('react-native');
  return {
    useVideoPlayer: () => mockPlayer,
    VideoView: (props: Record<string, unknown>) => require('react').createElement(View, { ...props, testID: 'video-view' }),
  };
});

type Props = Parameters<typeof StudioEditor>[0];

describe('Play button follows the real player', () => {
  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockResolvedValue(studioPlan);
    jest.spyOn(api, 'getJob').mockResolvedValue(variationsJob);
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [0.1, 0.5], duration: 12 });
    jest.spyOn(api, 'listStyles').mockResolvedValue({ styles: studioStyles });
    jest.spyOn(api, 'getProjectMemory').mockResolvedValue(emptyMemory);
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
  });
  afterEach(() => jest.restoreAllMocks());

  it('shows Play again when the player stops on its own (it used to stay on Pause, frozen at 00:02)', async () => {
    const props = screenProps({ projectId: 'p1' });
    await render(<StudioEditor {...(props as unknown as Props)} />);
    await screen.findByTestId('studio-editor');
    await fireEvent.press(screen.getByLabelText('Play'));
    expect(mockPlayer.play).toHaveBeenCalled();
    expect(screen.getByLabelText('Pause')).toBeTruthy();
    await act(async () => mockListeners.forEach((cb) => cb({ isPlaying: false })));
    expect(screen.getByLabelText('Play')).toBeTruthy();
  });
});
