import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { colors, radius, spacing } from '../../theme';
import type { TimelineModel } from '../../utils/timelineModel';
import { AppText } from '../AppText';

export interface TimelineShellProps {
  model: TimelineModel;
  children: ReactNode;
}

/** Header, empty state and legend around the platform-specific timeline canvas. */
export function TimelineShell({ model, children }: TimelineShellProps) {
  return (
    <View style={styles.wrap}>
      <View style={styles.header}>
        <AppText size="sm" weight="semibold">
          Timeline
        </AppText>
        <AppText size="xs" muted>
          {model.source === 'plan' ? 'from edit plan' : model.source === 'clips' ? 'raw clips' : ''}
        </AppText>
      </View>
      {model.segments.length === 0 ? (
        <View style={styles.empty}>
          <AppText size="sm" muted>
            Import clips to see them on the timeline.
          </AppText>
        </View>
      ) : (
        <>
          {children}
          <View style={styles.legend}>
            {model.segments.slice(0, 8).map((s) => (
              <View key={s.key} style={styles.legendItem}>
                <View style={[styles.dot, { backgroundColor: s.color }]} />
                <AppText size="xs" muted numberOfLines={1} style={styles.legendText}>
                  {s.label}
                </AppText>
              </View>
            ))}
            {model.segments.length > 8 ? (
              <AppText size="xs" muted>
                +{model.segments.length - 8} more
              </AppText>
            ) : null}
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  header: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.sm },
  empty: { height: 64, alignItems: 'center', justifyContent: 'center' },
  legend: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 4, maxWidth: 140 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  legendText: { flexShrink: 1 },
});
