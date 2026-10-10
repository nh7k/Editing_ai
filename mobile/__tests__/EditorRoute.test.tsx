import { act, render, screen } from '@testing-library/react-native';
import { Dimensions } from 'react-native';

import { api, ApiError } from '../src/api/client';
import { EditorRoute } from '../src/screens/EditorRoute';
import { project, runningJob, screenProps } from './fixtures';

type Props = Parameters<typeof EditorRoute>[0];

async function setWindowWidth(width: number) {
  const dims = { width, height: 900, scale: 1, fontScale: 1 };
  await act(async () => {
    Dimensions.set({ window: dims, screen: dims });
  });
}

describe('EditorRoute', () => {
  const original = Dimensions.get('window');

  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockRejectedValue(new ApiError('plan_not_found', 'No plan yet', 404));
    jest.spyOn(api, 'getJob').mockResolvedValue(runningJob);
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [], duration: 0 });
  });
  afterEach(async () => {
    await setWindowWidth(original.width);
    jest.restoreAllMocks();
  });

  it('renders the existing mobile EditorScreen on narrow windows', async () => {
    await setWindowWidth(400);
    const props = screenProps({ projectId: 'p1' });
    await render(<EditorRoute {...(props as unknown as Props)} />);
    expect(await screen.findByTestId('prompt-input')).toBeTruthy();
    expect(screen.queryByTestId('studio-editor')).toBeNull();
    expect(props.navigation.setOptions).toHaveBeenCalledWith({ headerShown: true });
  });

  it('renders the studio on windows at least 1024px wide', async () => {
    await setWindowWidth(1440);
    const props = screenProps({ projectId: 'p1' });
    await render(<EditorRoute {...(props as unknown as Props)} />);
    expect(await screen.findByTestId('studio-editor')).toBeTruthy();
    expect(screen.queryByTestId('prompt-input')).toBeNull();
    expect(props.navigation.setOptions).toHaveBeenCalledWith({ headerShown: false });
  });
});
