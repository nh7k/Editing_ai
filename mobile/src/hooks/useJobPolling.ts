import { useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../api/client';
import type { Job } from '../api/types';

export const POLL_INTERVAL_MS = 1500;
/** Stop polling after this many consecutive request failures. */
export const MAX_POLL_FAILURES = 5;

export function isTerminal(job: Job | null | undefined): boolean {
  return !!job && (job.status === 'done' || job.status === 'failed');
}

export interface JobPollingState {
  job: Job | null;
  error: string | null;
  polling: boolean;
}

interface Internal {
  jobId: string | null;
  job: Job | null;
  error: string | null;
  stopped: boolean;
}

/**
 * Polls GET /jobs/{id} every `intervalMs` until the job is done or failed.
 * Transient errors are surfaced but polling continues (up to MAX_POLL_FAILURES in a row).
 */
export function useJobPolling(
  jobId: string | null,
  onFinished?: (job: Job) => void,
  intervalMs: number = POLL_INTERVAL_MS,
): JobPollingState {
  const [state, setState] = useState<Internal>({ jobId: null, job: null, error: null, stopped: false });
  const onFinishedRef = useRef(onFinished);

  useEffect(() => {
    onFinishedRef.current = onFinished;
  });

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;

    const tick = async () => {
      try {
        const next = await api.getJob(jobId);
        if (cancelled) return;
        failures = 0;
        const done = isTerminal(next);
        setState({ jobId, job: next, error: null, stopped: done });
        if (done) {
          onFinishedRef.current?.(next);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        failures += 1;
        const stop = failures >= MAX_POLL_FAILURES;
        const message = errorMessage(e);
        setState((s) => ({
          jobId,
          job: s.jobId === jobId ? s.job : null,
          error: message,
          stopped: stop,
        }));
        if (stop) return;
      }
      timer = setTimeout(tick, intervalMs);
    };
    void tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  // Ignore state that belongs to a previous job id.
  if (!jobId || state.jobId !== jobId) {
    return { job: null, error: null, polling: !!jobId };
  }
  return { job: state.job, error: state.error, polling: !state.stopped };
}
