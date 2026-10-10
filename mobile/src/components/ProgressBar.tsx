import { StyleSheet, View } from 'react-native';

import { colors, radius } from '../theme';

export interface ProgressBarProps {
  /** Fraction 0..1. Clamped. */
  value: number;
  color?: string;
  height?: number;
  testID?: string;
}

export function toFraction(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const v = value;
  return Math.max(0, Math.min(1, v));
}

export function ProgressBar({ value, color = colors.accent, height = 6, testID }: ProgressBarProps) {
  const fraction = toFraction(value);
  return (
    <View
      testID={testID}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: Math.round(fraction * 100) }}
      style={[styles.track, { height, borderRadius: height / 2 }]}
    >
      <View style={[styles.fill, { width: `${fraction * 100}%`, backgroundColor: color, borderRadius: height / 2 }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  track: { width: '100%', backgroundColor: colors.cardAlt, overflow: 'hidden', borderRadius: radius.pill },
  fill: { height: '100%' },
});
