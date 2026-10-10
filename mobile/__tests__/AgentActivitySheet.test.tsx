import { act, render, screen } from '@testing-library/react-native';

import { api } from '../src/api/client';
import { AgentActivityContent, AgentActivitySheet } from '../src/components/AgentActivitySheet';
import { POLL_INTERVAL_MS } from '../src/hooks/useJobPolling';
import { doneJob, failedJob, runningJob } from './fixtures';

describe('AgentActivitySheet', () => {
  afterEach(() => {
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  it('renders agents, status, review checks and logs from a Job', async () => {
    await render(<AgentActivityContent job={runningJob} />);

    expect(screen.getByText('RUNNING')).toBeTruthy();
    expect(screen.getByText('45%')).toBeTruthy();
    // agents with status, score and attempts
    expect(screen.getByText('Analyzer')).toBeTruthy();
    expect(screen.getByText('retrying')).toBeTruthy();
    expect(screen.getByText(/score 55 · 2 attempts/)).toBeTruthy();
    // review checks + match %
    expect(screen.getByText('Match 72%')).toBeTruthy();
    expect(screen.getByText('REVIEW CHECKS (1/2 PASSED)')).toBeTruthy();
    expect(screen.getByText('FAIL')).toBeTruthy();
    expect(screen.getByText('PASS')).toBeTruthy();
    expect(screen.getByText('19.0s vs 15s target')).toBeTruthy();
    // logs
    expect(screen.getByText('Parsed intent: 15s')).toBeTruthy();
    expect(screen.getByText('Duration 19s exceeds target')).toBeTruthy();
  });

  it('shows the error message when the job failed', async () => {
    await render(<AgentActivityContent job={failedJob} />);
    expect(screen.getByText('FAILED')).toBeTruthy();
    expect(screen.getByText('Edit failed')).toBeTruthy();
    expect(screen.getByText('ffmpeg exited with code 1')).toBeTruthy();
  });

  it('polls GET /jobs/{id} until the job is done and reports completion', async () => {
    jest.useFakeTimers();
    const getJob = jest.spyOn(api, 'getJob').mockResolvedValueOnce(runningJob).mockResolvedValueOnce(doneJob);
    const onFinished = jest.fn();

    await render(<AgentActivitySheet jobId="j1" visible onClose={jest.fn()} onFinished={onFinished} />);

    expect(await screen.findByText('RUNNING')).toBeTruthy();
    expect(getJob).toHaveBeenCalledTimes(1);

    await act(async () => {
      jest.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    expect(await screen.findByText('DONE')).toBeTruthy();
    expect(screen.getByText('Match 92%')).toBeTruthy();
    expect(getJob).toHaveBeenCalledTimes(2);
    expect(onFinished).toHaveBeenCalledWith(doneJob);

    // No more polling once the job is terminal.
    await act(async () => {
      jest.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    });
    expect(getJob).toHaveBeenCalledTimes(2);
  });
});
