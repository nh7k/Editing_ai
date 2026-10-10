import { StyleSheet, View } from 'react-native';

import { colors, radius, spacing } from '../theme';
import { AppText } from './AppText';

export type PillTone = 'neutral' | 'accent' | 'success' | 'danger' | 'warning';

const toneColors: Record<PillTone, { bg: string; fg: string }> = {
  neutral: { bg: colors.cardAlt, fg: colors.textMuted },
  accent: { bg: colors.accentSoft, fg: colors.accent },
  success: { bg: colors.mintSoft, fg: colors.mint },
  danger: { bg: colors.coralSoft, fg: colors.coral },
  warning: { bg: colors.amberSoft, fg: colors.amber },
};

/** Map job / agent statuses to a tone. */
export function toneForStatus(status: string): PillTone {
  switch (status) {
    case 'done':
    case 'passed':
      return 'success';
    case 'failed':
      return 'danger';
    case 'running':
      return 'accent';
    case 'retrying':
      return 'warning';
    default:
      return 'neutral';
  }
}

export interface StatusPillProps {
  label: string;
  tone?: PillTone;
  testID?: string;
}

export function StatusPill({ label, tone = 'neutral', testID }: StatusPillProps) {
  const c = toneColors[tone];
  return (
    <View testID={testID} style={[styles.pill, { backgroundColor: c.bg }]}>
      <AppText size="xs" weight="semibold" color={c.fg}>
        {label}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    alignSelf: 'flex-start',
  },
});
