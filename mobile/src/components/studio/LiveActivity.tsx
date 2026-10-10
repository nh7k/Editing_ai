import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import type { Job, JobEvent } from '../../api/types';
import { AppText } from '../AppText';
import { studio } from './theme';

/** The LangGraph nodes, in the order they run, with what each one really does. */
export const NODE_ROWS: readonly { node: string; label: string; optional?: boolean }[] = [
  { node: 'understand', label: 'Understanding your request' },
  { node: 'analyze', label: 'Analyzing the video (scenes, motion, sound, speech)' },
  { node: 'audio', label: 'Music & audio' },
  { node: 'cutter', label: 'Cutting & arranging clips' },
  { node: 'color', label: 'Colour grading' },
  { node: 'effects', label: 'Effects, captions & transitions' },
  { node: 'render', label: 'Rendering' },
  { node: 'review', label: 'Reviewing the result' },
  { node: 'fix', label: 'Fixing what the reviewer flagged', optional: true },
  { node: 'finalize', label: 'Saving the final video' },
];

const CORE = new Set([
  'conversation', 'intent_parser', 'prompt_compiler', 'planner', 'memory_keeper', 'media_probe', 'visual_analyzer',
  'audio_analyzer', 'color_grader', 'audio_mixer', 'timeline_builder', 'renderer', 'quality_gate', 'reviewer',
  'lesson_writer', 'error_recovery', 'exporter',
]);

type RowState = 'pending' | 'running' | 'done' | 'failed';

export interface ActivityRow {
  node: string;
  label: string;
  state: RowState;
  ms?: number;
  runs: number;
}

/** Steps of a hand-made (manual) change: no AI nodes run, so none are shown. */
export const MANUAL_ROWS: readonly { node: string; label: string; optional?: boolean }[] = [
  { node: 'apply', label: 'Applying your change (no AI)' },
  { node: 'render', label: 'Rendering (only what changed)' },
  { node: 'review', label: 'Quality check' },
];

/** Turn real backend events into the panel rows. Nothing here is animated without an event behind it. */
export function activityRows(events: JobEvent[]): ActivityRow[] {
  const manual = events.some((e) => e.node === 'apply');
  return (manual ? MANUAL_ROWS : NODE_ROWS).map(({ node, label, optional }) => {
    const mine = events.filter((e) => e.node === node && e.type.startsWith('node_'));
    const last = mine[mine.length - 1];
    const runs = mine.filter((e) => e.type === 'node_started').length;
    const state: RowState = !last
      ? 'pending'
      : last.type === 'node_started'
        ? 'running'
        : last.type === 'node_failed'
          ? 'failed'
          : 'done';
    return { node, label, state, ms: last?.ms, runs, optional } as ActivityRow & { optional?: boolean };
  }).filter((r) => !(r as { optional?: boolean }).optional || r.state !== 'pending');
}

function secs(ms?: number) {
  if (ms === undefined) return '';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function LiveActivity({ events, job }: { events: JobEvent[]; job: Job | null }) {
  const [showAll, setShowAll] = useState(false);
  if (!events.length) return null;
  const rows = activityRows(events);
  const running = job ? job.status === 'running' || job.status === 'queued' : true;
  const stage = [...events].reverse().find((e) => e.type === 'progress');
  const selected = [...events].reverse().find((e) => e.type === 'agents_selected')?.agents ?? [];
  const specialists = selected.filter((a) => !CORE.has(a.id));
  const reviews = events.filter((e) => e.type === 'review_completed');
  const logs = events.filter((e) => e.type === 'log' && e.level !== 'debug');
  const lastT = events[events.length - 1].t;
  const resumed = events.some((e) => e.type === 'job_resumed');
  return (
    <View style={styles.box} testID="live-activity">
      <View style={styles.head}>
        <AppText size="xs" weight="semibold" color={studio.cyan}>
          {running ? 'AI EDITING' : 'WHAT THE AGENTS DID'}
        </AppText>
        <AppText size="xs" color={studio.muted}>
          {lastT.toFixed(1)} s{resumed ? ' · resumed after restart' : ''}
        </AppText>
      </View>
      {rows.map((r) => (
        <View key={r.node} style={styles.row} testID={`activity-${r.node}`}>
          <View style={styles.icon}>
            {r.state === 'running' ? (
              <ActivityIndicator size="small" color={studio.cyan} />
            ) : (
              <AppText size="sm" color={r.state === 'done' ? studio.green : r.state === 'failed' ? studio.red : studio.muted}>
                {r.state === 'done' ? '✓' : r.state === 'failed' ? '✗' : '○'}
              </AppText>
            )}
          </View>
          <View style={styles.rowText}>
            <AppText size="sm" color={r.state === 'pending' ? studio.muted : studio.text}>
              {r.label}
              {r.runs > 1 ? ` (×${r.runs})` : ''}
            </AppText>
            {/* agents run in parallel: the backend's stage text belongs to the render / save steps only */}
            {r.state === 'running' && (r.node === 'render' || r.node === 'finalize') && stage?.stage ? (
              <AppText size="xs" color={studio.muted}>
                {stage.stage}
              </AppText>
            ) : null}
            {r.node === 'understand' && specialists.length && r.state !== 'pending' ? (
              <AppText size="xs" color={studio.muted}>
                {selected.length} specialists picked
                {specialists.length ? `: ${specialists.slice(0, 6).map((a) => a.name).join(', ')}${specialists.length > 6 ? '…' : ''}` : ''}
              </AppText>
            ) : null}
            {r.node === 'review' && reviews.length ? (
              <AppText size="xs" color={studio.muted}>
                match {reviews[reviews.length - 1].match_percent}%
              </AppText>
            ) : null}
          </View>
          <AppText size="xs" color={studio.muted}>
            {r.state === 'done' ? secs(r.ms) : ''}
          </AppText>
        </View>
      ))}
      {logs.length ? (
        <Pressable onPress={() => setShowAll((v) => !v)} accessibilityRole="button" testID="activity-log-toggle">
          <AppText size="xs" color={studio.muted} numberOfLines={showAll ? undefined : 2}>
            {(showAll ? logs.slice(-40) : logs.slice(-1))
              .map((l) => `${l.agent}: ${l.msg}`)
              .join('\n')}
          </AppText>
          <AppText size="xs" color={studio.blue}>
            {showAll ? 'hide log' : `show log (${logs.length})`}
          </AppText>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { backgroundColor: studio.card, borderRadius: 12, padding: 10, gap: 6, borderWidth: 1, borderColor: studio.border },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  row: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  icon: { width: 18, alignItems: 'center', paddingTop: 1 },
  rowText: { flex: 1, gap: 1 },
});
