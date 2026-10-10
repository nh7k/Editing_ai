import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Animated,
  Image,
  Platform,
  ScrollView,
  StyleSheet,
  View,
  type LayoutChangeEvent,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { api } from '../api/client';
import type { Job, LiveTimeline } from '../api/types';
import { useJobEvents } from '../hooks/useJobEvents';
import { colors, radius, spacing } from '../theme';
import { formatPercent } from '../utils/format';
import {
  blockGeometry,
  blockKey,
  buildLiveState,
  colorLabel,
  liveTotal,
  LIVE_ROWS,
  pxPerSecond,
  ROW_LABELS,
  secondsLabel,
  workingAgent,
  type LiveRow,
  type LiveThoughtEntry,
} from '../utils/liveTimeline';
import { AppText } from './AppText';
import { Button } from './Button';
import { ProgressBar } from './ProgressBar';
import { InlineError } from './States';

const LABEL_W = 56;
const ROW_H: Record<LiveRow, number> = { video: 46, text: 26, fx: 22, music: 24 };
const ROW_COLOR: Record<LiveRow, string> = { video: colors.accent, text: colors.amber, fx: colors.coral, music: colors.mint };
const NATIVE_DRIVER = Platform.OS !== 'web';

/** Fades + slides its child in when it mounts. */
function AppearIn({ children, style, from = 12, testID }: { children?: ReactNode; style?: StyleProp<ViewStyle>; from?: number; testID?: string }) {
  const [v] = useState(() => new Animated.Value(0));
  useEffect(() => {
    const anim = Animated.timing(v, { toValue: 1, duration: 320, useNativeDriver: NATIVE_DRIVER });
    anim.start();
    return () => anim.stop();
  }, [v]);
  const translate = v.interpolate({ inputRange: [0, 1], outputRange: [from, 0] });
  return (
    <Animated.View testID={testID} style={[style, { opacity: v, transform: [{ translateY: translate }] }]}>
      {children}
    </Animated.View>
  );
}

/** "…" that cycles while an agent works. */
function TypingDots() {
  const [n, setN] = useState(1);
  useEffect(() => {
    const id = setInterval(() => setN((x) => (x % 3) + 1), 450);
    return () => clearInterval(id);
  }, []);
  return (
    <AppText size="sm" weight="bold" color={colors.accent} style={styles.dots}>
      {'•'.repeat(n)}
    </AppText>
  );
}

function ThoughtRow({ thought }: { thought: LiveThoughtEntry }) {
  return (
    <AppearIn style={styles.thought} from={10} testID={`live-thought-${thought.key}`}>
      <View style={styles.agentChip}>
        <AppText size="xs" weight="semibold" color={colors.accent} numberOfLines={1}>
          {thought.agent}
        </AppText>
      </View>
      <AppText size="sm" style={styles.thoughtText}>
        {thought.text}
      </AppText>
    </AppearIn>
  );
}

export interface LiveTracksProps {
  tracks: LiveTimeline;
  /** Initial width before layout is measured (tests / first frame). */
  initialWidth?: number;
}

/** Multi-track timeline (Video · Text · FX · Music + colour chip) that fills in as the agents work. */
export function LiveTracks({ tracks, initialWidth = 320 }: LiveTracksProps) {
  const [width, setWidth] = useState(initialWidth);
  const total = liveTotal(tracks);
  const pps = pxPerSecond(total, Math.max(0, width - LABEL_W - spacing.md));
  const contentW = Math.max(1, Math.round(total * pps));
  const look = colorLabel(tracks.color);
  const onLayout = (e: LayoutChangeEvent) => {
    const w = e.nativeEvent.layout.width;
    if (w > 0 && Math.abs(w - width) > 1) setWidth(w);
  };

  const block = (row: LiveRow, item: Record<string, unknown> & { start: number; dur: number }, i: number) => {
    const g = blockGeometry(item.start, item.dur, pps, total);
    const key = blockKey(row, item, i);
    const base = [styles.block, { left: g.left, width: g.width, height: ROW_H[row] - 6, backgroundColor: ROW_COLOR[row] }];
    if (row === 'video') {
      const thumb = typeof item.thumb === 'string' && item.thumb ? api.mediaUrl(item.thumb) : null;
      return (
        <AppearIn key={key} style={[base, styles.videoBlock]} testID={`live-block-video-${i}`}>
          {thumb ? (
            <Image source={{ uri: thumb }} style={StyleSheet.absoluteFill} resizeMode="cover" testID={`live-thumb-${i}`} />
          ) : null}
          {g.width > 34 ? (
            <AppText size="xs" weight="semibold" color="#FFFFFF" numberOfLines={1} style={styles.blockLabel}>
              {`${Number(item.dur).toFixed(1)}s`}
            </AppText>
          ) : null}
        </AppearIn>
      );
    }
    const label = row === 'text' ? item.text : row === 'fx' ? item.type : item.name;
    return (
      <AppearIn key={key} style={base} from={8} testID={`live-block-${row}-${i}`}>
        {g.width > 24 ? (
          <AppText size="xs" weight="medium" color="#0E0F13" numberOfLines={1} style={styles.blockText}>
            {String(label ?? '')}
          </AppText>
        ) : null}
      </AppearIn>
    );
  };

  return (
    <View style={styles.tracksBox} onLayout={onLayout} testID="live-timeline">
      <View style={styles.tracksHead}>
        <AppText size="xs" weight="semibold" muted>
          TIMELINE · {secondsLabel(total)}
        </AppText>
        <View style={[styles.colorChip, !look && styles.colorChipEmpty]} testID="live-color">
          <View style={[styles.colorDot, { backgroundColor: look ? colors.amber : colors.textFaint }]} />
          <AppText size="xs" color={look ? colors.text : colors.textFaint}>
            {look ? `Colour: ${look}` : 'Colour: —'}
          </AppText>
        </View>
      </View>
      <View style={styles.tracksBody}>
        <View style={styles.labels}>
          {LIVE_ROWS.map((r) => (
            <View key={r} style={[styles.labelCell, { height: ROW_H[r] }]}>
              <AppText size="xs" weight="semibold" color={ROW_COLOR[r]}>
                {ROW_LABELS[r]}
              </AppText>
            </View>
          ))}
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator style={styles.flex} contentContainerStyle={{ width: contentW }}>
          <View style={{ width: contentW }}>
            {LIVE_ROWS.map((r) => {
              const items = (tracks[r] ?? []) as unknown as (Record<string, unknown> & { start: number; dur: number })[];
              return (
                <View key={r} style={[styles.row, { height: ROW_H[r] }]} testID={`live-track-${r}`}>
                  {items.length ? (
                    items.map((it, i) => block(r, it, i))
                  ) : (
                    <AppText size="xs" color={colors.textFaint} style={styles.emptyRow}>
                      {r === 'video' ? 'cutting…' : '—'}
                    </AppText>
                  )}
                </View>
              );
            })}
          </View>
        </ScrollView>
      </View>
    </View>
  );
}

export interface LiveEditViewProps {
  jobId: string | null;
  job: Job | null;
  pollError?: string | null;
  /** Opens the detailed Agent Activity (sheet / panel). */
  onOpenActivity?: () => void;
  /** Fill the parent (studio main area) instead of sizing to content (phone scroll view). */
  fill?: boolean;
  style?: StyleProp<ViewStyle>;
}

/**
 * "Watch the agent edit": the agents' thoughts appear one by one while a multi-track timeline fills in.
 * Works from SSE (web) and from the polled job snapshot (`job.timeline`, `job.thoughts`, `job.events`).
 */
export function LiveEditView({ jobId, job, pollError, onOpenActivity, fill, style }: LiveEditViewProps) {
  const live = !!job && (job.status === 'running' || job.status === 'queued');
  const events = useJobEvents(jobId, job?.events, live || !job);
  const state = useMemo(() => buildLiveState(job, events), [job, events]);
  const worker = workingAgent(job, state.thoughts);
  const feedRef = useRef<ScrollView>(null);

  const progress = job?.progress ?? 0;
  const stage = job?.status === 'queued'
    ? job.queue_position ? `Line me hai · ${job.queue_position} edit aage` : 'Queue me hai…'
    : job?.stage || 'Starting…';

  return (
    <View style={[styles.root, fill && styles.rootFill, style]} testID="live-edit-view">
      <View style={styles.head}>
        <View style={styles.headLeft}>
          {live ? <ActivityIndicator size="small" color={colors.accent} /> : null}
          <AppText size="md" weight="bold">
            {live ? 'Agent edit kar raha hai' : job?.status === 'failed' ? 'Edit ruk gaya' : 'Live edit'}
          </AppText>
        </View>
        {onOpenActivity ? (
          <Button title="Agent activity" small variant="ghost" onPress={onOpenActivity} testID="live-open-activity" />
        ) : null}
      </View>

      <View style={styles.progressBox} testID="live-progress">
        <View style={styles.rowBetween}>
          <AppText size="xs" muted numberOfLines={1} style={styles.flex} testID="live-stage">
            {stage}
          </AppText>
          <AppText size="xs" weight="semibold">
            {formatPercent(progress)}
          </AppText>
        </View>
        <ProgressBar value={progress / 100} height={6} color={job?.status === 'failed' ? colors.coral : colors.accent} />
        {job?.prompt ? (
          <AppText size="xs" color={colors.textFaint} numberOfLines={1}>
            {`"${job.prompt}"`}
          </AppText>
        ) : null}
      </View>

      <LiveTracks tracks={state.tracks} />

      <View style={[styles.feedBox, fill ? styles.feedFill : styles.feedFixed]} testID="live-feed">
        <ScrollView
          ref={feedRef}
          contentContainerStyle={styles.feedContent}
          onContentSizeChange={() => feedRef.current?.scrollToEnd({ animated: true })}
        >
          {state.thoughts.length === 0 ? (
            <AppText size="sm" muted testID="live-feed-empty">
              {job ? 'Agents tayyar ho rahe hain…' : 'Connecting to the agents…'}
            </AppText>
          ) : (
            state.thoughts.map((t) => <ThoughtRow key={t.key} thought={t} />)
          )}
          {worker ? (
            <View style={styles.typing} testID="live-typing">
              <View style={styles.agentChip}>
                <AppText size="xs" weight="semibold" color={colors.accent}>
                  {worker}
                </AppText>
              </View>
              <AppText size="xs" muted>
                kaam kar raha hai
              </AppText>
              <TypingDots />
            </View>
          ) : null}
        </ScrollView>
      </View>
      {pollError ? <InlineError message={`${pollError} (retrying...)`} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md, gap: spacing.md, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  rootFill: { flex: 1, minHeight: 0 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm },
  headLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexShrink: 1 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm },
  flex: { flex: 1 },
  progressBox: { gap: 6 },
  tracksBox: { backgroundColor: colors.background, borderRadius: radius.md, padding: spacing.sm, gap: spacing.sm },
  tracksHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  colorChip: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.pill, backgroundColor: colors.amberSoft },
  colorChipEmpty: { backgroundColor: colors.cardAlt },
  colorDot: { width: 8, height: 8, borderRadius: 4 },
  tracksBody: { flexDirection: 'row' },
  labels: { width: LABEL_W },
  labelCell: { justifyContent: 'center' },
  row: { position: 'relative', justifyContent: 'center' },
  block: { position: 'absolute', top: 3, borderRadius: 5, overflow: 'hidden', justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(0,0,0,0.35)' },
  videoBlock: { backgroundColor: colors.accentSoft },
  blockLabel: { position: 'absolute', left: 4, bottom: 1, textShadowColor: '#000', textShadowRadius: 3 },
  blockText: { paddingHorizontal: 4 },
  emptyRow: { paddingLeft: 4 },
  feedBox: { backgroundColor: colors.background, borderRadius: radius.md },
  feedFixed: { maxHeight: 300, minHeight: 140 },
  feedFill: { flex: 1, minHeight: 140 },
  feedContent: { padding: spacing.sm, gap: spacing.sm },
  thought: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  agentChip: { backgroundColor: colors.accentSoft, borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 2, maxWidth: 120 },
  thoughtText: { flex: 1 },
  typing: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  dots: { minWidth: 24 },
});
