import { Canvas, Group, RoundedRect } from '@shopify/react-native-skia';
import { useMemo, useState } from 'react';
import { StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import { useDerivedValue, useSharedValue, withTiming } from 'react-native-reanimated';

import { colors } from '../../theme';
import { formatDuration } from '../../utils/format';
import { layoutSegments } from '../../utils/timelineModel';
import { AppText } from '../AppText';
import type { TimelineProps } from './types';

const TRACK_TOP = 10;
const PLAYHEAD_W = 3;

/**
 * Skia timeline: clip segments drawn as rounded rects proportional to their duration,
 * plus a draggable playhead driven by a Reanimated shared value.
 */
export default function SkiaTimeline({ model, height = 64, onSeek }: TimelineProps) {
  const [width, setWidth] = useState(0);
  const [time, setTime] = useState(0);
  const playheadX = useSharedValue(0);
  const trackH = height - TRACK_TOP * 2;

  const rects = useMemo(() => layoutSegments(model, width), [model, width]);

  const playheadRectX = useDerivedValue(() => playheadX.value - PLAYHEAD_W / 2);
  const knobX = useDerivedValue(() => playheadX.value - 6);

  const onLayout = (e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width);

  const toSeconds = (x: number) => (width > 0 ? (x / width) * model.total : 0);

  const pan = Gesture.Pan()
    .runOnJS(true)
    .minDistance(0)
    .onBegin((e) => {
      const x = Math.max(0, Math.min(width, e.x));
      playheadX.value = withTiming(x, { duration: 120 });
      setTime(toSeconds(x));
    })
    .onUpdate((e) => {
      const x = Math.max(0, Math.min(width, e.x));
      playheadX.value = x;
      setTime(toSeconds(x));
    })
    .onFinalize((e) => {
      const x = Math.max(0, Math.min(width, e.x));
      onSeek?.(toSeconds(x));
    });

  return (
    <View>
      <GestureDetector gesture={pan}>
        <View
          style={[styles.canvasWrap, { height }]}
          onLayout={onLayout}
          testID="skia-timeline"
          accessibilityLabel="Timeline. Drag to move the playhead."
        >
          {width > 0 ? (
            <Canvas style={{ width, height }}>
              {rects.map((r) => (
                <RoundedRect key={r.key} x={r.x} y={TRACK_TOP} width={r.width} height={trackH} r={8} color={r.color} opacity={0.9} />
              ))}
              <Group>
                <RoundedRect x={playheadRectX} y={2} width={PLAYHEAD_W} height={height - 4} r={1.5} color={colors.text} />
                <RoundedRect x={knobX} y={0} width={12} height={8} r={4} color={colors.text} />
              </Group>
            </Canvas>
          ) : null}
        </View>
      </GestureDetector>
      <View style={styles.ruler}>
        <AppText size="xs" muted>
          {formatDuration(time)}
        </AppText>
        <AppText size="xs" muted>
          {formatDuration(model.total)}
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  canvasWrap: { width: '100%' },
  ruler: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
});
