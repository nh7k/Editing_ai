import { useEffect, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { Job, JobAgent, JobLog, ReviewCheck } from '../api/types';
import { useJobPolling, type JobPollingState } from '../hooks/useJobPolling';
import { colors, radius, spacing } from '../theme';
import { formatDuration, formatPercent, formatTime } from '../utils/format';
import { AppText } from './AppText';
import { Button } from './Button';
import { ProgressBar } from './ProgressBar';
import { InlineError, LoadingState } from './States';
import { StatusPill, toneForStatus } from './StatusPill';

export interface AgentActivitySheetProps {
  jobId: string | null;
  visible: boolean;
  onClose: () => void;
  onFinished?: (job: Job) => void;
  /** Polling state owned by the screen (then the sheet does not poll on its own). */
  pollState?: JobPollingState;
}

/** Bottom sheet that polls GET /jobs/{id} and shows live agent activity. */
export function AgentActivitySheet({ jobId, visible, onClose, onFinished, pollState }: AgentActivitySheetProps) {
  const insets = useSafeAreaInsets();
  // Keep polling while the sheet is hidden so the screen still learns when the job finishes.
  const own = useJobPolling(pollState ? null : jobId, onFinished);
  const { job, error, polling } = pollState ?? own;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close agent activity" />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]} testID="agent-activity-sheet">
          <View style={styles.handle} />
          <View style={styles.titleRow}>
            <AppText size="lg" weight="bold">
              Agent Activity
            </AppText>
            <Button title="Close" variant="ghost" small onPress={onClose} />
          </View>
          {!job && !error ? <LoadingState label="Contacting the agents..." /> : null}
          {!job && error ? <InlineError message={error} /> : null}
          {job ? <AgentActivityContent job={job} pollError={error} polling={polling} /> : null}
        </View>
      </View>
    </Modal>
  );
}

export interface AgentActivityContentProps {
  job: Job;
  pollError?: string | null;
  polling?: boolean;
}

export function AgentActivityContent({ job, pollError, polling }: AgentActivityContentProps) {
  const matchPercent = job.review?.match_percent ?? job.match_percent;
  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>
      <View style={styles.overall}>
        <View style={styles.rowBetween}>
          <View style={styles.rowGap}>
            <StatusPill label={job.status.toUpperCase()} tone={toneForStatus(job.status)} testID="job-status" />
            {job.stage ? (
              <AppText size="sm" muted>
                {job.stage}
              </AppText>
            ) : null}
          </View>
          <AppText size="sm" weight="semibold">
            {formatPercent(job.progress)}
          </AppText>
        </View>
        <ProgressBar
          value={job.progress / 100}
          color={job.status === 'failed' ? colors.coral : job.status === 'done' ? colors.mint : colors.accent}
          height={8}
          testID="job-progress"
        />
        <AppText size="xs" muted numberOfLines={2}>
          {`"${job.prompt}"`}
        </AppText>
        <ElapsedHint job={job} />
        {matchPercent !== null && matchPercent !== undefined ? (
          <AppText size="sm" weight="semibold" color={colors.mint} testID="match-percent">
            {`Match ${formatPercent(matchPercent)}`}
          </AppText>
        ) : null}
      </View>

      {job.status === 'failed' ? (
        <View style={styles.failure} testID="job-error">
          <AppText weight="semibold" color={colors.coral}>
            Edit failed
          </AppText>
          <AppText size="sm" color={colors.coral}>
            {job.error ?? 'The job failed without an error message.'}
          </AppText>
        </View>
      ) : null}
      {pollError ? <InlineError message={`${pollError}${polling ? ' (retrying...)' : ''}`} /> : null}

      <Section title="Agents">
        {job.agents.length === 0 ? (
          <AppText size="sm" muted>
            Waiting for agents to start...
          </AppText>
        ) : (
          job.agents.map((a) => <AgentRow key={a.name} agent={a} />)
        )}
      </Section>

      {job.review ? (
        <Section title={`Review checks (${job.review.checks.filter((c) => c.passed).length}/${job.review.checks.length} passed)`}>
          {job.review.checks.map((c, i) => (
            <CheckRow key={`${c.name}-${i}`} check={c} />
          ))}
        </Section>
      ) : null}

      <Section title="Live log">
        {job.logs.length === 0 ? (
          <AppText size="sm" muted>
            No log entries yet.
          </AppText>
        ) : (
          [...job.logs].reverse().slice(0, 80).map((l, i) => <LogRow key={`${l.t}-${i}`} log={l} />)
        )}
      </Section>
    </ScrollView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <AppText size="sm" weight="semibold" muted style={styles.sectionTitle}>
        {title.toUpperCase()}
      </AppText>
      {children}
    </View>
  );
}

function AgentRow({ agent }: { agent: JobAgent }) {
  return (
    <View style={styles.agentRow} testID={`agent-${agent.name}`}>
      <View style={styles.rowBetween}>
        <View style={styles.rowGap}>
          <AppText weight="semibold">{agent.name}</AppText>
          <StatusPill label={agent.status} tone={toneForStatus(agent.status)} />
        </View>
        <AppText size="sm" muted>
          {agent.score !== null ? `score ${Math.round(agent.score)}` : 'score -'}
          {agent.attempts > 1 ? ` · ${agent.attempts} attempts` : ''}
        </AppText>
      </View>
      <ProgressBar
        value={agent.progress / 100}
        height={4}
        color={agent.status === 'failed' ? colors.coral : agent.status === 'done' ? colors.mint : colors.accent}
      />
      {agent.message ? (
        <AppText size="xs" muted numberOfLines={2}>
          {agent.message}
        </AppText>
      ) : null}
    </View>
  );
}

function CheckRow({ check }: { check: ReviewCheck }) {
  return (
    <View style={styles.checkRow}>
      <AppText color={check.passed ? colors.mint : colors.coral} weight="bold">
        {check.passed ? 'PASS' : 'FAIL'}
      </AppText>
      <View style={styles.flex}>
        <AppText size="sm" weight="medium">
          {check.name}
          <AppText size="xs" muted>{`  ${check.owner}`}</AppText>
        </AppText>
        {check.detail ? (
          <AppText size="xs" muted>
            {check.detail}
          </AppText>
        ) : null}
      </View>
      <AppText size="xs" weight="semibold" color={check.points >= 0 ? colors.mint : colors.coral}>
        {check.points > 0 ? `+${check.points}` : `${check.points}`}
      </AppText>
    </View>
  );
}

const levelColor: Record<JobLog['level'], string> = {
  info: colors.textMuted,
  warn: colors.amber,
  error: colors.coral,
};

function LogRow({ log }: { log: JobLog }) {
  return (
    <View style={styles.logRow}>
      <AppText size="xs" color={colors.textFaint}>
        {formatTime(log.t)}
      </AppText>
      <AppText size="xs" weight="semibold" color={colors.accent}>
        {log.agent}
      </AppText>
      <AppText size="xs" color={levelColor[log.level] ?? colors.textMuted} style={styles.flex}>
        {log.msg}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    maxHeight: '88%',
    minHeight: '50%',
    width: '100%',
    maxWidth: 760,
    alignSelf: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  handle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: spacing.sm },
  titleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm },
  scroll: { flexGrow: 0 },
  scrollContent: { paddingBottom: spacing.lg, gap: spacing.md },
  overall: { backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm },
  rowGap: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexShrink: 1 },
  failure: { backgroundColor: colors.coralSoft, borderRadius: radius.md, padding: spacing.md, gap: 4 },
  section: { backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  sectionTitle: { letterSpacing: 0.6 },
  agentRow: { gap: 6, paddingVertical: 4 },
  checkRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  logRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  flex: { flex: 1 },
});

/** Edits take minutes on a CPU server: show elapsed time so a long job never looks frozen. */
export function ElapsedHint({ job }: { job: Job }) {
  const active = job.status === 'queued' || job.status === 'running';
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  const start = Date.parse(job.created_at);
  const end = job.finished_at ? Date.parse(job.finished_at) : now;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  const secs = Math.max(0, Math.round((end - start) / 1000));
  const text = active
    ? `Elapsed ${formatDuration(secs)} · edits usually take 1–5 min${job.queue_position ? ' (waiting for the edit ahead)' : ''}`
    : `Took ${formatDuration(secs)}`;
  return (
    <AppText size="xs" muted testID="job-elapsed">
      {text}
    </AppText>
  );
}
