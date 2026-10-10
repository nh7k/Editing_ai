import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as Sharing from 'expo-sharing';

import { api, ApiError } from '../src/api/client';
import { defaultsFromOutput, EXTRAS_HINT, ExportScreen } from '../src/screens/ExportScreen';
import { doneJob, project, screenProps } from './fixtures';

type Props = Parameters<typeof ExportScreen>[0];

async function renderExport() {
  const props = screenProps({ projectId: 'p1' });
  await render(<ExportScreen {...(props as unknown as Props)} />);
  return props;
}

describe('ExportScreen', () => {
  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getJob').mockResolvedValue(doneJob);
  });
  afterEach(() => jest.restoreAllMocks());

  it('sends a thumbs up with the optional comment', async () => {
    const feedback = jest.spyOn(api, 'sendFeedback').mockResolvedValue({ ok: true, points_delta: 5 });
    await renderExport();

    await fireEvent.changeText(await screen.findByTestId('feedback-comment'), 'Great pacing');
    await fireEvent.press(screen.getByTestId('feedback-up'));

    await waitFor(() => expect(feedback).toHaveBeenCalledWith('j1', { rating: 'up', comment: 'Great pacing' }));
    expect(await screen.findByText('Thanks! Agents +5 points.')).toBeTruthy();
  });

  it('sends a thumbs down without a comment', async () => {
    const feedback = jest.spyOn(api, 'sendFeedback').mockResolvedValue({ ok: true, points_delta: -5 });
    await renderExport();

    await fireEvent.press(await screen.findByTestId('feedback-down'));
    await waitFor(() => expect(feedback).toHaveBeenCalledWith('j1', { rating: 'down' }));
    expect(await screen.findByText('Thanks! Agents -5 points.')).toBeTruthy();
  });

  it('shows feedback errors', async () => {
    jest.spyOn(api, 'sendFeedback').mockRejectedValue(new ApiError('job_not_found', 'Job j1 not found', 404));
    await renderExport();
    await fireEvent.press(await screen.findByTestId('feedback-up'));
    expect(await screen.findByText('Job j1 not found')).toBeTruthy();
  });

  it('re-runs the last prompt with the chosen resolution and aspect ratio', async () => {
    const startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j2', status: 'queued' });
    await renderExport();

    await fireEvent.press(await screen.findByText('1080p'));
    await fireEvent.press(screen.getByText('16:9'));
    await fireEvent.press(screen.getByTestId('render-export'));

    await waitFor(() =>
      expect(startEdit).toHaveBeenCalledWith('p1', { prompt: 'Trim to 15s', aspect_ratio: '16:9', resolution: 1080 }),
    );
  });

  it('hides GIF/MP3 downloads when the last render has no extras, but shows the hint', async () => {
    await renderExport();
    expect(await screen.findByText(EXTRAS_HINT)).toBeTruthy();
    expect(EXTRAS_HINT).toBe("Ask for 'export gif and mp3' in your prompt to get them.");
    expect(screen.queryByText('Download GIF')).toBeNull();
    expect(screen.queryByText('Download MP3')).toBeNull();
  });

  it('shows only the extras the last render produced', async () => {
    jest.spyOn(api, 'getJob').mockResolvedValue({ ...doneJob, output: { ...doneJob.output!, extras: ['gif'] } });
    await renderExport();
    expect(await screen.findByText('Download GIF')).toBeTruthy();
    expect(screen.queryByText('Download MP3')).toBeNull();
  });

  it('downloads and shares the GIF / MP3 extras with the right format and mime type', async () => {
    jest.spyOn(api, 'getJob').mockResolvedValue({ ...doneJob, output: { ...doneJob.output!, extras: ['gif', 'mp3'] } });
    const outputUrl = jest.spyOn(api, 'outputUrl');
    await renderExport();

    await fireEvent.press(await screen.findByTestId('download-gif'));
    await waitFor(() =>
      expect(Sharing.shareAsync).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ mimeType: 'image/gif' })),
    );
    expect(outputUrl).toHaveBeenCalledWith('p1', 'j1', 'gif');

    await fireEvent.press(screen.getByTestId('download-mp3'));
    await waitFor(() =>
      expect(Sharing.shareAsync).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ mimeType: 'audio/mpeg' })),
    );
    expect(outputUrl).toHaveBeenCalledWith('p1', 'j1', 'mp3');
    expect(await screen.findByText('Shared.')).toBeTruthy();
  });

  it('pre-selects options from the last output', () => {
    expect(defaultsFromOutput({ width: 720, height: 1280, duration: 1, has_audio: true, size_bytes: 1 })).toEqual({
      resolution: 720,
      aspect: '9:16',
    });
    expect(defaultsFromOutput({ width: 1920, height: 1080, duration: 1, has_audio: true, size_bytes: 1 })).toEqual({
      resolution: 1080,
      aspect: '16:9',
    });
    expect(defaultsFromOutput(null)).toEqual({ resolution: 720, aspect: '9:16' });
  });
});
