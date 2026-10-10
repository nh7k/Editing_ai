import { ActivityIndicator, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import type { Job } from '../../api/types';
import { formatPercent } from '../../utils/format';
import { AppText } from '../AppText';
import { ProgressBar } from '../ProgressBar';
import { studio } from './theme';

/** Stage line of a running job ("Line me hai · 2 edit aage" while queued). */
export function liveStageText(job: Pick<Job, 'status' | 'stage' | 'queue_position'> | null | undefined): string {
  if (job?.status === 'queued') return job.queue_position ? `Line me hai · ${job.queue_position} edit aage` : 'Queue me hai…';
  return job?.stage || 'Starting…';
}

export interface LiveProgressCardProps {
  job: Job | null;
  /** Colour chip text from the live `color` track (null = not decided yet). */
  look: string | null;
  pollError?: string | null;
  style?: StyleProp<ViewStyle>;
}

/**
 * Small card over the preview while the agents edit (studio, wide layout): title, stage, progress and the
 * colour chip. The live timeline itself is drawn in the bottom StudioTimeline and the agents' thoughts in
 * the chat.
 */
export function LiveProgressCard({ job, look, pollError, style }: LiveProgressCardProps) {
  const progress = job?.progress ?? 0;
  const failed = job?.status === 'failed';
  return (
    <View style={[styles.card, style]} testID="live-progress-card">
      <View style={styles.head}>
        {!failed ? <ActivityIndicator size="small" color={studio.cyan} /> : null}
        <AppText size="md" weight="bold">
          {failed ? 'Edit ruk gaya' : 'Agent edit kar raha hai'}
        </AppText>
      </View>
      <View style={styles.row}>
        <AppText size="xs" color={studio.muted} numberOfLines={1} style={styles.flex} testID="live-card-stage">
          {liveStageText(job)}
        </AppText>
        <AppText size="xs" weight="semibold" testID="live-card-percent">
          {formatPercent(progress)}
        </AppText>
      </View>
      <ProgressBar value={progress / 100} height={6} color={failed ? studio.red : studio.cyan} testID="live-card-progress" />
      <View style={styles.row}>
        <View style={[styles.colorChip, !look && styles.colorChipEmpty]} testID="live-card-color">
          <View style={[styles.colorDot, { backgroundColor: look ? studio.purple : studio.faint }]} />
          <AppText size="xs" color={look ? studio.text : studio.faint}>
            {look ? `Colour: ${look}` : 'Colour: —'}
          </AppText>
        </View>
        <AppText size="xs" color={studio.faint} numberOfLines={1} style={styles.flex}>
          Timeline neeche · soch chat me
        </AppText>
      </View>
      {job?.prompt ? (
        <AppText size="xs" color={studio.faint} numberOfLines={1}>
          {`"${job.prompt}"`}
        </AppText>
      ) : null}
      {pollError ? (
        <AppText size="xs" color={studio.red}>
          {`${pollError} (retrying...)`}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: 340,
    maxWidth: '90%',
    gap: 8,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: studio.border,
    backgroundColor: 'rgba(21, 23, 30, 0.92)',
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  flex: { flex: 1 },
  colorChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 999,
    backgroundColor: 'rgba(199, 125, 219, 0.18)',
  },
  colorChipEmpty: { backgroundColor: studio.card },
  colorDot: { width: 8, height: 8, borderRadius: 4 },
});
