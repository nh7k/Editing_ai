import { useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { AppText } from '../AppText';
import { useStudioSkia } from './skia/useStudioSkia';
import { studio } from './theme';

export interface IconButtonProps {
  glyph: string;
  label: string;
  onPress?: () => void;
  disabled?: boolean;
  active?: boolean;
  size?: number;
  testID?: string;
  style?: StyleProp<ViewStyle>;
}

/** Square icon button using a text glyph. */
export function IconButton({ glyph, label, onPress, disabled, active, size = 32, testID, style }: IconButtonProps) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled, selected: !!active }}
      testID={testID}
      style={({ pressed }) => [
        styles.iconBtn,
        { width: size, height: size },
        active && styles.iconBtnActive,
        pressed && !disabled && styles.pressed,
        disabled && styles.disabled,
        style,
      ]}
    >
      <AppText size="md" color={active ? studio.white : studio.text} weight="semibold">
        {glyph}
      </AppText>
    </Pressable>
  );
}

export interface MenuItem {
  key: string;
  label: string;
  disabled?: boolean;
  hint?: string;
}

export interface DropdownProps {
  /** Rendered trigger content. */
  trigger: ReactNode;
  items: MenuItem[];
  onSelect: (key: string) => void;
  testID?: string;
  triggerStyle?: StyleProp<ViewStyle>;
  align?: 'left' | 'right';
  accessibilityLabel?: string;
  disabled?: boolean;
  menuWidth?: number;
}

/** Trigger + absolutely positioned menu (closes on select). */
export function Dropdown({
  trigger,
  items,
  onSelect,
  testID,
  triggerStyle,
  align = 'left',
  accessibilityLabel,
  disabled,
  menuWidth = 160,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  return (
    <View style={styles.dropWrap}>
      <Pressable
        onPress={() => setOpen((o) => !o)}
        disabled={disabled}
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        accessibilityState={{ expanded: open, disabled: !!disabled }}
        testID={testID}
        style={({ pressed }) => [triggerStyle, pressed && styles.pressed, disabled && styles.disabled]}
      >
        {trigger}
      </Pressable>
      {open ? (
        <View
          style={[styles.menu, { width: menuWidth }, align === 'right' ? { right: 0 } : { left: 0 }]}
          testID={testID ? `${testID}-menu` : undefined}
        >
          {items.map((it) => (
            <Pressable
              key={it.key}
              disabled={it.disabled}
              onPress={() => {
                setOpen(false);
                onSelect(it.key);
              }}
              accessibilityRole="menuitem"
              accessibilityState={{ disabled: !!it.disabled }}
              testID={testID ? `${testID}-${it.key}` : undefined}
              style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
            >
              <AppText size="sm" color={it.disabled ? studio.faint : studio.text}>
                {it.label}
              </AppText>
              {it.hint ? (
                <AppText size="xs" color={studio.faint}>
                  {it.hint}
                </AppText>
              ) : null}
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** Gradient preview: Skia LinearGradient when available, flat first colour otherwise. */
export function GradientPreview({
  colors,
  width,
  height,
  radius = 10,
}: {
  colors: string[];
  width: number;
  height: number;
  radius?: number;
}) {
  const skia = useStudioSkia();
  if (skia && width > 0) {
    return <skia.GradientSwatch width={width} height={height} colors={colors} radius={radius} />;
  }
  return (
    <View style={{ width, height, borderRadius: radius, flexDirection: 'row', overflow: 'hidden' }}>
      {(colors.length ? colors : [studio.indigo]).map((c, i) => (
        <View key={`${c}-${i}`} style={{ flex: 1, backgroundColor: c }} />
      ))}
    </View>
  );
}

export function Badge({ label, color, textColor = studio.white }: { label: string; color: string; textColor?: string }) {
  return (
    <View style={[styles.badge, { backgroundColor: color }]}>
      <AppText size="xs" weight="semibold" color={textColor}>
        {label}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  iconBtn: { alignItems: 'center', justifyContent: 'center', borderRadius: 10 },
  iconBtnActive: { backgroundColor: studio.blue },
  pressed: { opacity: 0.7 },
  disabled: { opacity: 0.35 },
  dropWrap: { position: 'relative', zIndex: 20 },
  menu: {
    position: 'absolute',
    top: '100%',
    marginTop: 6,
    backgroundColor: studio.card,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: studio.border,
    paddingVertical: 4,
    zIndex: 50,
    elevation: 10,
  },
  menuItem: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  menuItemPressed: { backgroundColor: studio.cardHover },
  badge: { borderRadius: 6, paddingHorizontal: 6, paddingVertical: 1, alignSelf: 'flex-start' },
});
