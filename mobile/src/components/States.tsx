import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { colors, radius, spacing } from '../theme';
import { AppText } from './AppText';
import { Button } from './Button';

export function LoadingState({ label = 'Loading...' }: { label?: string }) {
  return (
    <View style={styles.center} testID="loading-state">
      <ActivityIndicator color={colors.accent} />
      <AppText muted size="sm" style={styles.gap}>
        {label}
      </AppText>
    </View>
  );
}

export interface EmptyStateProps {
  title: string;
  message?: string;
  icon?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({ title, message, icon = '+', actionLabel, onAction }: EmptyStateProps) {
  return (
    <View style={styles.center} testID="empty-state">
      <View style={[styles.badge, { backgroundColor: colors.accentSoft }]}>
        <AppText size="xl" weight="bold" color={colors.accent}>
          {icon}
        </AppText>
      </View>
      <AppText size="lg" weight="semibold" center style={styles.gap}>
        {title}
      </AppText>
      {message ? (
        <AppText muted center style={styles.gapSm}>
          {message}
        </AppText>
      ) : null}
      {actionLabel && onAction ? <Button title={actionLabel} onPress={onAction} style={styles.gap} /> : null}
    </View>
  );
}

export interface ErrorStateProps {
  message: string;
  title?: string;
  onRetry?: () => void;
}

export function ErrorState({ message, title = 'Something went wrong', onRetry }: ErrorStateProps) {
  return (
    <View style={styles.center} testID="error-state">
      <View style={[styles.badge, { backgroundColor: colors.coralSoft }]}>
        <AppText size="xl" weight="bold" color={colors.coral}>
          !
        </AppText>
      </View>
      <AppText size="lg" weight="semibold" center style={styles.gap}>
        {title}
      </AppText>
      <AppText muted center style={styles.gapSm}>
        {message}
      </AppText>
      {onRetry ? <Button title="Try again" variant="secondary" onPress={onRetry} style={styles.gap} /> : null}
    </View>
  );
}

/** Small inline error banner used inside forms / cards. */
export function InlineError({ message }: { message: string }) {
  return (
    <View style={styles.inline} accessibilityRole="alert">
      <AppText size="sm" color={colors.coral}>
        {message}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl, minHeight: 200 },
  badge: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  gap: { marginTop: spacing.md },
  gapSm: { marginTop: spacing.xs },
  inline: {
    backgroundColor: colors.coralSoft,
    borderRadius: radius.sm,
    padding: spacing.md,
    marginTop: spacing.sm,
  },
});
