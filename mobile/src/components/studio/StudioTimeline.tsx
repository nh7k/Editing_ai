import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Animated,
  Easing,
  Image,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
  type LayoutChangeEvent,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';

import { api } from '../../api/client';
import type { Waveform } from '../../api/types';
import { queueLabel } from '../../utils/liveTimeline';
import {
  cutSchedule,
  filmstripCrop,
  formatTimecode,
  fxChipLabel,
  pxPerSecond,
  revealOffsets,
  rulerTicks,
  shotPopAt,
  slicePeaks,
  snapTime,
  songLabel,
  spanOf,
  staggerDelay,
  type CutSchedule,
  type KeptRange,
  type RawClip,
  type RawRange,
  type StudioLiveItem,
  type StudioSegment,
  type StudioTimelineModel,
} from '../../utils/studioTimeline';
import { AppText } from '../AppText';
import { useStudioSkia, type StudioSkiaParts } from './skia/useStudioSkia';
import { studio } from './theme';
import { IconButton } from './ui';

export const FILMSTRIP_FRAMES = 10;
const LABEL_W = 160;
const RULER_H = 30;
const TEXT_H = 30;
const GRAPHIC_H = 38;
const MAIN_H = 76;
const SEG_LABEL_H = 16;
const FILM_H = 38;
const WAVE_H = MAIN_H - SEG_LABEL_H - FILM_H - 4;
const MIN_ZOOM = 1;
const MAX_ZOOM = 8;
const SLIDER_W = 110;
const FX_H = 30;
const MUSIC_H = 30;
const NATIVE_DRIVER = Platform.OS !== 'web';
/** How long one block takes to pop in (ms). */
const POP_MS = 340;
/** A ticker line stays at least this long, so a burst of thoughts reads one by one (ms). */
const TICKER_MIN_MS = 900;
/** How long an effect's label chip floats above its block (ms). */
const CHIP_HOLD_MS = 1400;
/** Width of the timeline comment box (px). */
const COMMENT_W = 300;
/** Hold this long on the timeline to open a comment box (ms). */
const LONG_PRESS_MS = 450;
export const COMMENT_PLACEHOLDER = 'Is moment pe kya karna hai? e.g. zoom, WOW likh do, rose ka sticker, ye part hata do';

/** A comment the user pinned on the timeline this session (sent as an edit for that moment). */
export interface TimelineComment {
  key: string;
  /** Seconds in the edited output. */
  at: number;
  text: string;
}

/** "12.4s": how a comment's moment is shown. */
export function commentTimeLabel(at: number): string {
  return `${(Math.round(at * 10) / 10).toFixed(1)}s`;
}

/**
 * Wall-clock time (ms) when `sig` last changed: the start of the current cut animation. Blocks that arrive later
 * (text / fx a second after the cut) are scheduled against it, so effects appear one by one AFTER the cut.
 */
function useAnchor(sig: string): number {
  const [anchor, setAnchor] = useState(() => ({ sig, at: Date.now() }));
  if (anchor.sig !== sig) {
    // "adjust state when a prop changes": the clock is read once per new video track, not on every render
    // eslint-disable-next-line react-hooks/purity
    const next = { sig, at: Date.now() };
    setAnchor(next);
    return next.at;
  }
  return anchor.at;
}

export interface StudioTimelineProps {
  projectId: string;
  model: StudioTimelineModel;
  /** Current playback time (seconds). */
  currentTime: number;
  /** Duration shown in the timecode (rendered output when known). */
  duration: number;
  playing: boolean;
  onTogglePlay: () => void;
  onSeek: (seconds: number) => void;
  waveforms: Record<string, Waveform>;
  /**
   * Timeline comments: a click (while paused) or a long-press on the tracks opens a small box for that moment;
   * what the user writes is sent as an edit for that moment only. Off when not given (or while the agents edit).
   */
  onComment?: (text: string, at: number) => void;
  /** Comments sent this session, shown as pins on the ruler. */
  comments?: TimelineComment[];
}

export function StudioTimeline({
  projectId,
  model,
  currentTime,
  duration,
  playing,
  onTogglePlay,
  onSeek,
  waveforms,
  onComment,
  comments = [],
}: StudioTimelineProps) {
  const skia = useStudioSkia();
  const live = model.live;
  // live: always one FX lane, so the user sees where effects will land
  const fxLanes: StudioLiveItem[][] = live ? (live.fxLanes.length ? live.fxLanes : [[]]) : [];
  const music = live?.music ?? [];
  const [viewW, setViewW] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [snap, setSnap] = useState(true);
  const [dragTime, setDragTime] = useState<number | null>(null);

  const total = Math.max(model.total, 0.001);
  const pps = pxPerSecond(total, viewW, zoom);
  const contentW = Math.max(viewW, total * pps);
  const ticks = useMemo(() => rulerTicks(model.total, pps), [model.total, pps]);

  // ---- live: raw footage → cut animation → effects one by one → render / review progress ----
  const segs = model.segments;
  const hasVideo = !!live && segs.length > 0;
  const showRaw = !!live && live.raw.length > 0 && live.rawTotal > 0;
  const animateCut = !!live && hasVideo && showRaw && live.kept.length > 0;
  const anchor = useAnchor(live ? live.videoSig : '');
  const sched = useMemo(() => cutSchedule(animateCut ? segs.length : 0), [animateCut, segs.length]);
  const cutDone = animateCut ? sched.doneMs : hasVideo ? staggerDelay(segs.length - 1, segs.length) + POP_MS : 0;
  const reveal = useMemo(() => (live ? revealOffsets(model, cutDone) : {}), [live, model, cutDone]);
  const revealAt = (key: string) => anchor + (reveal[key] ?? cutDone);
  const rawPps = showRaw && live ? contentW / live.rawTotal : 0;
  const phase = live?.phase ?? 'working';
  const doneCount = live?.render.doneCount ?? 0;
  const renderX = doneCount > 0 ? segs[Math.min(doneCount, segs.length) - 1].end * pps : 0;
  const cursor: { x: number; loop: boolean; label: string } | null = !live
    ? null
    : phase === 'reviewing'
      ? { x: model.total * pps, loop: true, label: 'AI review sweep' }
      : phase === 'rendering' && hasVideo
        ? { x: renderX, loop: false, label: 'AI render cursor' }
        : phase === 'working' && !hasVideo && showRaw
          ? { x: model.total * pps, loop: true, label: 'AI watching the raw footage' }
          : { x: live.buildEnd * pps, loop: false, label: 'AI build cursor' };

  const toTime = (x: number) => {
    if (pps <= 0) return 0;
    const t = Math.max(0, Math.min(model.total, x / pps));
    return snap ? snapTime(model, t, 8 / pps) : t;
  };

  // ---- timeline comments: pause, pick the moment, write what to do there ----
  const [commentAt, setCommentAt] = useState<number | null>(null);
  const [commentText, setCommentText] = useState('');
  const [hoverComment, setHoverComment] = useState<string | null>(null);
  const canComment = !!onComment && !live && model.total > 0;
  const openComment = (t: number) => {
    if (!canComment) return;
    if (playing) onTogglePlay(); // stop at that moment while the user writes
    setCommentAt(Math.max(0, Math.min(model.total, t)));
    setCommentText('');
  };
  const closeComment = () => {
    setCommentAt(null);
    setCommentText('');
  };
  const sendComment = () => {
    const text = commentText.trim();
    if (!text || commentAt === null || !onComment) return;
    onComment(text, commentAt);
    closeComment();
  };

  const pan = Gesture.Pan()
    .runOnJS(true)
    .minDistance(0)
    .onBegin((e) => setDragTime(toTime(e.x)))
    .onUpdate((e) => setDragTime(toTime(e.x)))
    .onFinalize((e) => {
      onSeek(toTime(e.x));
      setDragTime(null);
    });
  // long-press anywhere (playing or not): pause + comment box at that time
  const longPress = Gesture.LongPress()
    .runOnJS(true)
    .minDuration(LONG_PRESS_MS)
    .withTestId('timeline-long-press')
    .onStart((e) => openComment(toTime(e.x)));
  // a plain click while paused: comment box at the clicked time (while playing a click just seeks)
  const tap = Gesture.Tap()
    .runOnJS(true)
    .withTestId('timeline-tap')
    .onEnd((e, success) => {
      if (success && !playing) openComment(toTime(e.x));
    });
  const trackGesture = Gesture.Simultaneous(pan, tap, longPress);

  const playheadT = dragTime ?? Math.min(currentTime, model.total);
  const onLayout = (e: LayoutChangeEvent) => setViewW(e.nativeEvent.layout.width);
  const setZoomFromSlider = (x: number) => setZoom(MIN_ZOOM + Math.max(0, Math.min(1, x / SLIDER_W)) * (MAX_ZOOM - MIN_ZOOM));
  const zoomFrac = (zoom - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM);

  return (
    <View style={styles.wrap} testID="studio-timeline">
      <View style={styles.toolbar}>
        <Pressable
          onPress={onTogglePlay}
          accessibilityRole="button"
          accessibilityLabel={playing ? 'Pause' : 'Play'}
          testID="transport-play"
          style={styles.play}
        >
          <AppText size="md" weight="bold" color={studio.bg}>
            {playing ? '❚❚' : '▶'}
          </AppText>
        </Pressable>
        <AppText size="md" weight="medium" testID="timecode">
          {formatTimecode(playheadT)}{' '}
          <AppText size="md" color={studio.muted}>
            / {formatTimecode(duration)}
          </AppText>
        </AppText>
        <View style={styles.trackSelect}>
          <AppText size="sm" weight="semibold">
            Main ▾
          </AppText>
        </View>
        {live ? (
          <View style={styles.liveBadge} testID="timeline-live-badge">
            <ActivityIndicator size="small" color={studio.cyan} />
            <AppText size="xs" weight="semibold" color={studio.cyan}>
              AI editing…
            </AppText>
            {live.color ? <ColorChip key={live.color} label={live.color} at={revealAt('color')} /> : null}
          </View>
        ) : null}
        {live ? <Ticker text={live.ticker} /> : null}
        {live && phase === 'queued' ? (
          <View style={styles.queueChip} testID="timeline-queue">
            <AppText size="xs" weight="semibold" color={studio.text} numberOfLines={1}>
              {queueLabel(live.queuePosition)}
            </AppText>
          </View>
        ) : null}
        <IconButton glyph="⫿" label="Split (coming soon)" disabled />
        <IconButton glyph="⧉" label="Duplicate (coming soon)" disabled />
        <IconButton glyph="⌫" label="Delete (coming soon)" disabled />
        <IconButton
          glyph="📍"
          label="Comment at the playhead"
          disabled={!canComment}
          onPress={() => openComment(playheadT)}
          testID="timeline-comment-open"
        />
        <View style={styles.spacer} />
        <IconButton
          glyph="∩"
          label={snap ? 'Snapping on' : 'Snapping off'}
          active={snap}
          onPress={() => setSnap((s) => !s)}
          testID="snap-toggle"
        />
        <IconButton glyph="−" label="Zoom timeline out" onPress={() => setZoom((z) => Math.max(MIN_ZOOM, z / 1.5))} />
        <Pressable
          onPress={(e) => setZoomFromSlider(e.nativeEvent.locationX)}
          accessibilityRole="adjustable"
          accessibilityLabel="Timeline zoom"
          accessibilityValue={{ min: MIN_ZOOM, max: MAX_ZOOM, now: Math.round(zoom * 10) / 10 }}
          testID="timeline-zoom"
          style={styles.slider}
        >
          <View style={styles.sliderTrack} />
          <View style={[styles.sliderFill, { width: Math.max(6, zoomFrac * SLIDER_W) }]} />
        </Pressable>
        <IconButton glyph="+" label="Zoom timeline in" onPress={() => setZoom((z) => Math.min(MAX_ZOOM, z * 1.5))} />
      </View>

      <View style={styles.body}>
        <View style={styles.labels}>
          <View style={{ height: RULER_H }} />
          <TrackLabel glyph="T" label="Text" height={TEXT_H} />
          {model.overlays.map((o, i) => (
            <TrackLabel key={o.key} glyph="◈" label={`Graphic track ${i + 1}`} height={GRAPHIC_H} />
          ))}
          {fxLanes.map((_, i) => (
            <TrackLabel key={`fx${i}`} glyph="✦" label={fxLanes.length > 1 ? `FX track ${i + 1}` : 'FX track'} height={FX_H} />
          ))}
          <TrackLabel glyph="▶" label="Main" height={MAIN_H} strong />
          {music.length ? <TrackLabel glyph="♪" label="Music" height={MUSIC_H} /> : null}
        </View>

        <View style={styles.tracksView} onLayout={onLayout} testID="timeline-view">
          <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={{ width: contentW }}>
            <View style={{ width: contentW }}>
              <GestureDetector gesture={trackGesture}>
                <View
                  style={{ width: contentW }}
                  testID="timeline-tracks"
                  accessibilityLabel={
                    canComment
                      ? 'Timeline. Drag to move the playhead; pause and click, or long-press, to comment on a moment.'
                      : 'Timeline. Click or drag to move the playhead.'
                  }
                >
                  <View style={styles.ruler} testID="timeline-ruler">
                    {ticks.map((t) => (
                      <View key={t.t} style={[styles.tick, { left: t.t * pps }]}>
                        <View style={styles.tickMark} />
                        <AppText size="xs" color={studio.muted} style={styles.tickLabel}>
                          {t.label}
                        </AppText>
                      </View>
                    ))}
                  </View>

                  {live?.render.shimmer ? <RenderShimmer width={contentW} /> : null}

                  <View style={[styles.row, { height: TEXT_H }]} testID="text-track">
                    {model.text.map((t, i) => {
                      const s = spanOf(t.start, t.end, pps);
                      return (
                        <Pop
                          key={t.key}
                          animate={!!live}
                          delay={staggerDelay(i, model.text.length)}
                          at={live ? revealAt(t.key) : undefined}
                          style={[styles.textPill, { left: s.x, width: s.width }]}
                          testID={live ? `live-text-${i}` : undefined}
                        >
                          <AppText size="xs" weight="semibold" numberOfLines={1} color={studio.text}>
                            {t.kind === 'watermark' ? '◎ ' : t.kind === 'title' ? '▣ ' : '“ '}
                            {t.label}
                          </AppText>
                        </Pop>
                      );
                    })}
                    {live
                      ? model.text.map((t, i) => (
                          <LabelChip
                            key={`chip-${t.key}`}
                            x={t.start * pps}
                            label={`T ${t.label}`}
                            at={revealAt(t.key)}
                            testID={`live-chip-text-${i}`}
                          />
                        ))
                      : null}
                  </View>

                  {model.overlays.map((o) => {
                    const s = spanOf(o.start, o.end, pps);
                    return (
                      <View key={o.key} style={[styles.row, { height: GRAPHIC_H }]} testID="graphic-track">
                        <View style={[styles.graphicPill, { left: s.x, width: s.width }]}>
                          <AppText size="sm" weight="semibold" numberOfLines={1} color="#FFFFFF">
                            ▪ {o.label}
                          </AppText>
                        </View>
                      </View>
                    );
                  })}

                  {fxLanes.map((lane, li) => (
                    <View key={`fx${li}`} style={[styles.row, { height: FX_H }]} testID={`live-fx-track-${li}`}>
                      {lane.map((x, i) => {
                        const s = spanOf(x.start, x.end, pps, 6);
                        return (
                          <Pop
                            key={x.key}
                            animate
                            delay={staggerDelay(i, lane.length)}
                            at={revealAt(x.key)}
                            style={[styles.fxPill, { left: s.x, width: s.width }]}
                            testID={`live-fx-${li}-${i}`}
                          >
                            {s.width > 26 ? (
                              <AppText size="xs" weight="semibold" numberOfLines={1} color={studio.white}>
                                {x.label}
                              </AppText>
                            ) : null}
                          </Pop>
                        );
                      })}
                      {lane.map((x, i) => (
                        <LabelChip
                          key={`chip-${x.key}`}
                          x={x.start * pps}
                          label={fxChipLabel(x.label)}
                          at={revealAt(x.key)}
                          testID={`live-chip-fx-${li}-${i}`}
                        />
                      ))}
                    </View>
                  ))}

                  <View style={[styles.row, { height: MAIN_H }]} testID="main-track">
                    {live && showRaw && (!hasVideo || animateCut) ? (
                      <RawFootage
                        key={`raw-${live.videoSig}`}
                        projectId={projectId}
                        raw={live.raw}
                        rawPps={rawPps}
                        kept={hasVideo ? live.kept : []}
                        gaps={hasVideo ? live.gaps : []}
                        cutPoints={hasVideo ? live.cutPoints : []}
                        sched={sched}
                        cutting={animateCut}
                        queued={phase === 'queued'}
                      />
                    ) : null}
                    {model.segments.map((seg, i) => (
                      <MainSegment
                        key={seg.key}
                        seg={seg}
                        pps={pps}
                        projectId={projectId}
                        waveform={waveforms[seg.clipId]}
                        skia={skia}
                        animate={!!live}
                        delay={animateCut ? shotPopAt(sched, i) : staggerDelay(i, model.segments.length)}
                        renderDone={live ? i < doneCount : false}
                        index={i}
                      />
                    ))}
                    {animateCut && live && pps > 0 && rawPps > 0
                      ? live.kept.map((k) => (
                          <CutGhost
                            key={`ghost-${live.videoSig}-${k.index}`}
                            projectId={projectId}
                            kept={k}
                            raw={live.raw}
                            rawPps={rawPps}
                            pps={pps}
                            delay={sched.highlightMs + k.index * sched.step}
                            morphMs={sched.morphMs}
                          />
                        ))
                      : null}
                    {live?.render.reuse ? (
                      <View pointerEvents="none" style={styles.reuseNote} testID="live-render-reuse">
                        <AppText size="xs" weight="semibold" color={studio.bg} numberOfLines={1}>
                          ✓ cut wahi hai, sirf text/gaana
                        </AppText>
                      </View>
                    ) : null}
                    {model.segments.length === 0 && !showRaw ? (
                      <AppText
                        size="sm"
                        color={live ? studio.cyan : studio.muted}
                        style={styles.emptyMain}
                        testID={live ? 'live-main-empty' : undefined}
                      >
                        {live ? 'Agent clips kaat raha hai…' : 'Add clips to see them on the timeline.'}
                      </AppText>
                    ) : null}
                  </View>

                  {music.length ? (
                    <View style={[styles.row, { height: MUSIC_H }]} testID="live-music-track">
                      {music.map((x, i) => {
                        const s = spanOf(x.start, x.end, pps, 6);
                        return (
                          <Pop
                            key={x.key}
                            animate
                            delay={staggerDelay(i, music.length)}
                            at={revealAt(x.key)}
                            style={[styles.musicPill, { left: s.x, width: s.width }]}
                            testID={`live-music-${i}`}
                          >
                            <AppText size="xs" weight="semibold" numberOfLines={1} color={studio.bg}>
                              ♪ {x.label}
                            </AppText>
                          </Pop>
                        );
                      })}
                      {music.map((x, i) => (
                        <LabelChip
                          key={`chip-${x.key}`}
                          x={x.start * pps}
                          label={`♪ ${songLabel(x.label)}`}
                          at={revealAt(x.key)}
                          testID={`live-chip-music-${i}`}
                        />
                      ))}
                    </View>
                  ) : null}

                  {live && cursor ? (
                    <BuildCursor
                      x={cursor.x}
                      loop={cursor.loop}
                      label={cursor.label}
                      revision={live.revision}
                      sweepMs={
                        animateCut ? cutDone : staggerDelay(live.buildCount - 1, live.buildCount) + POP_MS
                      }
                    />
                  ) : pps > 0 ? (
                    <View pointerEvents="none" style={[styles.playhead, { left: playheadT * pps - 1 }]} testID="playhead">
                      <View style={styles.playheadKnob} />
                    </View>
                  ) : null}
                </View>
              </GestureDetector>

              {/* outside the gesture area: clicking a pin / typing in the box must not seek */}
              {pps > 0 && comments.length ? (
                <View pointerEvents="box-none" style={styles.commentPins} testID="timeline-comment-pins">
                  {comments.map((c, i) => (
                    <Pressable
                      key={c.key}
                      onPress={() => onSeek(c.at)}
                      onHoverIn={() => setHoverComment(c.key)}
                      onHoverOut={() => setHoverComment((k) => (k === c.key ? null : k))}
                      accessibilityRole="button"
                      accessibilityLabel={`Comment @ ${commentTimeLabel(c.at)}: ${c.text}`}
                      testID={`timeline-comment-marker-${i}`}
                      style={[styles.commentPin, { left: c.at * pps - 6 }]}
                    >
                      <View style={styles.commentPinDot} />
                      <View style={styles.commentPinStem} />
                      {hoverComment === c.key ? (
                        <View style={styles.commentTip} testID={`timeline-comment-tip-${i}`}>
                          <AppText size="xs" weight="semibold" color={studio.bg} numberOfLines={2}>
                            {commentTimeLabel(c.at)}: {c.text}
                          </AppText>
                        </View>
                      ) : null}
                    </Pressable>
                  ))}
                </View>
              ) : null}

              {commentAt !== null && canComment ? (
                <>
                  <View pointerEvents="none" style={[styles.commentLine, { left: commentAt * pps - 1 }]} />
                  <View
                    style={[
                      styles.commentBox,
                      { left: Math.max(0, Math.min(contentW - COMMENT_W, commentAt * pps - 16)) },
                    ]}
                    testID="timeline-comment-box"
                  >
                    <View style={styles.commentHead}>
                      <AppText size="xs" weight="bold" color={studio.cyan} testID="timeline-comment-time">
                        📍 @ {commentTimeLabel(commentAt)}
                      </AppText>
                      <View style={styles.spacer} />
                      <Pressable
                        onPress={closeComment}
                        accessibilityRole="button"
                        accessibilityLabel="Cancel comment"
                        testID="timeline-comment-cancel"
                        style={styles.commentClose}
                      >
                        <AppText size="sm" color={studio.muted}>
                          ✕
                        </AppText>
                      </Pressable>
                    </View>
                    <View style={styles.commentRow}>
                      <TextInput
                        value={commentText}
                        onChangeText={setCommentText}
                        placeholder={COMMENT_PLACEHOLDER}
                        placeholderTextColor={studio.muted}
                        style={styles.commentInput}
                        onSubmitEditing={sendComment}
                        autoFocus
                        testID="timeline-comment-input"
                      />
                      <Pressable
                        onPress={sendComment}
                        disabled={!commentText.trim()}
                        accessibilityRole="button"
                        accessibilityLabel="Add comment"
                        accessibilityState={{ disabled: !commentText.trim() }}
                        testID="timeline-comment-send"
                        style={[styles.commentSend, !commentText.trim() && styles.commentSendOff]}
                      >
                        <AppText size="sm" weight="bold" color={studio.white}>
                          Add
                        </AppText>
                      </Pressable>
                    </View>
                  </View>
                </>
              ) : null}
            </View>
          </ScrollView>
        </View>
      </View>
    </View>
  );
}

function TrackLabel({ glyph, label, height, strong }: { glyph: string; label: string; height: number; strong?: boolean }) {
  return (
    <View style={[styles.trackLabel, { height }, strong && styles.trackLabelMain]}>
      <AppText size="sm" color={studio.muted}>
        {glyph}
      </AppText>
      <AppText size="sm" weight={strong ? 'semibold' : 'medium'} numberOfLines={1}>
        {label}
      </AppText>
    </View>
  );
}

/**
 * A timeline block. With `animate` (live mode) it pops in when it mounts — fades, grows and drops into
 * place after `delay` ms — so a track fills left → right like an editor placing clips. A re-cut track's
 * blocks have new keys, so they mount fresh and pop in again.
 */
function Pop({
  animate,
  delay = 0,
  at,
  style,
  testID,
  children,
}: {
  animate: boolean;
  delay?: number;
  /** Wall-clock time (ms) to pop at instead of `delay` (blocks scheduled after the cut animation). */
  at?: number;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  children?: ReactNode;
}) {
  const [v] = useState(() => new Animated.Value(animate ? 0 : 1));
  // the schedule is fixed when the block mounts (a re-render must not restart it halfway)
  const [when] = useState(() => ({ delay, at }));
  useEffect(() => {
    if (!animate) return;
    const wait = when.at !== undefined ? Math.max(0, when.at - Date.now()) : when.delay;
    const anim = Animated.timing(v, {
      toValue: 1,
      duration: POP_MS,
      delay: wait,
      easing: Easing.out(Easing.back(1.4)),
      useNativeDriver: NATIVE_DRIVER,
    });
    anim.start();
    return () => anim.stop();
  }, [v, animate, when]);
  if (!animate) {
    return (
      <View style={style} testID={testID}>
        {children}
      </View>
    );
  }
  const scale = v.interpolate({ inputRange: [0, 1], outputRange: [0.6, 1] });
  const translateY = v.interpolate({ inputRange: [0, 1], outputRange: [-14, 0] });
  const opacity = v.interpolate({ inputRange: [0, 0.4, 1], outputRange: [0, 0.9, 1], extrapolate: 'clamp' });
  return (
    <Animated.View style={[style, { opacity, transform: [{ translateY }, { scale }] }]} testID={testID}>
      {children}
    </Animated.View>
  );
}

/**
 * Glowing "build cursor" of live mode: sweeps from the start to the end of the newest block (in step with
 * the blocks popping in) whenever a track changes, follows zoom / resize, and pulses while the agents work.
 */
function BuildCursor({
  x,
  revision,
  sweepMs,
  loop = false,
  label = 'AI build cursor',
}: {
  x: number;
  revision: string;
  sweepMs: number;
  /** Sweep 0 → x over and over (the agent watching the footage / reviewing the result). */
  loop?: boolean;
  label?: string;
}) {
  const [pos] = useState(() => new Animated.Value(0));
  const [pulse] = useState(() => new Animated.Value(0));
  const lastRevision = useRef<string | null>(null);

  useEffect(() => {
    if (loop) {
      lastRevision.current = null; // leaving the loop sweeps the cursor in again
      pos.setValue(0);
      const anim = Animated.loop(
        Animated.sequence([
          Animated.timing(pos, { toValue: Math.max(0, x), duration: 1800, easing: Easing.inOut(Easing.quad), useNativeDriver: NATIVE_DRIVER }),
          Animated.timing(pos, { toValue: 0, duration: 0, useNativeDriver: NATIVE_DRIVER }),
        ]),
      );
      anim.start();
      return () => anim.stop();
    }
    const sweep = lastRevision.current !== revision;
    lastRevision.current = revision;
    if (sweep) pos.setValue(0);
    const anim = Animated.timing(pos, {
      toValue: Math.max(0, x),
      duration: sweep ? Math.max(400, sweepMs) : 250,
      easing: Easing.inOut(Easing.cubic),
      useNativeDriver: NATIVE_DRIVER,
    });
    anim.start();
    return () => anim.stop();
  }, [pos, x, revision, sweepMs, loop]);

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: NATIVE_DRIVER }),
        Animated.timing(pulse, { toValue: 0, duration: 700, useNativeDriver: NATIVE_DRIVER }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  const glow = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0.9] });
  return (
    <Animated.View
      pointerEvents="none"
      style={[styles.buildCursor, { transform: [{ translateX: pos }] }]}
      testID="build-cursor"
      accessibilityLabel={label}
    >
      <Animated.View style={[styles.buildGlow, { opacity: glow }]} />
      <View style={styles.buildLine} />
      <View style={styles.buildKnob}>
        <AppText size="xs" weight="bold" color={studio.bg}>
          AI
        </AppText>
      </View>
    </Animated.View>
  );
}

function MainSegment({
  seg,
  pps,
  projectId,
  waveform,
  skia,
  animate = false,
  delay = 0,
  renderDone = false,
  index = 0,
}: {
  seg: StudioSegment;
  pps: number;
  projectId: string;
  waveform?: Waveform;
  skia: StudioSkiaParts | null;
  animate?: boolean;
  delay?: number;
  /** Live: this shot is rendered (✓ badge + green glow). */
  renderDone?: boolean;
  index?: number;
}) {
  const s = spanOf(seg.start, seg.end, pps);
  const crop = filmstripCrop(seg, s.width);
  const peaks = waveform ? slicePeaks(waveform.peaks, waveform.duration || seg.clipDuration, seg.in, seg.out) : [];
  const isLive = seg.thumb !== undefined;
  const thumb = seg.thumb ? api.mediaUrl(seg.thumb) : null;
  return (
    <Pop
      animate={animate}
      delay={delay}
      style={[styles.segment, isLive && styles.segmentLive, renderDone && styles.segmentDone, { left: s.x, width: s.width }]}
      testID={`segment-${seg.key}`}
    >
      {renderDone ? (
        <Pop animate style={styles.doneBadge} testID={`live-render-done-${index}`}>
          <AppText size="xs" weight="bold" color={studio.bg}>
            ✓
          </AppText>
        </Pop>
      ) : null}
      <AppText size="xs" weight="semibold" numberOfLines={1} color={studio.white} style={styles.segLabel}>
        {isLive ? `${(seg.end - seg.start).toFixed(1)}s · ${seg.label}` : seg.label}
      </AppText>
      <View style={styles.film}>
        {isLive ? (
          thumb ? (
            <Image source={{ uri: thumb }} style={StyleSheet.absoluteFill} resizeMode="cover" testID={`live-thumb-${seg.key}`} />
          ) : null
        ) : (
          <Image
            source={{ uri: api.filmstripUrl(projectId, seg.clipId, FILMSTRIP_FRAMES) }}
            style={{ position: 'absolute', left: crop.offsetX, top: 0, width: crop.stripWidth, height: FILM_H }}
            resizeMode="stretch"
            testID={`filmstrip-${seg.key}`}
          />
        )}
      </View>
      <View style={styles.wave}>
        {skia && peaks.length ? (
          <skia.WaveformBars width={Math.max(1, s.width - 4)} height={WAVE_H} peaks={peaks} color="#9CC8FF" />
        ) : (
          <View style={styles.waveLine} />
        )}
      </View>
    </Pop>
  );
}

/**
 * One-line "what the agent is doing right now". New lines slide in; a burst of changes (all of the agents'
 * thoughts land within ~1.5 s) is queued so each line stays ≥ TICKER_MIN_MS, skipping to the newest when behind.
 */
function Ticker({ text }: { text: string }) {
  const [shown, setShown] = useState(text);
  const lastQueued = useRef(text);
  const pending = useRef<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shownAt = useRef(0);
  const [v] = useState(() => new Animated.Value(1));

  useEffect(() => {
    if (text === lastQueued.current) return;
    lastQueued.current = text;
    pending.current.push(text);
    if (pending.current.length > 3) pending.current.splice(0, pending.current.length - 3);
    const pump = () => {
      timer.current = null;
      const next = pending.current.shift();
      if (next === undefined) return;
      shownAt.current = Date.now();
      setShown(next);
      if (pending.current.length) timer.current = setTimeout(pump, TICKER_MIN_MS);
    };
    if (!timer.current) timer.current = setTimeout(pump, Math.max(0, shownAt.current + TICKER_MIN_MS - Date.now()));
  }, [text]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  useEffect(() => {
    v.setValue(0);
    const anim = Animated.timing(v, { toValue: 1, duration: 260, easing: Easing.out(Easing.cubic), useNativeDriver: NATIVE_DRIVER });
    anim.start();
    return () => anim.stop();
  }, [shown, v]);

  const translateY = v.interpolate({ inputRange: [0, 1], outputRange: [8, 0] });
  return (
    <View style={styles.ticker} testID="timeline-ticker" accessibilityLiveRegion="polite" accessibilityLabel={shown}>
      <Animated.View style={{ opacity: v, transform: [{ translateY }] }}>
        <AppText size="xs" weight="medium" color={studio.text} numberOfLines={1}>
          {shown}
        </AppText>
      </Animated.View>
    </View>
  );
}

/** Colour chip of the header: appears at its turn after the cut and pulses (mounts fresh for a new look). */
function ColorChip({ label, at }: { label: string; at: number }) {
  const [v] = useState(() => new Animated.Value(0));
  const [startAt] = useState(at);
  useEffect(() => {
    const anim = Animated.sequence([
      Animated.delay(Math.max(0, startAt - Date.now())),
      Animated.timing(v, { toValue: 1, duration: 220, easing: Easing.out(Easing.quad), useNativeDriver: NATIVE_DRIVER }),
      Animated.timing(v, { toValue: 2, duration: 260, easing: Easing.inOut(Easing.quad), useNativeDriver: NATIVE_DRIVER }),
    ]);
    anim.start();
    return () => anim.stop();
  }, [v, startAt]);
  const scale = v.interpolate({ inputRange: [0, 1, 2], outputRange: [0.6, 1.3, 1] });
  const opacity = v.interpolate({ inputRange: [0, 0.5, 2], outputRange: [0, 1, 1] });
  return (
    <Animated.View style={[styles.colorChip, { opacity, transform: [{ scale }] }]} testID="timeline-live-color">
      <AppText size="xs" weight="semibold" color={studio.text}>
        🎨 {label}
      </AppText>
    </Animated.View>
  );
}

/**
 * Short label floating above an effect block when it appears ("⚡ flash", "T Goa Trip"), then fading away.
 * Decorative (the block itself carries the text), so it is hidden from screen readers.
 */
function LabelChip({ x, label, at, testID }: { x: number; label: string; at: number; testID?: string }) {
  const [v] = useState(() => new Animated.Value(0));
  const [startAt] = useState(at);
  useEffect(() => {
    const anim = Animated.sequence([
      Animated.delay(Math.max(0, startAt - Date.now())),
      Animated.timing(v, { toValue: 1, duration: 200, easing: Easing.out(Easing.quad), useNativeDriver: NATIVE_DRIVER }),
      Animated.delay(CHIP_HOLD_MS),
      Animated.timing(v, { toValue: 2, duration: 400, useNativeDriver: NATIVE_DRIVER }),
    ]);
    anim.start();
    return () => anim.stop();
  }, [v, startAt]);
  const opacity = v.interpolate({ inputRange: [0, 1, 2], outputRange: [0, 1, 0] });
  const translateY = v.interpolate({ inputRange: [0, 1, 2], outputRange: [6, 0, -6] });
  return (
    <Animated.View
      pointerEvents="none"
      aria-hidden
      style={[styles.labelChip, { left: Math.max(0, x), opacity, transform: [{ translateY }] }]}
      testID={testID}
    >
      <AppText size="xs" weight="bold" color={studio.bg} numberOfLines={1}>
        {label}
      </AppText>
    </Animated.View>
  );
}

/**
 * The project's raw clips end-to-end on the Main track (dimmed, "Raw footage") until the cut lands. When it does:
 * the parts the agent kept light up one by one, the parts it cut away go dark with ✂ at each cut, and the layer
 * fades once the kept pieces have slid into the edit (CutGhost). Keyed by the video track, so a re-cut replays it.
 */
function RawFootage({
  projectId,
  raw,
  rawPps,
  kept,
  gaps,
  cutPoints,
  sched,
  cutting,
  queued,
}: {
  projectId: string;
  raw: RawClip[];
  rawPps: number;
  kept: KeptRange[];
  gaps: RawRange[];
  cutPoints: number[];
  sched: CutSchedule;
  cutting: boolean;
  queued: boolean;
}) {
  const [fade] = useState(() => new Animated.Value(1));
  const [dark] = useState(() => new Animated.Value(0));
  useEffect(() => {
    if (!cutting) return;
    const anim = Animated.parallel([
      Animated.timing(dark, { toValue: 1, duration: 300, delay: 250, useNativeDriver: NATIVE_DRIVER }),
      Animated.timing(fade, { toValue: 0, duration: 350, delay: sched.doneMs, useNativeDriver: NATIVE_DRIVER }),
    ]);
    anim.start();
    return () => anim.stop();
  }, [cutting, dark, fade, sched.doneMs]);

  if (!(rawPps > 0)) {
    return (
      <View pointerEvents="none" style={styles.rawLayer} testID="live-raw-track">
        <RawLabel queued={queued} />
      </View>
    );
  }
  const markEvery = cutPoints.length > 1 ? Math.min(40, 400 / (cutPoints.length - 1)) : 0;
  return (
    <Animated.View pointerEvents="none" style={[styles.rawLayer, { opacity: fade }]} testID="live-raw-track">
      {raw.map((r, i) => {
        const left = r.start * rawPps;
        const width = Math.max(2, (r.end - r.start) * rawPps);
        return (
          <View key={`${r.clipId}-${i}`} style={[styles.rawClip, { left, width }]} testID={`live-raw-clip-${i}`}>
            <Image
              source={{ uri: api.filmstripUrl(projectId, r.clipId, FILMSTRIP_FRAMES) }}
              style={styles.rawFilm}
              resizeMode="stretch"
              testID={`live-raw-film-${i}`}
            />
            <AppText size="xs" numberOfLines={1} color={studio.muted} style={styles.rawName}>
              {r.label}
            </AppText>
          </View>
        );
      })}
      {gaps.map((g, i) => (
        <Animated.View
          key={`gap-${i}`}
          style={[styles.cutGap, { left: g.start * rawPps, width: Math.max(1, (g.end - g.start) * rawPps), opacity: dark }]}
          testID={`live-cut-gap-${i}`}
        />
      ))}
      {kept.map((k, i) => (
        <Pop
          key={`kept-${k.index}`}
          animate
          delay={i * sched.highlightStep}
          style={[styles.keptBox, { left: k.rawStart * rawPps, width: Math.max(2, (k.rawEnd - k.rawStart) * rawPps) }]}
          testID={`live-kept-${k.index}`}
        />
      ))}
      {cutPoints.map((t, i) => (
        <Pop
          key={`cut-${i}`}
          animate
          delay={300 + Math.round(i * markEvery)}
          style={[styles.cutMark, { left: t * rawPps - 7 }]}
          testID={`live-cut-mark-${i}`}
        >
          <View style={styles.cutLine} />
          <AppText size="xs" weight="bold" color={studio.red} style={styles.cutGlyph}>
            ✂
          </AppText>
        </Pop>
      ))}
      <RawLabel queued={queued} />
    </Animated.View>
  );
}

function RawLabel({ queued }: { queued: boolean }) {
  return (
    <View style={styles.rawLabel} testID="live-raw-label">
      <AppText size="xs" weight="semibold" color={studio.text}>
        {queued ? 'Raw footage · line me' : 'Raw footage'}
      </AppText>
    </View>
  );
}

/**
 * A kept piece of raw footage sliding from its place on the raw strip to its place in the edit (translateX +
 * scaleX only: no layout work per frame), then fading as the edited block pops in under it.
 */
function CutGhost({
  projectId,
  kept,
  raw,
  rawPps,
  pps,
  delay,
  morphMs,
}: {
  projectId: string;
  kept: KeptRange;
  raw: RawClip[];
  rawPps: number;
  pps: number;
  delay: number;
  morphMs: number;
}) {
  const [v] = useState(() => new Animated.Value(0));
  const [startDelay] = useState(delay);
  useEffect(() => {
    const anim = Animated.sequence([
      Animated.timing(v, { toValue: 1, duration: morphMs, delay: startDelay, easing: Easing.inOut(Easing.cubic), useNativeDriver: NATIVE_DRIVER }),
      Animated.timing(v, { toValue: 2, duration: 220, useNativeDriver: NATIVE_DRIVER }),
    ]);
    anim.start();
    return () => anim.stop();
  }, [v, morphMs, startDelay]);

  const clip = raw.find((r) => r.clipId === kept.clipId);
  const fromX = kept.rawStart * rawPps;
  const fromW = Math.max(2, (kept.rawEnd - kept.rawStart) * rawPps);
  const toX = kept.outStart * pps;
  const toW = Math.max(2, (kept.outEnd - kept.outStart) * pps);
  const dx = toX + toW / 2 - (fromX + fromW / 2);
  const translateX = v.interpolate({ inputRange: [0, 1, 2], outputRange: [0, dx, dx] });
  const scaleX = v.interpolate({ inputRange: [0, 1, 2], outputRange: [1, toW / fromW, toW / fromW] });
  const translateY = v.interpolate({ inputRange: [0, 0.5, 1, 2], outputRange: [0, -10, 0, 0] });
  const opacity = v.interpolate({ inputRange: [0, 0.05, 1, 2], outputRange: [0, 1, 1, 0] });
  const stripW = clip ? Math.max(2, (clip.end - clip.start) * rawPps) : fromW;
  const stripX = clip ? (clip.start - kept.rawStart) * rawPps : 0;
  return (
    <Animated.View
      pointerEvents="none"
      style={[styles.ghost, { left: fromX, width: fromW, opacity, transform: [{ translateX }, { translateY }, { scaleX }] }]}
      testID={`live-ghost-${kept.index}`}
    >
      <Image
        source={{ uri: api.filmstripUrl(projectId, kept.clipId, FILMSTRIP_FRAMES) }}
        style={{ position: 'absolute', top: 0, bottom: 0, left: stripX, width: stripW }}
        resizeMode="stretch"
      />
    </Animated.View>
  );
}

/** Thin shimmer running across the whole timeline while the shots are joined / the final pass runs. */
function RenderShimmer({ width }: { width: number }) {
  const [v] = useState(() => new Animated.Value(0));
  useEffect(() => {
    const anim = Animated.loop(Animated.timing(v, { toValue: 1, duration: 1100, easing: Easing.linear, useNativeDriver: NATIVE_DRIVER }));
    anim.start();
    return () => anim.stop();
  }, [v]);
  const translateX = v.interpolate({ inputRange: [0, 1], outputRange: [-120, Math.max(120, width)] });
  return (
    <View pointerEvents="none" style={styles.shimmerTrack} testID="timeline-render-shimmer">
      <Animated.View style={[styles.shimmerGlint, { transform: [{ translateX }] }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: studio.panel,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: studio.border,
    overflow: 'hidden',
  },
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: studio.border,
    zIndex: 2,
  },
  play: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: studio.text,
    alignItems: 'center',
    justifyContent: 'center',
  },
  trackSelect: {
    marginLeft: 12,
    paddingHorizontal: 12,
    height: 32,
    borderRadius: 10,
    backgroundColor: studio.card,
    justifyContent: 'center',
  },
  spacer: { flex: 1 },
  slider: { width: SLIDER_W, height: 24, justifyContent: 'center' },
  sliderTrack: { position: 'absolute', left: 0, right: 0, height: 4, borderRadius: 2, backgroundColor: studio.border },
  sliderFill: { height: 4, borderRadius: 2, backgroundColor: studio.text },
  body: { flexDirection: 'row' },
  labels: { width: LABEL_W, borderRightWidth: 1, borderRightColor: studio.border },
  trackLabel: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14 },
  trackLabelMain: { backgroundColor: studio.card },
  tracksView: { flex: 1 },
  ruler: { height: RULER_H, borderBottomWidth: 1, borderBottomColor: studio.border },
  tick: { position: 'absolute', top: 0, height: RULER_H, flexDirection: 'row' },
  tickMark: { width: 1, height: 10, backgroundColor: studio.faint, marginTop: 14 },
  tickLabel: { marginLeft: 4, marginTop: 6 },
  row: { position: 'relative', justifyContent: 'center' },
  textPill: {
    position: 'absolute',
    top: 4,
    height: TEXT_H - 8,
    borderRadius: 8,
    backgroundColor: studio.indigo,
    paddingHorizontal: 8,
    justifyContent: 'center',
  },
  graphicPill: {
    position: 'absolute',
    top: 3,
    height: GRAPHIC_H - 6,
    borderRadius: 8,
    backgroundColor: studio.purple,
    paddingHorizontal: 10,
    justifyContent: 'center',
  },
  segment: {
    position: 'absolute',
    top: 2,
    height: MAIN_H - 4,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: studio.blue,
    backgroundColor: studio.blue,
    overflow: 'hidden',
  },
  segLabel: { height: SEG_LABEL_H, paddingHorizontal: 6, lineHeight: SEG_LABEL_H },
  film: { height: FILM_H, overflow: 'hidden', backgroundColor: '#0E1A33' },
  wave: { height: WAVE_H, justifyContent: 'center', backgroundColor: '#123A7A' },
  waveLine: { height: 1, backgroundColor: '#9CC8FF', opacity: 0.6 },
  emptyMain: { paddingHorizontal: 12 },
  segmentLive: { borderColor: studio.cyan },
  fxPill: {
    position: 'absolute',
    top: 4,
    height: FX_H - 8,
    borderRadius: 6,
    backgroundColor: studio.violet,
    paddingHorizontal: 6,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  musicPill: {
    position: 'absolute',
    top: 4,
    height: MUSIC_H - 8,
    borderRadius: 6,
    backgroundColor: studio.green,
    paddingHorizontal: 8,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    height: 28,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: studio.cyan,
    backgroundColor: studio.blueSoft,
  },
  buildCursor: { position: 'absolute', top: 0, bottom: 0, left: -1, width: 2, zIndex: 3 },
  buildGlow: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: -5,
    width: 12,
    borderRadius: 6,
    backgroundColor: studio.cyan,
    boxShadow: '0 0 14px 4px rgba(34, 211, 238, 0.7)',
  },
  buildLine: { position: 'absolute', top: 0, bottom: 0, left: 0, width: 2, backgroundColor: studio.cyan },
  buildKnob: {
    position: 'absolute',
    top: 2,
    left: -11,
    width: 24,
    height: 16,
    borderRadius: 4,
    backgroundColor: studio.cyan,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ticker: {
    // what the agent is doing must be readable (it was cut to "Resul…" at laptop widths)
    flexGrow: 1,
    flexShrink: 1,
    minWidth: 180,
    maxWidth: 560,
    height: 28,
    justifyContent: 'center',
    paddingHorizontal: 10,
    borderRadius: 999,
    backgroundColor: studio.card,
    overflow: 'hidden',
  },
  queueChip: {
    height: 28,
    justifyContent: 'center',
    paddingHorizontal: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: studio.faint,
    backgroundColor: studio.card,
  },
  colorChip: { paddingHorizontal: 6, height: 20, borderRadius: 999, backgroundColor: studio.card, justifyContent: 'center' },
  labelChip: {
    position: 'absolute',
    top: -9,
    height: 18,
    maxWidth: 180,
    paddingHorizontal: 7,
    borderRadius: 999,
    backgroundColor: studio.cyan,
    justifyContent: 'center',
    zIndex: 4,
  },
  rawLayer: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  rawClip: {
    position: 'absolute',
    top: 2,
    height: MAIN_H - 4,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: studio.faint,
    backgroundColor: '#0E1A33',
    overflow: 'hidden',
  },
  rawFilm: { position: 'absolute', left: 0, right: 0, top: SEG_LABEL_H, height: FILM_H, opacity: 0.45 },
  rawName: { height: SEG_LABEL_H, paddingHorizontal: 6, lineHeight: SEG_LABEL_H },
  rawLabel: {
    position: 'absolute',
    left: 6,
    bottom: 6,
    paddingHorizontal: 6,
    height: 16,
    borderRadius: 4,
    backgroundColor: 'rgba(11, 12, 16, 0.75)',
    justifyContent: 'center',
  },
  cutGap: { position: 'absolute', top: 2, height: MAIN_H - 4, backgroundColor: 'rgba(5, 6, 8, 0.78)' },
  keptBox: {
    position: 'absolute',
    top: 2,
    height: MAIN_H - 4,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: studio.cyan,
    backgroundColor: 'rgba(34, 211, 238, 0.14)',
  },
  cutMark: { position: 'absolute', top: 0, height: MAIN_H, width: 14, alignItems: 'center' },
  cutLine: { position: 'absolute', top: 0, bottom: 0, left: 6, width: 2, backgroundColor: studio.red, opacity: 0.8 },
  cutGlyph: { marginTop: -2, backgroundColor: studio.bg, borderRadius: 7, width: 14, textAlign: 'center' },
  ghost: {
    position: 'absolute',
    top: 2,
    height: MAIN_H - 4,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: studio.cyan,
    backgroundColor: '#0E1A33',
    overflow: 'hidden',
    zIndex: 3,
  },
  shimmerTrack: { position: 'absolute', top: RULER_H - 3, left: 0, right: 0, height: 3, overflow: 'hidden', zIndex: 2 },
  shimmerGlint: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 120,
    borderRadius: 2,
    backgroundColor: studio.cyan,
    boxShadow: '0 0 10px 2px rgba(34, 211, 238, 0.8)',
  },
  segmentDone: { borderColor: studio.green, boxShadow: '0 0 8px 1px rgba(34, 197, 94, 0.55)' },
  doneBadge: {
    position: 'absolute',
    top: 1,
    right: 3,
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: studio.green,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 2,
  },
  reuseNote: {
    position: 'absolute',
    right: 8,
    bottom: 6,
    paddingHorizontal: 8,
    height: 18,
    borderRadius: 999,
    backgroundColor: studio.green,
    justifyContent: 'center',
    zIndex: 4,
  },
  playhead: { position: 'absolute', top: 0, bottom: 0, width: 2, backgroundColor: studio.blue },
  commentPins: { position: 'absolute', top: 0, left: 0, right: 0, height: RULER_H, zIndex: 5 },
  commentPin: { position: 'absolute', top: 2, width: 12, height: RULER_H - 2, alignItems: 'center' },
  commentPinDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: studio.cyan,
    borderWidth: 2,
    borderColor: studio.bg,
  },
  commentPinStem: { width: 2, flex: 1, backgroundColor: studio.cyan, opacity: 0.7 },
  commentTip: {
    position: 'absolute',
    top: 0,
    left: 14,
    width: 200,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    backgroundColor: studio.cyan,
  },
  commentLine: { position: 'absolute', top: 0, bottom: 0, width: 2, backgroundColor: studio.cyan, zIndex: 5 },
  commentBox: {
    position: 'absolute',
    top: RULER_H + 2,
    width: COMMENT_W,
    padding: 8,
    gap: 6,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: studio.cyan,
    backgroundColor: studio.card,
    boxShadow: '0 6px 18px rgba(0, 0, 0, 0.45)',
    zIndex: 6,
  },
  commentHead: { flexDirection: 'row', alignItems: 'center' },
  commentClose: { width: 22, height: 22, alignItems: 'center', justifyContent: 'center' },
  commentRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  commentInput: {
    flex: 1,
    height: 32,
    paddingHorizontal: 8,
    borderRadius: 8,
    backgroundColor: studio.bg,
    color: studio.text,
    fontSize: 13,
  },
  commentSend: {
    height: 32,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: studio.blue,
    alignItems: 'center',
    justifyContent: 'center',
  },
  commentSendOff: { backgroundColor: studio.cardHover },
  playheadKnob: {
    position: 'absolute',
    top: 0,
    left: -5,
    width: 12,
    height: 12,
    borderRadius: 3,
    backgroundColor: studio.blue,
  },
});
