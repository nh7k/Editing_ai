import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import type { MemoryHistoryItem, ProjectMemory } from '../../api/types';
import { formatDuration } from '../../utils/format';
import { AppText } from '../AppText';
import { styleName, titleCaseId } from './fxPhrases';
import { studio } from './theme';

export const SAME_AS_BEFORE = 'same as before but ';
export const IN_MY_STYLE = 'in my style, ';

export interface MemoryCardProps {
  memory?: ProjectMemory | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** A quick chip was pressed; receives the phrase to put in the chat input. */
  onQuickPhrase: (phrase: string) => void;
  /** Start collapsed (default: expanded). */
  initiallyCollapsed?: boolean;
}

/** Most recent `n` history entries, newest first. */
export function recentHistory(history: MemoryHistoryItem[] | undefined, n = 3): MemoryHistoryItem[] {
  return [...(history ?? [])]
    .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))
    .slice(0, n);
}

function deliveredLine(h: MemoryHistoryItem): string {
  const parts: string[] = [];
  const style = h.delivered?.style ?? h.chosen_style;
  if (style) parts.push(styleName(style));
  if (typeof h.delivered?.duration === 'number') parts.push(formatDuration(h.delivered.duration));
  if (h.rating === 'up') parts.push('liked');
  if (h.rating === 'down') parts.push('disliked');
  return parts.join(' · ');
}

/** Collapsible "CutMind remembers" card at the top of the studio chat. */
export function MemoryCard({ memory, loading, error, onRetry, onQuickPhrase, initiallyCollapsed }: MemoryCardProps) {
  const [open, setOpen] = useState(!initiallyCollapsed);
  const prefs = memory?.preferences;
  const recent = recentHistory(memory?.history);
  const remembered = prefs?.edits_remembered ?? memory?.history?.length ?? 0;

  return (
    <View style={styles.card} testID="memory-card">
      <Pressable
        onPress={() => setOpen((o) => !o)}
        accessibilityRole="button"
        accessibilityLabel="CutMind remembers"
        accessibilityState={{ expanded: open }}
        testID="memory-toggle"
        style={styles.header}
      >
        <AppText size="sm" weight="semibold">
          ◎ CutMind remembers
        </AppText>
        <AppText size="xs" color={studio.muted}>
          {memory ? `${remembered} edit${remembered === 1 ? '' : 's'} ` : ''}
          {open ? '▴' : '▾'}
        </AppText>
      </Pressable>

      {open ? (
        <View style={styles.body} testID="memory-body">
          {loading && !memory ? (
            <View style={styles.row}>
              <ActivityIndicator size="small" color={studio.cyan} />
              <AppText size="xs" color={studio.muted}>
                Loading memory…
              </AppText>
            </View>
          ) : null}
          {error && !memory ? (
            <View style={styles.row} testID="memory-error">
              <AppText size="xs" color={studio.red} style={styles.flex}>
                Could not load memory: {error}
              </AppText>
              {onRetry ? (
                <AppText size="xs" color={studio.blue} onPress={onRetry} testID="memory-retry">
                  Retry
                </AppText>
              ) : null}
            </View>
          ) : null}

          {memory ? (
            <>
              <AppText size="xs" color={studio.text} testID="memory-summary">
                {memory.summary || 'No edits remembered yet — your first edit teaches CutMind your taste.'}
              </AppText>
              <View style={styles.chips}>
                {prefs?.favourite_style ? (
                  <View style={[styles.pill, styles.pillFav]} testID="memory-fav-style">
                    <AppText size="xs" weight="semibold" color={studio.white}>
                      ★ {styleName(prefs.favourite_style)}
                    </AppText>
                  </View>
                ) : null}
                {prefs?.favourite_colour_look ? (
                  <View style={styles.pill} testID="memory-fav-look">
                    <AppText size="xs" color={studio.text}>
                      Look: {titleCaseId(prefs.favourite_colour_look)}
                    </AppText>
                  </View>
                ) : null}
                {prefs?.usual_aspect_ratio ? (
                  <View style={styles.pill} testID="memory-aspect">
                    <AppText size="xs" color={studio.text}>
                      Usually {prefs.usual_aspect_ratio}
                    </AppText>
                  </View>
                ) : null}
              </View>
              {recent.length ? (
                <View style={styles.history} testID="memory-history">
                  {recent.map((h) => {
                    const line = deliveredLine(h);
                    return (
                      <View key={h.job_id} style={styles.historyItem} testID={`memory-history-${h.job_id}`}>
                        <AppText size="xs" numberOfLines={1}>
                          “{h.prompt}”
                        </AppText>
                        {line ? (
                          <AppText size="xs" color={studio.muted}>
                            {line}
                          </AppText>
                        ) : null}
                      </View>
                    );
                  })}
                </View>
              ) : null}
            </>
          ) : null}

          <View style={styles.chips}>
            <Pressable
              onPress={() => onQuickPhrase(SAME_AS_BEFORE)}
              accessibilityRole="button"
              testID="memory-same-as-before"
              style={({ pressed }) => [styles.quick, pressed && styles.pressed]}
            >
              <AppText size="xs" weight="semibold" color={studio.cyan}>
                ↺ Same as before
              </AppText>
            </Pressable>
            <Pressable
              onPress={() => onQuickPhrase(IN_MY_STYLE)}
              accessibilityRole="button"
              testID="memory-in-my-style"
              style={({ pressed }) => [styles.quick, pressed && styles.pressed]}
            >
              <AppText size="xs" weight="semibold" color={studio.cyan}>
                ✦ In my style
              </AppText>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginHorizontal: 12,
    marginBottom: 8,
    backgroundColor: studio.card,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: studio.border,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  body: { paddingHorizontal: 12, paddingBottom: 10, gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  flex: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  pill: {
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderWidth: 1,
    borderColor: studio.border,
  },
  pillFav: { backgroundColor: studio.violet, borderColor: studio.violet },
  history: { gap: 6 },
  historyItem: { gap: 1, borderLeftWidth: 2, borderLeftColor: studio.border, paddingLeft: 8 },
  quick: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: studio.cyan,
  },
  pressed: { opacity: 0.7 },
});
