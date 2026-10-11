import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { PlanOverlay, StyleInfo } from '../../api/types';
import { AppText } from '../AppText';
import { OverlayCard } from './MediaPanel';
import { studio } from './theme';
import { GradientPreview } from './ui';

export interface OverlaysPanelProps {
  overlays: PlanOverlay[];
  /** Currently applied plan style id. */
  activeStyle?: string | null;
  onApplyStyle: (style: StyleInfo) => void;
  /** Take the look off: its gradient graphic tracks and the style name (no AI, undo brings it back). */
  onRemoveStyle?: () => void;
  busy?: boolean;
}

export function OverlaysPanel({ overlays, activeStyle, onApplyStyle, onRemoveStyle, busy }: OverlaysPanelProps) {
  const [styles_, setStyles] = useState<StyleInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .listStyles()
      .then((r) => {
        if (alive) setStyles(r.styles ?? []);
      })
      .catch((e) => {
        if (alive) setError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <View style={styles.panel} testID="overlays-panel">
      <AppText size="md" weight="semibold">
        Styles
      </AppText>
      <AppText size="xs" color={studio.muted}>
        Pick a look — the agent re-edits your video with its animated gradients.
      </AppText>
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {!styles_ && !error ? <ActivityIndicator color={studio.blue} /> : null}
        {error ? (
          <AppText size="xs" color={studio.red}>
            {error}
          </AppText>
        ) : null}
        {(styles_ ?? []).map((s) => {
          const on = s.id === activeStyle;
          return (
            <Pressable
              key={s.id}
              onPress={() => onApplyStyle(s)}
              disabled={busy}
              accessibilityRole="button"
              accessibilityLabel={`Apply ${s.name} style`}
              testID={`style-${s.id}`}
              style={({ pressed }) => [styles.styleCard, on && styles.styleCardOn, pressed && styles.pressed]}
            >
              <GradientPreview colors={s.colors} width={64} height={48} radius={10} />
              <View style={styles.styleText}>
                <AppText size="sm" weight="semibold">
                  {s.name}
                  {on ? '  · applied' : ''}
                </AppText>
                <AppText size="xs" color={studio.muted} numberOfLines={2}>
                  {s.description}
                </AppText>
              </View>
            </Pressable>
          );
        })}

        <AppText size="md" weight="semibold" style={styles.section}>
          On this edit ({overlays.length})
        </AppText>
        <View style={styles.grid}>
          {overlays.map((o, i) => (
            <OverlayCard key={`${o.label}-${i}`} overlay={o} />
          ))}
        </View>
        {overlays.length === 0 ? (
          <AppText size="xs" color={studio.muted}>
            No overlays yet.
          </AppText>
        ) : null}
        {onRemoveStyle && (overlays.length > 0 || activeStyle) ? (
          <Pressable
            onPress={onRemoveStyle}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel="Remove the look and its gradient tracks"
            testID="remove-style"
            style={({ pressed }) => [styles.removeBtn, (pressed || busy) && styles.pressed]}
          >
            <AppText size="sm" weight="semibold" color={studio.red}>
              ✕ Look hatao (gradient tracks)
            </AppText>
            <AppText size="xs" color={studio.muted}>
              Saare gradient / colour wash tracks hat jayenge. Galti ho to ↶ Undo.
            </AppText>
          </Pressable>
        ) : null}
      </ScrollView>
    </View>
  );
}

export function ComingSoonPanel({ title }: { title: string }) {
  return (
    <View style={[styles.panel, styles.soon]} testID="coming-soon-panel">
      <AppText size="md" weight="semibold">
        {title}
      </AppText>
      <AppText size="sm" color={studio.muted} center>
        Coming soon. Meanwhile, just ask the CutMind agent in the chat.
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    width: 340,
    backgroundColor: studio.panel,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: studio.border,
    padding: 14,
    gap: 8,
  },
  soon: { alignItems: 'center', justifyContent: 'center' },
  scroll: { flex: 1 },
  content: { gap: 10, paddingBottom: 12 },
  styleCard: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'center',
    backgroundColor: studio.card,
    borderRadius: 12,
    padding: 8,
    borderWidth: 1,
    borderColor: studio.border,
  },
  styleCardOn: { borderColor: studio.blue },
  styleText: { flex: 1, gap: 2 },
  pressed: { opacity: 0.75 },
  removeBtn: {
    marginTop: 4,
    padding: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: studio.red,
    backgroundColor: studio.card,
    gap: 2,
  },
  section: { marginTop: 6 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
});
