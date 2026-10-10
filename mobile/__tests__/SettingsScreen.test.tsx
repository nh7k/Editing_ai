import { act, fireEvent, render, screen } from '@testing-library/react-native';

import { api } from '../src/api/client';
import type { Health } from '../src/api/types';
import { SettingsScreen } from '../src/screens/SettingsScreen';
import { getApiKey, setApiKey } from '../src/store/settings';
import { colors } from '../src/theme';

// Exact shape the real backend returns from GET /health.
const health = (llm: Health['llm'], over: Partial<Health> = {}): Health => ({
  status: 'ok',
  version: '0.2.0',
  planner_mode: llm.available === null ? 'mock' : 'local',
  ffmpeg: true,
  whisper: true,
  auth_required: false,
  llm,
  ...over,
});

async function testConnection(h: Health) {
  jest.spyOn(api, 'healthAt').mockResolvedValue(h);
  await render(<SettingsScreen />);
  await fireEvent.press(screen.getByText('Test connection'));
  expect(await screen.findByText('CONNECTED')).toBeTruthy();
}

describe('SettingsScreen', () => {
  afterEach(async () => {
    jest.restoreAllMocks();
    // The screen is still mounted and subscribed to the store.
    await act(async () => {
      await setApiKey('');
    });
  });

  it('renders the health result in mock mode (rules only)', async () => {
    await testConnection(health({ model: null, available: null }));
    expect(screen.getByText('AI model')).toBeTruthy();
    expect(screen.getByText('rules only (mock planner)')).toHaveStyle({ color: colors.mint });
    expect(screen.getByText('auth')).toBeTruthy();
    expect(screen.getByText('off')).toBeTruthy();
  });

  it('shows the model as ready when it is cached', async () => {
    await testConnection(
      health({ model: 'onnx-community/Qwen2.5-1.5B-Instruct', file: 'onnx/model_q4.onnx', available: true }),
    );
    expect(screen.getByText('ready · onnx-community/Qwen2.5-1.5B-Instruct')).toHaveStyle({ color: colors.mint });
  });

  it('warns while the model is downloading / not cached', async () => {
    await testConnection(health({ model: 'onnx-community/Qwen2.5-1.5B-Instruct', available: false }));
    expect(screen.getByText('downloading / not cached · onnx-community/Qwen2.5-1.5B-Instruct')).toHaveStyle({
      color: colors.coral,
    });
  });

  it('shows auth: required and prompts for a key when none is set', async () => {
    await testConnection(health({ model: null, available: null }, { auth_required: true }));
    expect(screen.getByText('required')).toBeTruthy();
    expect(screen.getByText('This backend requires an API key. Set it below.')).toBeTruthy();
  });

  it('saves a trimmed API key from a secure input', async () => {
    await render(<SettingsScreen />);
    const input = screen.getByTestId('api-key-input');
    expect(input.props.secureTextEntry).toBe(true);
    await fireEvent.changeText(input, '  s3cret  ');
    await fireEvent.press(screen.getByText('Save API key'));
    expect(await screen.findByText('Saved')).toBeTruthy();
    expect(getApiKey()).toBe('s3cret');
    // The "Saved" confirmation resets after 2s.
    expect(await screen.findByText('Save API key', {}, { timeout: 4000 })).toBeTruthy();
  });
});
