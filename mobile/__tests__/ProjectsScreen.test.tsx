import { fireEvent, render, screen } from '@testing-library/react-native';

import { api, ApiError } from '../src/api/client';
import { ProjectsScreen } from '../src/screens/ProjectsScreen';
import { project, screenProps } from './fixtures';

type Props = Parameters<typeof ProjectsScreen>[0];

async function renderScreen() {
  const props = screenProps(undefined as never);
  await render(<ProjectsScreen {...(props as unknown as Props)} />);
  return props;
}

describe('ProjectsScreen', () => {
  afterEach(() => jest.restoreAllMocks());

  it('renders the project list', async () => {
    jest.spyOn(api, 'listProjects').mockResolvedValue([project, { ...project, id: 'p2', name: 'Tokyo nights', clips: [], has_output: false }]);
    const { navigation } = await renderScreen();

    expect(await screen.findByText('Lisbon reel')).toBeTruthy();
    expect(screen.getByText('Tokyo nights')).toBeTruthy();
    expect(screen.getByText('Rendered')).toBeTruthy();
    expect(screen.getByText('Draft')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('open-p1'));
    expect(navigation.navigate).toHaveBeenCalledWith('Editor', { projectId: 'p1', projectName: 'Lisbon reel' });
  });

  it('shows the empty state when there are no projects', async () => {
    jest.spyOn(api, 'listProjects').mockResolvedValue([]);
    await renderScreen();
    expect(await screen.findByText('No projects yet')).toBeTruthy();
    expect(screen.getByTestId('empty-state')).toBeTruthy();
  });

  it('shows the error state and retries', async () => {
    const spy = jest
      .spyOn(api, 'listProjects')
      .mockRejectedValueOnce(new ApiError('network_error', 'Cannot reach the backend'))
      .mockResolvedValueOnce([project]);
    await renderScreen();

    expect(await screen.findByText('Could not load projects')).toBeTruthy();
    expect(screen.getByText('Cannot reach the backend')).toBeTruthy();

    await fireEvent.press(screen.getByText('Try again'));
    expect(await screen.findByText('Lisbon reel')).toBeTruthy();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it('creates a project and opens the import screen', async () => {
    jest.spyOn(api, 'listProjects').mockResolvedValue([]);
    const create = jest.spyOn(api, 'createProject').mockResolvedValue({ ...project, id: 'p9', name: 'New one', clips: [] });
    const { navigation } = await renderScreen();

    await screen.findByText('No projects yet');
    await fireEvent.changeText(screen.getByTestId('project-name-input'), '  New one ');
    await fireEvent.press(screen.getByTestId('create-project'));

    expect(await screen.findByText('New one')).toBeTruthy();
    expect(create).toHaveBeenCalledWith('New one');
    expect(navigation.navigate).toHaveBeenCalledWith('Import', { projectId: 'p9', projectName: 'New one' });
  });
});
