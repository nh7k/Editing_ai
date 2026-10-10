import { render, screen } from '@testing-library/react-native';

import { ElapsedHint } from '../src/components/AgentActivitySheet';
import { runningJob } from './fixtures';

describe('ElapsedHint (long jobs must never look frozen)', () => {
  it('shows elapsed time and the queue wait for a queued job', async () => {
    const created = new Date(Date.now() - 125_000).toISOString();
    await render(<ElapsedHint job={{ ...runningJob, status: 'queued', created_at: created, finished_at: null, queue_position: 1 }} />);
    const text = screen.getByTestId('job-elapsed').props.children as string;
    expect(text).toMatch(/^Elapsed 2:0[4-6] · edits usually take 1–5 min \(waiting for the edit ahead\)$/);
  });

  it('shows the total time once the job is done', async () => {
    await render(
      <ElapsedHint
        job={{ ...runningJob, status: 'done', created_at: '2026-10-05T10:00:00Z', finished_at: '2026-10-05T10:03:30Z' }}
      />,
    );
    expect(screen.getByText('Took 3:30')).toBeTruthy();
  });
});
