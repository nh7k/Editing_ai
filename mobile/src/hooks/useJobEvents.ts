import { useEffect, useMemo, useState } from 'react';
import { Platform } from 'react-native';

import { api } from '../api/client';
import type { JobEvent } from '../api/types';

/** Every event type the backend emits (EventSource needs a listener per named event). */
export const EVENT_TYPES = [
  'job_started', 'job_resumed', 'job_requeued', 'progress', 'agents_selected', 'node_started', 'node_completed',
  'node_failed', 'agent_started', 'agent_completed', 'agent_failed', 'agent_status', 'agent_scored', 'log',
  'render_completed', 'review_completed', 'final_ready', 'job_done', 'job_failed', 'thought', 'timeline', 'render_step',
] as const;

function sseSupported(): boolean {
  return Platform.OS === 'web' && typeof (globalThis as { EventSource?: unknown }).EventSource !== 'undefined';
}

/**
 * Live events of a job. On the web they stream over Server-Sent Events the moment they happen; elsewhere
 * (and as a fallback) they come with the polled job snapshot. Merged by sequence number, so nothing repeats.
 */
export function useJobEvents(jobId: string | null, snapshotEvents: JobEvent[] | undefined, live: boolean): JobEvent[] {
  // keyed by job id, so a new job never shows the previous job's events
  const [streamed, setStreamed] = useState<{ id: string | null; events: JobEvent[] }>({ id: null, events: [] });

  useEffect(() => {
    if (!jobId || !live || !sseSupported()) return;
    const ES = (globalThis as unknown as { EventSource: typeof EventSource }).EventSource;
    const source = new ES(api.jobEventsUrl(jobId));
    const onEvent = (e: MessageEvent) => {
      try {
        const ev = JSON.parse(e.data) as JobEvent;
        setStreamed((prev) => {
          const list = prev.id === jobId ? prev.events : [];
          return list.length && list[list.length - 1].seq >= ev.seq ? prev : { id: jobId, events: [...list, ev] };
        });
      } catch {
        // ignore malformed lines
      }
    };
    for (const t of EVENT_TYPES) source.addEventListener(t, onEvent as EventListener);
    source.addEventListener('end', () => source.close());
    source.onerror = () => source.close(); // polling keeps the panel up to date
    return () => source.close();
  }, [jobId, live]);

  return useMemo(() => {
    const bySeq = new Map<number, JobEvent>();
    for (const e of snapshotEvents ?? []) bySeq.set(e.seq, e);
    for (const e of streamed.id === jobId ? streamed.events : []) bySeq.set(e.seq, e);
    return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
  }, [snapshotEvents, streamed, jobId]);
}
