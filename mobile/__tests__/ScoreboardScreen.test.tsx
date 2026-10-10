import { render, screen, within } from '@testing-library/react-native';
import { StyleSheet } from 'react-native';

import { api, ApiError } from '../src/api/client';
import { ScoreboardScreen } from '../src/screens/ScoreboardScreen';
import { colors } from '../src/theme';
import { agents } from './fixtures';

function colorOf(testID: string): unknown {
  return StyleSheet.flatten(screen.getByTestId(testID).props.style).color;
}

describe('ScoreboardScreen', () => {
  afterEach(() => jest.restoreAllMocks());

  it('ranks agents by total points', async () => {
    jest.spyOn(api, 'getScoreboard').mockResolvedValue({ agents });
    await render(<ScoreboardScreen />);

    await screen.findByText('Color');
    expect(within(screen.getByTestId('agent-card-Color')).getByText('#1')).toBeTruthy();
    expect(within(screen.getByTestId('agent-card-Audio')).getByText('#2')).toBeTruthy();
    expect(within(screen.getByTestId('agent-card-Cutter')).getByText('#3')).toBeTruthy();
    expect(screen.getByText('Respect the target duration', { exact: false })).toBeTruthy();
  });

  it('colours positive deltas mint and negative deltas coral', async () => {
    jest.spyOn(api, 'getScoreboard').mockResolvedValue({ agents });
    await render(<ScoreboardScreen />);
    await screen.findByText('Color');

    expect(screen.getByTestId('delta-Color').props.children).toBe('+10');
    expect(colorOf('delta-Color')).toBe(colors.mint);
    expect(screen.getByTestId('delta-Cutter').props.children).toBe('-15');
    expect(colorOf('delta-Cutter')).toBe(colors.coral);
    expect(colorOf('delta-Audio')).toBe(colors.textMuted);
  });

  it('shows an error state when the scoreboard cannot be loaded', async () => {
    jest.spyOn(api, 'getScoreboard').mockRejectedValue(new ApiError('timeout', 'Request timed out after 15s'));
    await render(<ScoreboardScreen />);
    expect(await screen.findByText('Could not load scoreboard')).toBeTruthy();
    expect(screen.getByText('Request timed out after 15s')).toBeTruthy();
  });

  it('shows an empty state when there are no agents', async () => {
    jest.spyOn(api, 'getScoreboard').mockResolvedValue({ agents: [] });
    await render(<ScoreboardScreen />);
    expect(await screen.findByText('No agents yet')).toBeTruthy();
  });
});
