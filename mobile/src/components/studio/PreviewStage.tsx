import { VideoView, type VideoPlayer } from 'expo-video';
import { useState, type ReactNode } from 'react';
import { StyleSheet, View, type LayoutChangeEvent } from 'react-native';

import type { AspectRatio } from '../../api/types';
import { AppText } from '../AppText';
import { useStudioSkia } from './skia/useStudioSkia';
import { studio } from './theme';

const RATIO: Record<AspectRatio, number> = { '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1 };
const MARGIN = 32;

/** Largest `ratio` box inside `w`×`h` (minus a margin), scaled by `zoom`. */
export function fitFrame(w: number, h: number, ratio: number, zoom = 1): { width: number; height: number } {
  const aw = Math.max(0, w - MARGIN * 2);
  const ah = Math.max(0, h - MARGIN * 2);
  if (aw <= 0 || ah <= 0) return { width: 0, height: 0 };
  let width = aw;
  let height = width / ratio;
  if (height > ah) {
    height = ah;
    width = height * ratio;
  }
  return { width: Math.round(width * zoom), height: Math.round(height * zoom) };
}

export interface PreviewStageProps {
  player: VideoPlayer;
  hasOutput: boolean;
  aspect: AspectRatio;
  zoom: number;
  label?: string;
  /** Drawn centred over the stage (e.g. the live progress card while the agents edit). */
  overlay?: ReactNode;
}

/** Near-black stage with the video centred inside an animated glowing gradient border. */
export function PreviewStage({ player, hasOutput, aspect, zoom, label, overlay }: PreviewStageProps) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  const skia = useStudioSkia();
  const onLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setSize({ w: width, h: height });
  };
  const frame = fitFrame(size.w, size.h, RATIO[aspect], zoom);

  return (
    <View style={styles.stage} onLayout={onLayout} testID="preview-stage">
      <View style={[styles.frame, { width: frame.width, height: frame.height }, !skia && styles.fallbackBorder]}>
        {skia && frame.width > 0 ? <skia.GlowFrame width={frame.width} height={frame.height} radius={4} /> : null}
        <View style={styles.inner}>
          {hasOutput ? (
            <VideoView player={player} style={styles.video} nativeControls={false} contentFit="contain" testID="video-view" />
          ) : (
            <View style={styles.placeholder} testID="video-placeholder">
              <AppText size="xxl" color={studio.cyan}>
                ▶
              </AppText>
              <AppText weight="semibold">No render yet</AppText>
              <AppText size="sm" color={studio.muted} center>
                Ask the CutMind agent on the right to cut your first version.
              </AppText>
            </View>
          )}
        </View>
      </View>
      {label ? (
        <View style={styles.label}>
          <AppText size="xs" color={studio.muted}>
            {label}
          </AppText>
        </View>
      ) : null}
      {overlay ? (
        <View style={styles.overlay} pointerEvents="box-none" testID="preview-overlay">
          {overlay}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  stage: {
    flex: 1,
    backgroundColor: studio.bg,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  frame: { position: 'relative' },
  fallbackBorder: { borderWidth: 2, borderColor: studio.cyan, borderRadius: 4 },
  inner: { flex: 1, backgroundColor: studio.stage, borderRadius: 4, overflow: 'hidden' },
  video: { width: '100%', height: '100%' },
  placeholder: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 6, padding: 16 },
  label: { position: 'absolute', top: 8, left: 12 },
  overlay: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, alignItems: 'center', justifyContent: 'center', padding: 16 },
});
