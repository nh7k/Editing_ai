// Skia drawings for the studio. Loaded lazily on web (after CanvasKit) via useStudioSkia.
import {
  BlurMask,
  Canvas,
  LinearGradient,
  Path,
  Rect,
  RoundedRect,
  Skia,
  SweepGradient,
  vec,
} from '@shopify/react-native-skia';
import { useEffect, useMemo } from 'react';
import { View } from 'react-native';
import { cancelAnimation, Easing, useDerivedValue, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';

import { glowColors } from '../theme';

export interface GlowFrameProps {
  width: number;
  height: number;
  radius?: number;
  colors?: string[];
  /** Seconds per full turn of the gradient. */
  period?: number;
}

const PAD = 12;

/** 2px border whose cyan → indigo gradient rotates continuously, plus a soft blurred glow. */
export function GlowFrame({ width, height, radius = 6, colors = glowColors, period = 5 }: GlowFrameProps) {
  const angle = useSharedValue(0);
  useEffect(() => {
    angle.value = withRepeat(withTiming(Math.PI * 2, { duration: period * 1000, easing: Easing.linear }), -1, false);
    return () => cancelAnimation(angle);
  }, [angle, period]);
  const center = vec(PAD + width / 2, PAD + height / 2);
  const transform = useDerivedValue(() => [{ rotate: angle.value }]);
  if (width <= 0 || height <= 0) return null;
  const rect = { x: PAD - 1, y: PAD - 1, width: width + 2, height: height + 2 };
  return (
    <View
      pointerEvents="none"
      style={{ position: 'absolute', left: -PAD, top: -PAD, width: width + PAD * 2, height: height + PAD * 2 }}
    >
      <Canvas style={{ width: width + PAD * 2, height: height + PAD * 2 }}>
        <RoundedRect {...rect} r={radius} style="stroke" strokeWidth={4} opacity={0.55}>
          <SweepGradient c={center} colors={colors} transform={transform} origin={center} />
          <BlurMask blur={8} style="normal" />
        </RoundedRect>
        <RoundedRect {...rect} r={radius} style="stroke" strokeWidth={2}>
          <SweepGradient c={center} colors={colors} transform={transform} origin={center} />
        </RoundedRect>
      </Canvas>
    </View>
  );
}

export interface GradientSwatchProps {
  width: number;
  height: number;
  colors: string[];
  radius?: number;
}

/** Diagonal linear gradient preview of an overlay / style palette. */
export function GradientSwatch({ width, height, colors, radius = 10 }: GradientSwatchProps) {
  const stops = colors.length >= 2 ? colors : [colors[0] ?? '#6366F1', colors[0] ?? '#22D3EE'];
  if (width <= 0 || height <= 0) return null;
  return (
    <Canvas style={{ width, height }}>
      <RoundedRect x={0} y={0} width={width} height={height} r={radius}>
        <LinearGradient start={vec(0, 0)} end={vec(width, height)} colors={stops} />
      </RoundedRect>
    </Canvas>
  );
}

export interface WaveformBarsProps {
  width: number;
  height: number;
  peaks: number[];
  color: string;
}

/** Mirrored waveform bars (one per peak) centred vertically. */
export function WaveformBars({ width, height, peaks, color }: WaveformBarsProps) {
  const path = useMemo(() => {
    const p = Skia.Path.Make();
    const n = peaks.length;
    if (!n || width <= 0) return p;
    const step = width / n;
    const bw = Math.max(1, step * 0.6);
    const mid = height / 2;
    peaks.forEach((v, i) => {
      const h = Math.max(1, Math.min(1, Math.max(0, v)) * height);
      p.addRect(Skia.XYWHRect(i * step, mid - h / 2, bw, h));
    });
    return p;
  }, [peaks, width, height]);
  if (width <= 0 || height <= 0) return null;
  return (
    <Canvas style={{ width, height }}>
      <Rect x={0} y={height / 2 - 0.5} width={width} height={1} color={color} opacity={0.5} />
      <Path path={path} color={color} />
    </Canvas>
  );
}
