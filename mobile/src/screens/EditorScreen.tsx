import { useVideoPlayer } from 'expo-video';
import { useCallback, useLayoutEffect, useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';

import { api, ApiError, errorMessage } from '../api/client';
import type { EditPlan, Job } from '../api/types';
import { AgentActivitySheet } from '../components/AgentActivitySheet';
import { ChatInput } from '../components/ChatInput';
import { LiveEditView } from '../components/LiveEditView';
import { AppText, Button, ErrorState, InlineError, LoadingState, Screen, StatusPill } from '../components';
import { Timeline } from '../components/timeline/Timeline';
import { VideoPreview } from '../components/VideoPreview';
import { useAsync } from '../hooks/useAsync';
import { isTerminal, useJobPolling } from '../hooks/useJobPolling';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import type { RootScreenProps } from '../navigation/types';
import { colors, spacing } from '../theme';
import { formatPercent } from '../utils/format';
import { buildTimeline } from '../utils/timelineModel';

type Props = RootScreenProps<'Editor'>;

/** GET /projects/{id}/plan, returning null when no plan exists yet (404). */
export async function loadPlanOrNull(projectId: string): Promise<EditPlan | null> {
  try {
    return await api.getPlan(projectId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export function EditorScreen({ navigation, route }: Props) {
  const { projectId, projectName, jobId: routeJobId } = route.params;
  const project = useAsync(() => api.getProject(projectId), projectId);
  const plan = useAsync(() => loadPlanOrNull(projectId), projectId);
  useRefreshOnFocus(navigation, () => {
    void project.reload(true);
    void plan.reload(true);
  });

  const [prompt, setPrompt] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  // a job started elsewhere (Copy an Edit / Templates) arrives as the `jobId` route param
  const [jobId, setJobId] = useState<string | null>(routeJobId ?? null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [lastResult, setLastResult] = useState<Job | null>(null);

  // a newer job id in the route params (we were sent back here with a new job) replaces the current one
  const [seenRouteJob, setSeenRouteJob] = useState(routeJobId);
  if (routeJobId && routeJobId !== seenRouteJob) {
    setSeenRouteJob(routeJobId);
    setJobId(routeJobId);
    setLastResult(null);
  }

  useLayoutEffect(() => {
    navigation.setOptions({ title: project.data?.name ?? projectName ?? 'Editor' });
  }, [navigation, project.data?.name, projectName]);

  const hasOutput = !!project.data?.has_output;
  const outputUrl = hasOutput ? api.outputUrl(projectId, project.data?.output_job_id ?? project.data?.last_job_id) : null;
  const player = useVideoPlayer(outputUrl, (p) => {
    p.loop = true;
  });

  const timeline = useMemo(() => buildTimeline(plan.data, project.data?.clips ?? []), [plan.data, project.data?.clips]);

  const send = async () => {
    const text = prompt.trim();
    if (!text) return;
    setSending(true);
    setSendError(null);
    try {
      const res = await api.startEdit(projectId, { prompt: text });
      setJobId(res.job_id);
      setLastResult(null);
    } catch (e) {
      setSendError(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  const reloadProject = project.reload;
  const reloadPlan = plan.reload;
  const onFinished = useCallback(
    (job: Job) => {
      setLastResult(job);
      void reloadProject(true);
      void reloadPlan(true);
    },
    [reloadProject, reloadPlan],
  );
  const poll = useJobPolling(jobId, onFinished);
  const running = !!jobId && poll.polling && !isTerminal(poll.job);

  const onSeek = useCallback(
    (seconds: number) => {
      if (!hasOutput) return;
      try {
        player.seekBy(seconds - player.currentTime);
      } catch {
        // Player not ready yet; ignore.
      }
    },
    [hasOutput, player],
  );

  if (project.loading && !project.data) {
    return (
      <Screen>
        <LoadingState label="Opening editor..." />
      </Screen>
    );
  }
  if (project.error && !project.data) {
    return (
      <Screen>
        <ErrorState title="Could not open project" message={project.error} onRetry={() => project.reload()} />
      </Screen>
    );
  }

  const clipCount = project.data?.clips.length ?? 0;

  return (
    <Screen>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {running ? (
            <LiveEditView jobId={jobId} job={poll.job} pollError={poll.error} onOpenActivity={() => setSheetOpen(true)} />
          ) : (
            <VideoPreview player={player} hasOutput={hasOutput} />
          )}

          <View style={styles.toolbar}>
            <Button
              title={`Clips (${clipCount})`}
              small
              variant="secondary"
              onPress={() => navigation.navigate('Import', { projectId, projectName: project.data?.name })}
            />
            <Button
              title="Export"
              small
              variant="secondary"
              disabled={!project.data?.last_job_id}
              onPress={() => navigation.navigate('Export', { projectId, projectName: project.data?.name })}
            />
            <Button
              title="🎬 Copy an Edit"
              small
              variant="secondary"
              onPress={() => navigation.navigate('CopyEdit', { projectId, projectName: project.data?.name })}
              testID="editor-copy-edit"
            />
            <Button
              title="▤ Templates"
              small
              variant="secondary"
              onPress={() => navigation.navigate('TemplatesGallery', { projectId, projectName: project.data?.name })}
              testID="editor-templates"
            />
            {jobId ? (
              <Button title="Agent activity" small variant="ghost" onPress={() => setSheetOpen(true)} testID="editor-agent-activity" />
            ) : null}
          </View>

          {lastResult ? (
            <View style={styles.resultRow}>
              <StatusPill label={lastResult.status.toUpperCase()} tone={lastResult.status === 'done' ? 'success' : 'danger'} />
              <AppText size="sm" muted>
                {lastResult.status === 'done'
                  ? `Render finished · match ${formatPercent(lastResult.match_percent)}`
                  : lastResult.error ?? 'Edit failed'}
              </AppText>
            </View>
          ) : null}

          {running ? null : <Timeline model={timeline} onSeek={onSeek} />}
          {plan.error ? <InlineError message={`Plan unavailable: ${plan.error}`} /> : null}

          {clipCount === 0 ? (
            <View style={styles.hint}>
              <AppText size="sm" color={colors.amber}>
                This project has no clips yet. Import clips before asking for an edit.
              </AppText>
            </View>
          ) : null}
        </ScrollView>

        <View style={styles.composer}>
          {sendError ? <InlineError message={sendError} /> : null}
          <ChatInput
            value={prompt}
            onChangeText={setPrompt}
            onSend={send}
            sending={sending}
            disabled={clipCount === 0}
          />
        </View>
      </KeyboardAvoidingView>

      <AgentActivitySheet jobId={jobId} visible={sheetOpen} onClose={() => setSheetOpen(false)} pollState={poll} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
  toolbar: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  resultRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  hint: { backgroundColor: colors.amberSoft, borderRadius: 10, padding: spacing.md },
  composer: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
  },
});
