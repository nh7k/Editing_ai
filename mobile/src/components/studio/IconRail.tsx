import { Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '../AppText';
import { studio } from './theme';

export type RailKey = 'media' | 'effects' | 'images' | 'sounds' | 'captions' | 'text' | 'overlays' | 'more';

export const RAIL_ITEMS: { key: RailKey; label: string; glyph: string }[] = [
  { key: 'media', label: 'Media', glyph: '▶' },
  { key: 'effects', label: 'Effects', glyph: '✦' },
  { key: 'images', label: 'Images', glyph: '◩' },
  { key: 'sounds', label: 'Sounds', glyph: '♫' },
  { key: 'captions', label: 'Captions', glyph: '㏄' },
  { key: 'text', label: 'Text', glyph: 'T' },
  { key: 'overlays', label: 'Overlays', glyph: '◈' },
  { key: 'more', label: 'More', glyph: '•••' },
];

export function IconRail({ active, onSelect }: { active: RailKey; onSelect: (k: RailKey) => void }) {
  return (
    <View style={styles.rail} testID="icon-rail">
      {RAIL_ITEMS.map((it) => {
        const on = it.key === active;
        return (
          <Pressable
            key={it.key}
            onPress={() => onSelect(it.key)}
            accessibilityRole="tab"
            accessibilityLabel={it.label}
            accessibilityState={{ selected: on }}
            testID={`rail-${it.key}`}
            style={({ pressed }) => [styles.item, on && styles.itemActive, pressed && !on && styles.pressed]}
          >
            <AppText size="lg" weight="bold" color={on ? studio.white : studio.muted}>
              {it.glyph}
            </AppText>
            <AppText size="xs" weight={on ? 'semibold' : 'regular'} color={on ? studio.white : studio.muted}>
              {it.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  rail: {
    width: 84,
    backgroundColor: studio.panel,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: studio.border,
    paddingVertical: 8,
    paddingHorizontal: 6,
    gap: 4,
    alignSelf: 'flex-start',
  },
  item: { alignItems: 'center', justifyContent: 'center', borderRadius: 12, paddingVertical: 8, gap: 2 },
  itemActive: { backgroundColor: studio.blue },
  pressed: { backgroundColor: studio.card },
});
