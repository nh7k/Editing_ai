import { useCallback, useLayoutEffect, useState } from 'react';
import { Platform, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage } from '../api/client';
import type { AspectRatio, Job, JobOutput, OutputExtra, Project, Resolution } from '../api/types';
import { AgentActivitySheet } from '../components/AgentActivitySheet';
import {
  AppText,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  Screen,
  StatusPill,
} from '../components';
import { useAsync } from '../hooks/useAsync';
import type { RootScreenProps } from '../navigation/types';
import { colors, radius, spacing } from '../theme';
import { formatBytes, formatDuration, formatPercent } from '../utils/format';
import { saveVideo, shareVideo } from '../utils/media';

type Props = RootScreenProps<'Export'>;

export const RESOLUTIONS: Resolution[] = [480, 720, 1080];
export const ASPECTS: AspectRatio[] = ['9:16', '1:1', '16:9'];

export const EXTRAS_HINT = "Ask for 'export gif and mp3' in your prompt to get them.";

/** Extra downloads the backend can render next to the mp4, in display order. */
export const EXTRA_FORMATS: { format: OutputExtra; label: string; mimeType: string }[] = [
  { format: 'gif', label: 'Download GIF', mimeType: 'image/gif' },
  { format: 'mp3', label: 'Download MP3', mimeType: 'audio/mpeg' },
];

interface ExportData {
  project: Project;
  lastJob: Job | null;
}

/** Pre-select the options of the last render when we know them. */
export function defaultsFromOutput(output: JobOutput | null | undefined): { resolution: Resolution; aspect: AspectRatio } {
  if (!output || output.width <= 0 || output.height <= 0) return { resolution: 720, aspect: '9:16' };
  const short = Math.min(output.width, output.height);
  const resolution = RESOLUTIONS.find((r) => r === short) ?? 720;
  const ratio = output.width / output.height;
  const aspect: AspectRatio = ratio < 0.8 ? '9:16' : ratio > 1.25 ? '16:9' : '1:1';
  return { resolution, aspect };
}

/** Unique, filesystem-safe download name, e.g. `cutmind-lisbon-reel-1700000000000.gif`. */
function exportFileName(projectName: string, ext: string): string {
  return `cutmind-${projectName.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${Date.now()}.${ext}`;
}

async function loadExportData(projectId: string): Promise<ExportData> {
  const project = await api.getProject(projectId);
  const lastJob = project.last_job_id ? await api.getJob(project.last_job_id) : null;
  return { project, lastJob };
}

export function ExportScreen({ navigation, route }: Props) {
  const { projectId, projectName } = route.params;
  const data = useAsync(() => loadExportData(projectId), projectId);

  // null = "not chosen yet": fall back to the options of the last render.
  const [resolutionChoice, setResolution] = useState<Resolution | null>(null);
  const [aspectChoice, setAspect] = useState<AspectRatio | null>(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const [mediaBusy, setMediaBusy] = useState<'save' | 'share' | OutputExtra | null>(null);
  const [mediaMessage, setMediaMessage] = useState<string | null>(null);
  const [mediaError, setMediaError] = useState<string | null>(null);

  const [comment, setComment] = useState('');
  const [feedbackBusy, setFeedbackBusy] = useState<'up' | 'down' | null>(null);
  const [feedbackResult, setFeedbackResult] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: `Export · ${data.data?.project.name ?? projectName ?? ''}`.trim() });
  }, [navigation, data.data?.project.name, projectName]);

  const defaults = defaultsFromOutput(data.data?.lastJob?.output);
  const resolution = resolutionChoice ?? defaults.resolution;
  const aspect = aspectChoice ?? defaults.aspect;

  const reload = data.reload;
  const onFinished = useCallback(() => {
    void reload(true);
  }, [reload]);

  if (data.loading && !data.data) {
    return (
      <Screen>
        <LoadingState label="Loading export options..." />
      </Screen>
    );
  }
  if (data.error && !data.data) {
    return (
      <Screen>
        <ErrorState title="Could not load project" message={data.error} onRetry={() => data.reload()} />
      </Screen>
    );
  }
  const project = data.data?.project;
  const lastJob = data.data?.lastJob ?? null;
  if (!project) return null;

  if (!lastJob) {
    return (
      <Screen>
        <EmptyState
          title="Nothing to export yet"
          message="Run an edit in the editor first. Export re-renders your last prompt at the size you choose."
          actionLabel="Go to editor"
          onAction={() => navigation.navigate('Editor', { projectId, projectName: project.name })}
        />
      </Screen>
    );
  }

  const outputUrl = api.outputUrl(projectId, project.output_job_id ?? project.last_job_id);

  const render = async () => {
    setRendering(true);
    setRenderError(null);
    setFeedbackResult(null);
    try {
      const res = await api.startEdit(projectId, { prompt: lastJob.prompt, aspect_ratio: aspect, resolution });
      setJobId(res.job_id);
      setSheetOpen(true);
    } catch (e) {
      setRenderError(errorMessage(e));
    } finally {
      setRendering(false);
    }
  };

  const extras = EXTRA_FORMATS.filter((x) => lastJob.output?.extras?.includes(x.format));
  const runMedia = async (kind: 'save' | 'share') => {
    setMediaBusy(kind);
    setMediaError(null);
    setMediaMessage(null);
    try {
      const fileName = exportFileName(project.name, 'mp4');
      const res = kind === 'save' ? await saveVideo(outputUrl, fileName) : await shareVideo(outputUrl, fileName);
      setMediaMessage(res.message);
    } catch (e) {
      setMediaError(errorMessage(e));
    } finally {
      setMediaBusy(null);
    }
  };

  /** Web: plain download link. Native: download to cache + system share sheet. */
  const downloadExtra = async (extra: (typeof EXTRA_FORMATS)[number]) => {
    setMediaBusy(extra.format);
    setMediaError(null);
    setMediaMessage(null);
    try {
      const url = api.outputUrl(projectId, project.output_job_id ?? project.last_job_id, extra.format);
      const fileName = exportFileName(project.name, extra.format);
      const res =
        Platform.OS === 'web' ? await saveVideo(url, fileName) : await shareVideo(url, fileName, extra.mimeType);
      setMediaMessage(res.message);
    } catch (e) {
      setMediaError(errorMessage(e));
    } finally {
      setMediaBusy(null);
    }
  };

  const sendFeedback = async (rating: 'up' | 'down') => {
    setFeedbackBusy(rating);
    setFeedbackError(null);
    setFeedbackResult(null);
    try {
      const trimmed = comment.trim();
      const res = await api.sendFeedback(lastJob.id, { rating, ...(trimmed ? { comment: trimmed } : {}) });
      setFeedbackResult(`Thanks! Agents ${res.points_delta >= 0 ? '+' : ''}${res.points_delta} points.`);
      setComment('');
    } catch (e) {
      setFeedbackError(errorMessage(e));
    } finally {
      setFeedbackBusy(null);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Card style={styles.gap}>
          <View style={styles.rowBetween}>
            <AppText size="lg" weight="bold">
              Last render
            </AppText>
            <StatusPill label={lastJob.status.toUpperCase()} tone={lastJob.status === 'done' ? 'success' : lastJob.status === 'failed' ? 'danger' : 'accent'} />
          </View>
          <AppText size="sm" muted>{`"${lastJob.prompt}"`}</AppText>
          {lastJob.output ? (
            <AppText size="sm" muted>
              {`${lastJob.output.width}x${lastJob.output.height} · ${formatDuration(lastJob.output.duration)} · ${formatBytes(lastJob.output.size_bytes)} · match ${formatPercent(lastJob.match_percent)}`}
            </AppText>
          ) : null}
        </Card>

        <Card style={styles.gap}>
          <AppText weight="semibold">Resolution</AppText>
          <View style={styles.chips}>
            {RESOLUTIONS.map((r) => (
              <Chip key={r} label={`${r}p`} selected={resolution === r} onPress={() => setResolution(r)} />
            ))}
          </View>
          <AppText weight="semibold">Aspect ratio</AppText>
          <View style={styles.chips}>
            {ASPECTS.map((a) => (
              <Chip key={a} label={a} selected={aspect === a} onPress={() => setAspect(a)} />
            ))}
          </View>
          <Button title={`Render ${resolution}p · ${aspect}`} onPress={render} loading={rendering} testID="render-export" />
          {jobId ? <Button title="Show agent activity" variant="ghost" small onPress={() => setSheetOpen(true)} /> : null}
          {renderError ? <InlineError message={renderError} /> : null}
        </Card>

        <Card style={styles.gap}>
          <AppText weight="semibold">Save & share</AppText>
          {!project.has_output ? (
            <AppText size="sm" muted>
              No rendered video available yet.
            </AppText>
          ) : null}
          <View style={styles.row}>
            <Button
              title="Save"
              onPress={() => runMedia('save')}
              loading={mediaBusy === 'save'}
              disabled={!project.has_output || mediaBusy !== null}
              style={styles.flex}
            />
            <Button
              title="Share"
              variant="secondary"
              onPress={() => runMedia('share')}
              loading={mediaBusy === 'share'}
              disabled={!project.has_output || mediaBusy !== null}
              style={styles.flex}
            />
          </View>
          {extras.length > 0 ? (
            <View style={styles.row}>
              {extras.map((x) => (
                <Button
                  key={x.format}
                  title={x.label}
                  variant="secondary"
                  onPress={() => downloadExtra(x)}
                  loading={mediaBusy === x.format}
                  disabled={mediaBusy !== null}
                  style={styles.flex}
                  testID={`download-${x.format}`}
                />
              ))}
            </View>
          ) : null}
          <AppText size="xs" muted testID="extras-hint">
            {EXTRAS_HINT}
          </AppText>
          {mediaMessage ? (
            <AppText size="sm" color={colors.mint}>
              {mediaMessage}
            </AppText>
          ) : null}
          {mediaError ? <InlineError message={mediaError} /> : null}
        </Card>

        <Card style={styles.gap}>
          <AppText weight="semibold">How did the agents do?</AppText>
          <TextInput
            value={comment}
            onChangeText={setComment}
            placeholder="Optional comment (becomes a lesson for the agents)"
            placeholderTextColor={colors.textFaint}
            style={styles.input}
            multiline
            accessibilityLabel="Feedback comment"
            testID="feedback-comment"
          />
          <View style={styles.row}>
            <Button
              title="Thumbs up"
              icon="👍"
              variant="secondary"
              onPress={() => sendFeedback('up')}
              loading={feedbackBusy === 'up'}
              disabled={feedbackBusy !== null}
              style={styles.flex}
              testID="feedback-up"
            />
            <Button
              title="Thumbs down"
              icon="👎"
              variant="secondary"
              onPress={() => sendFeedback('down')}
              loading={feedbackBusy === 'down'}
              disabled={feedbackBusy !== null}
              style={styles.flex}
              testID="feedback-down"
            />
          </View>
          {feedbackResult ? (
            <AppText size="sm" color={colors.mint} testID="feedback-result">
              {feedbackResult}
            </AppText>
          ) : null}
          {feedbackError ? <InlineError message={feedbackError} /> : null}
        </Card>
      </ScrollView>

      <AgentActivitySheet jobId={jobId} visible={sheetOpen} onClose={() => setSheetOpen(false)} onFinished={onFinished} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  gap: { gap: spacing.sm },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  row: { flexDirection: 'row', gap: spacing.sm },
  chips: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  flex: { flex: 1 },
  input: {
    minHeight: 64,
    backgroundColor: colors.cardAlt,
    borderRadius: radius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: 15,
    textAlignVertical: 'top',
  },
});
