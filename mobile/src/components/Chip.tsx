import { Pressable, StyleSheet } from 'react-native';

import { colors, radius, spacing } from '../theme';
import { AppText } from './AppText';

export interface ChipProps {
  label: string;
  onPress?: () => void;
  selected?: boolean;
  disabled?: boolean;
  testID?: string;
}

export function Chip({ label, onPress, selected, disabled, testID }: ChipProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected: !!selected, disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.chip,
        selected && styles.selected,
        pressed && styles.pressed,
        disabled && styles.disabled,
      ]}
    >
      <AppText size="sm" weight="medium" color={selected ? '#FFFFFF' : colors.text} numberOfLines={1}>
        {label}
      </AppText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: colors.cardAlt,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  selected: { backgroundColor: colors.accent, borderColor: colors.accent },
  pressed: { opacity: 0.8 },
  disabled: { opacity: 0.45 },
});
