import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { api } from '../src/api/client';
import type { Template, TemplatesResponse } from '../src/api/types';
import { TemplatesScreen, filterTemplates, gridColumns, templateMeta } from '../src/screens/TemplatesScreen';
import { DEFAULT_BASE_URL } from '../src/store/settings';
import { project } from './fixtures';

// first render in a cold worker can be slow when the whole suite runs in parallel
jest.setTimeout(60_000);

type Props = Parameters<typeof TemplatesScreen>[0];

const velocity: Template = {
  id: 'tpl_velocity', name: 'Velocity Fan Edit', category: 'Sports', kind: 'builtin',
  description: 'Fast beat cuts, stutters, B&W flashes, big name titles', tags: ['fast', 'beat'],
  prompt: 'brief', duration: 15, aspect: '9:16', colors: ['#0b0b0b', '#e8e8e8'], preview_url: '/templates/tpl_velocity/preview',
};
const travel: Template = { ...velocity, id: 'tpl_travel', name: 'Travel Diary', category: 'Travel', description: 'Calm cuts', tags: ['calm'] };
const mine: Template = { ...velocity, id: 'tpl_mine1', name: 'My liked edit', category: 'Mine', kind: 'mine', description: 'From Copy an Edit' };
const gallery: TemplatesResponse = { templates: [velocity, travel, mine], categories: ['Sports', 'Travel'] };

function props(params?: { projectId?: string; projectName?: string }, state?: object) {
  const navigation = {
    navigate: jest.fn(),
    setOptions: jest.fn(),
    addListener: jest.fn(() => () => undefined),
    popTo: jest.fn(),
    replace: jest.fn(),
    getState: () => state,
  };
  return { navigation, route: { key: 't', name: 'Templates', params } };
}

async function renderScreen(p: ReturnType<typeof props>) {
  await render(<TemplatesScreen {...(p as unknown as Props)} />);
  return p;
}

describe('TemplatesScreen', () => {
  beforeEach(() => {
    jest.spyOn(api, 'listTemplates').mockResolvedValue(gallery);
    jest.spyOn(api, 'listProjects').mockResolvedValue([project, { ...project, id: 'p2', name: 'Tokyo nights' }]);
  });
  afterEach(() => jest.restoreAllMocks());

  it('shows the gallery with All / categories / Mine filters', async () => {
    await renderScreen(props());
    expect(await screen.findByTestId('template-card-tpl_velocity')).toBeTruthy();
    expect(screen.getByText('Velocity Fan Edit')).toBeTruthy();
    expect(screen.getByText('Fast beat cuts, stutters, B&W flashes, big name titles')).toBeTruthy();
    expect(screen.getAllByText('#fast').length).toBeGreaterThan(0);
    expect(screen.getByText('Sports · 15s · 9:16')).toBeTruthy();
    expect(screen.getByLabelText('Velocity Fan Edit preview').props.source).toEqual({
      uri: `${DEFAULT_BASE_URL}/templates/tpl_velocity/preview`,
    });
    for (const id of ['all', 'sports', 'travel', 'mine']) expect(screen.getByTestId(`template-filter-${id}`)).toBeTruthy();

    await fireEvent.press(screen.getByTestId('template-filter-travel'));
    expect(screen.getByTestId('template-card-tpl_travel')).toBeTruthy();
    expect(screen.queryByTestId('template-card-tpl_velocity')).toBeNull();

    await fireEvent.press(screen.getByTestId('template-filter-mine'));
    expect(screen.getByTestId('template-card-tpl_mine1')).toBeTruthy();
    expect(screen.queryByTestId('template-card-tpl_travel')).toBeNull();
  });

  it('card → details → use → choose project + extra prompt → apply → editor with the job (from the tab)', async () => {
    const apply = jest.spyOn(api, 'applyTemplate').mockResolvedValue({ job_id: 'j77', status: 'queued' });
    const p = await renderScreen(props(undefined, { type: 'tab', index: 1, routes: [{ name: 'Projects' }, { name: 'Templates' }] }));
    await fireEvent.press(await screen.findByTestId('template-card-tpl_velocity'));
    expect(screen.getByTestId('template-sheet')).toBeTruthy();
    expect(screen.getByTestId('template-description').props.children).toBe(velocity.description);
    expect(screen.queryByTestId('template-delete')).toBeNull();

    await fireEvent.press(screen.getByTestId('template-use'));
    await fireEvent.press(await screen.findByTestId('template-project-p2'));
    await fireEvent.changeText(screen.getByTestId('template-extra-prompt'), 'mera naam title me');
    await fireEvent.press(screen.getByTestId('template-apply'));

    await waitFor(() => expect(apply).toHaveBeenCalledWith('p2', 'tpl_velocity', 'mera naam title me'));
    expect(p.navigation.navigate).toHaveBeenCalledWith('Editor', {
      projectId: 'p2', projectName: 'Tokyo nights', jobId: 'j77', jobLabel: '▤ Template: Velocity Fan Edit',
    });
  });

  it('opened from the editor: the project is preselected and the editor below gets the job', async () => {
    const apply = jest.spyOn(api, 'applyTemplate').mockResolvedValue({ job_id: 'j78', status: 'queued' });
    const p = await renderScreen(
      props({ projectId: 'p1', projectName: 'Lisbon reel' }, {
        type: 'stack', index: 2,
        routes: [{ name: 'Tabs' }, { name: 'Editor', params: { projectId: 'p1' } }, { name: 'TemplatesGallery' }],
      }),
    );
    expect(await screen.findByTestId('templates-for-project')).toBeTruthy();
    await fireEvent.press(await screen.findByTestId('template-card-tpl_travel'));
    await fireEvent.press(screen.getByTestId('template-use'));
    const row = await screen.findByTestId('template-project-p1');
    expect(row.props.accessibilityState).toMatchObject({ selected: true });
    expect(await screen.findByText('Apply on Lisbon reel')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('template-apply'));
    await waitFor(() => expect(apply).toHaveBeenCalledWith('p1', 'tpl_travel', undefined));
    expect(p.navigation.popTo).toHaveBeenCalledWith('Editor', expect.objectContaining({ projectId: 'p1', jobId: 'j78' }), { merge: true });
  });

  it('"Mine" templates can be deleted (asks once more)', async () => {
    const del = jest.spyOn(api, 'deleteTemplate').mockResolvedValue({ deleted: true });
    await renderScreen(props());
    await fireEvent.press(await screen.findByTestId('template-card-tpl_mine1'));
    await fireEvent.press(screen.getByTestId('template-delete'));
    expect(del).not.toHaveBeenCalled();
    expect(screen.getByText('Pakka delete karein?')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('template-delete'));
    await waitFor(() => expect(del).toHaveBeenCalledWith('tpl_mine1'));
    await waitFor(() => expect(screen.queryByTestId('template-card-tpl_mine1')).toBeNull());
  });

  it('helpers', () => {
    expect(filterTemplates(gallery.templates, 'All')).toHaveLength(3);
    expect(filterTemplates(gallery.templates, 'Mine').map((t) => t.id)).toEqual(['tpl_mine1']);
    expect(filterTemplates(gallery.templates, 'Sports').map((t) => t.id)).toEqual(['tpl_velocity']);
    expect(gridColumns(340)).toBe(1);
    expect(gridColumns(360)).toBe(2);
    expect(gridColumns(900)).toBe(4);
    expect(gridColumns(2000)).toBe(4);
    expect(gridColumns(600)).toBe(3);
    expect(templateMeta({ duration: 15, aspect: '9:16' })).toBe('15s · 9:16');
    expect(templateMeta({ duration: null, aspect: null })).toBe('');
  });
});
