import { fireEvent, render, screen } from '@testing-library/react-native';

import { ApiError, api } from '../src/api/client';
import { EffectsPanel } from '../src/components/studio/EffectsPanel';
import { appendPhrase, fxPhrase, lookColors, prefixPhrase, styleName, totalCount } from '../src/components/studio/fxPhrases';
import { MemoryCard, recentHistory } from '../src/components/studio/MemoryCard';
import { emptyMemory, fxCatalog, projectMemory } from './fixtures';

describe('fx phrase helpers', () => {
  it('builds natural phrases per category', () => {
    const it_ = { id: 'x', name: 'Pan Left', description: '' };
    expect(fxPhrase('motion', it_)).toBe('pan left');
    expect(fxPhrase('video_effect', { ...it_, name: 'Glitch' })).toBe('Glitch effect');
    expect(fxPhrase('transition', { ...it_, name: 'Pixelize' })).toBe('Pixelize transitions');
    expect(fxPhrase('color', { ...it_, name: 'Noir' })).toBe('Noir look');
    expect(fxPhrase('text_animation', { ...it_, name: 'Karaoke' })).toBe('Karaoke captions');
  });

  it('appends to drafts sensibly', () => {
    expect(appendPhrase('', 'glitch effect')).toBe('glitch effect');
    expect(appendPhrase('   ', 'glitch effect')).toBe('glitch effect');
    expect(appendPhrase('make it punchy', 'glitch effect')).toBe('make it punchy, glitch effect');
    expect(appendPhrase('same as before but ', 'glitch effect')).toBe('same as before but glitch effect');
    expect(appendPhrase('in my style,', 'noir look')).toBe('in my style, noir look');
  });

  it('prefixes memory shortcuts once', () => {
    expect(prefixPhrase('', 'same as before but ')).toBe('same as before but ');
    expect(prefixPhrase('  shorter', 'same as before but ')).toBe('same as before but shorter');
    expect(prefixPhrase('same as before but shorter', 'same as before but ')).toBe('same as before but shorter');
  });

  it('maps style ids, look colours and totals', () => {
    expect(styleName('midnight_drift')).toBe('Midnight Drift');
    expect(styleName('violet_authority')).toBe('Violet Authority');
    expect(styleName('cyan_kinetic')).toBe('Cyan Kinetic');
    expect(styleName('new_style')).toBe('New Style');
    expect(lookColors('teal_orange')).toHaveLength(2);
    expect(lookColors('unknown')).toEqual(['#6366F1', '#7C5CFF']);
    expect(totalCount(fxCatalog.counts)).toBe(112);
    expect(totalCount({ total: 7, motion: 3 })).toBe(7);
    expect(totalCount(undefined)).toBe(0);
  });
});

describe('EffectsPanel', () => {
  afterEach(() => jest.restoreAllMocks());

  it('renders tabs with counts and the total', async () => {
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    await render(<EffectsPanel onAddPhrase={jest.fn()} />);
    expect(await screen.findByText('112 effects')).toBeTruthy();
    expect(screen.getByText('Motion 10')).toBeTruthy();
    expect(screen.getByText('Effects 28')).toBeTruthy();
    expect(screen.getByText('Transitions 58')).toBeTruthy();
    expect(screen.getByText('Looks 10')).toBeTruthy();
    expect(screen.getByText('Text anim 6')).toBeTruthy();
    // Effects tab is selected by default
    expect(screen.getByTestId('fx-tab-video_effect')).toBeSelected();
    expect(screen.getByTestId('fx-card-glitch')).toBeTruthy();
    expect(screen.getByText('Digital glitch with RGB tearing')).toBeTruthy();
    expect(screen.queryByTestId('fx-card-pixelize')).toBeNull();
  });

  it('search filters by name and description, with an empty state', async () => {
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    await render(<EffectsPanel onAddPhrase={jest.fn()} />);
    await screen.findByTestId('fx-card-glitch');
    await fireEvent.changeText(screen.getByTestId('fx-search'), 'vhs');
    expect(screen.getByTestId('fx-card-vhs')).toBeTruthy();
    expect(screen.queryByTestId('fx-card-glitch')).toBeNull();
    await fireEvent.changeText(screen.getByTestId('fx-search'), 'analogue');
    expect(screen.getByTestId('fx-card-film_grain')).toBeTruthy();
    expect(screen.queryByTestId('fx-card-vhs')).toBeNull();
    await fireEvent.changeText(screen.getByTestId('fx-search'), 'zzz');
    expect(screen.getByTestId('fx-empty')).toBeTruthy();
    expect(screen.getByText('Nothing matches “zzz”.')).toBeTruthy();
  });

  it('clicking cards sends the natural phrase for each tab and shows "+ added"', async () => {
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    const onAdd = jest.fn();
    await render(<EffectsPanel onAddPhrase={onAdd} />);
    await fireEvent.press(await screen.findByTestId('fx-card-glitch'));
    expect(onAdd).toHaveBeenLastCalledWith('Glitch effect');
    expect(screen.getByText('+ added')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('fx-tab-motion'));
    await fireEvent.press(screen.getByTestId('fx-card-pan_left'));
    expect(onAdd).toHaveBeenLastCalledWith('pan left');

    await fireEvent.press(screen.getByTestId('fx-tab-transition'));
    await fireEvent.press(screen.getByTestId('fx-card-pixelize'));
    expect(onAdd).toHaveBeenLastCalledWith('Pixelize transitions');

    await fireEvent.press(screen.getByTestId('fx-tab-color'));
    expect(screen.getByTestId('fx-swatch-teal_orange')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('fx-card-teal_orange'));
    expect(onAdd).toHaveBeenLastCalledWith('Teal & Orange look');

    await fireEvent.press(screen.getByTestId('fx-tab-text_animation'));
    await fireEvent.press(screen.getByTestId('fx-card-karaoke'));
    expect(onAdd).toHaveBeenLastCalledWith('Karaoke captions');
    expect(onAdd).toHaveBeenCalledTimes(5);
  });

  it('shows a loading state while the catalog is pending', async () => {
    jest.spyOn(api, 'getFxCatalog').mockReturnValue(new Promise(() => undefined));
    await render(<EffectsPanel onAddPhrase={jest.fn()} />);
    expect(screen.getByTestId('fx-loading')).toBeTruthy();
    expect(screen.queryByTestId('fx-total')).toBeNull();
  });

  it('shows an error with retry', async () => {
    const get = jest
      .spyOn(api, 'getFxCatalog')
      .mockRejectedValueOnce(new ApiError('network_error', 'Cannot reach the backend'))
      .mockResolvedValue(fxCatalog);
    await render(<EffectsPanel onAddPhrase={jest.fn()} />);
    expect(await screen.findByTestId('fx-error')).toBeTruthy();
    expect(screen.getByText('Could not load effects: Cannot reach the backend')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('fx-retry'));
    expect(await screen.findByTestId('fx-card-glitch')).toBeTruthy();
    expect(get).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId('fx-error')).toBeNull();
  });

  it('shows an empty state for an empty catalog', async () => {
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue({ catalog: {}, counts: {} });
    await render(<EffectsPanel onAddPhrase={jest.fn()} />);
    expect(await screen.findByTestId('fx-empty')).toBeTruthy();
    expect(screen.getByText('0 effects')).toBeTruthy();
  });
});

describe('MemoryCard', () => {
  it('renders summary, favourite style, look, usual aspect and the last 3 edits newest first', async () => {
    await render(<MemoryCard memory={projectMemory} onQuickPhrase={jest.fn()} />);
    expect(screen.getByTestId('memory-summary').props.children).toBe(projectMemory.summary);
    expect(screen.getByText('★ Violet Authority')).toBeTruthy();
    expect(screen.getByText('Look: Teal Orange')).toBeTruthy();
    expect(screen.getByText('Usually 9:16')).toBeTruthy();
    expect(screen.getByText('4 edits ▴')).toBeTruthy();
    expect(screen.getByTestId('memory-history-h4')).toBeTruthy();
    expect(screen.getByTestId('memory-history-h3')).toBeTruthy();
    expect(screen.getByTestId('memory-history-h2')).toBeTruthy();
    expect(screen.queryByTestId('memory-history-h1')).toBeNull();
    expect(screen.getByText('“newest teal and orange version”')).toBeTruthy();
    expect(screen.getByText('Violet Authority · 0:30')).toBeTruthy();
    expect(screen.getByText('Violet Authority · 0:15 · liked')).toBeTruthy();
    expect(recentHistory(projectMemory.history).map((h) => h.job_id)).toEqual(['h4', 'h3', 'h2']);
  });

  it('quick chips pass their phrases', async () => {
    const onQuick = jest.fn();
    await render(<MemoryCard memory={emptyMemory} onQuickPhrase={onQuick} />);
    await fireEvent.press(screen.getByTestId('memory-same-as-before'));
    expect(onQuick).toHaveBeenLastCalledWith('same as before but ');
    await fireEvent.press(screen.getByTestId('memory-in-my-style'));
    expect(onQuick).toHaveBeenLastCalledWith('in my style, ');
  });

  it('is collapsible and has a friendly empty summary', async () => {
    await render(<MemoryCard memory={emptyMemory} onQuickPhrase={jest.fn()} />);
    expect(screen.getByText(/No edits remembered yet/)).toBeTruthy();
    expect(screen.queryByTestId('memory-fav-style')).toBeNull();
    expect(screen.queryByTestId('memory-history')).toBeNull();
    await fireEvent.press(screen.getByTestId('memory-toggle'));
    expect(screen.queryByTestId('memory-body')).toBeNull();
    await fireEvent.press(screen.getByTestId('memory-toggle'));
    expect(screen.getByTestId('memory-body')).toBeTruthy();
  });

  it('shows loading and error states with retry', async () => {
    const onRetry = jest.fn();
    const view = await render(<MemoryCard loading onQuickPhrase={jest.fn()} />);
    expect(screen.getByText('Loading memory…')).toBeTruthy();
    await view.rerender(<MemoryCard error="No such project" onRetry={onRetry} onQuickPhrase={jest.fn()} />);
    expect(screen.getByTestId('memory-error')).toBeTruthy();
    expect(screen.getByText('Could not load memory: No such project')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('memory-retry'));
    expect(onRetry).toHaveBeenCalled();
    // quick chips still work without memory
    expect(screen.getByTestId('memory-same-as-before')).toBeTruthy();
  });
});

