import { ActivityIndicator, Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { colors, radius, spacing } from '../theme';
import { AppText } from './AppText';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export interface ButtonProps {
  title: string;
  onPress?: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  icon?: string;
  small?: boolean;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  accessibilityLabel?: string;
}

const bg: Record<ButtonVariant, string> = {
  primary: colors.accent,
  secondary: colors.cardAlt,
  ghost: 'transparent',
  danger: colors.coralSoft,
};

const fg: Record<ButtonVariant, string> = {
  primary: '#FFFFFF',
  secondary: colors.text,
  ghost: colors.accent,
  danger: colors.coral,
};

export function Button({
  title,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  icon,
  small,
  style,
  testID,
  accessibilityLabel,
}: ButtonProps) {
  const inactive = !!disabled || !!loading;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? title}
      accessibilityState={{ disabled: inactive, busy: !!loading }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.base,
        small && styles.small,
        { backgroundColor: bg[variant] },
        variant === 'secondary' && styles.bordered,
        pressed && !inactive && styles.pressed,
        inactive && styles.disabled,
        style,
      ]}
    >
      <View style={styles.row}>
        {loading ? <ActivityIndicator size="small" color={fg[variant]} /> : null}
        {!loading && icon ? (
          <AppText size={small ? 'sm' : 'md'} color={fg[variant]}>
            {icon}
          </AppText>
        ) : null}
        <AppText size={small ? 'sm' : 'md'} weight="semibold" color={fg[variant]}>
          {title}
        </AppText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 46,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  small: { minHeight: 34, paddingHorizontal: spacing.md, borderRadius: radius.sm },
  bordered: { borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  pressed: { opacity: 0.8 },
  disabled: { opacity: 0.45 },
});
