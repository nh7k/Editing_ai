import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { FxCatalogResponse, FxCategory, FxItem, ManualOp } from '../../api/types';
import { AppText } from '../AppText';
import { FX_GLYPHS, FX_TABS, fxPhrase, lookColors, totalCount } from './fxPhrases';
import { studio } from './theme';
import { GradientPreview } from './ui';

export interface EffectsPanelProps {
  /** Called with a natural phrase ("glitch effect") to add to the chat prompt. */
  onAddPhrase: (phrase: string) => void;
  /** Apply a card directly to the current edit (no AI). When given, "Apply now" is the default mode. */
  onApply?: (ops: ManualOp[], label: string) => void;
}

/** Effects that need the person tracker / spoken words: those go through the agents. */
const NEEDS_AI = new Set(['follow', 'person_zoom', 'spotlight', 'punch', 'punch_static', 'pulse']);

export function manualOpFor(tab: FxCategory, it: FxItem): ManualOp | null {
  if (tab === 'motion' || tab === 'video_effect') return NEEDS_AI.has(it.id) ? null : { op: 'add_effect', type: it.id };
  if (tab === 'transition') return { op: 'set_transition', type: it.id };
  if (tab === 'color') return { op: 'set_look', preset: it.id };
  if (tab === 'text_animation') return { op: 'style_captions', animation: it.id };
  return null;
}

const ADDED_MS = 1500;

/** Browser for `GET /fx`: motion, effects, transitions, colour looks and text animations. */
export function EffectsPanel({ onAddPhrase, onApply }: EffectsPanelProps) {
  const [mode, setMode] = useState<'apply' | 'prompt'>(onApply ? 'apply' : 'prompt');
  const [data, setData] = useState<FxCatalogResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<FxCategory>('video_effect');
  const [query, setQuery] = useState('');
  const [added, setAdded] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getFxCatalog()
      .then((r) => {
        if (alive) setData(r ?? { catalog: {}, counts: {} });
      })
      .catch((e) => {
        if (alive) setError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, [attempt]);

  useEffect(() => {
    if (!added) return;
    const t = setTimeout(() => setAdded(null), ADDED_MS);
    return () => clearTimeout(t);
  }, [added]);

  const items = useMemo(() => {
    const list = data?.catalog?.[tab] ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((it) => it.name.toLowerCase().includes(q) || it.description.toLowerCase().includes(q) || it.id.toLowerCase().includes(q));
  }, [data, tab, query]);

  const countFor = useCallback(
    (k: FxCategory) => data?.counts?.[k] ?? data?.catalog?.[k]?.length ?? 0,
    [data],
  );
  const total = data ? totalCount(data.counts) || FX_TABS.reduce((a, t) => a + countFor(t.key), 0) : 0;

  const pick = (it: FxItem) => {
    const op = manualOpFor(tab, it);
    if (mode === 'apply' && onApply && op) {
      onApply([op], `${it.name} (applied)`);
    } else {
      onAddPhrase(fxPhrase(tab, it));
    }
    setAdded(`${tab}:${it.id}`);
  };

  return (
    <View style={styles.panel} testID="effects-panel">
      <View style={styles.headerRow}>
        <AppText size="md" weight="semibold">
          Effects
        </AppText>
        {data ? (
          <AppText size="xs" color={studio.muted} testID="fx-total">
            {total} effects
          </AppText>
        ) : null}
      </View>
      {onApply ? (
        <View style={styles.modeRow}>
          {(['apply', 'prompt'] as const).map((m) => (
            <Pressable key={m} onPress={() => setMode(m)} accessibilityRole="switch" accessibilityState={{ checked: mode === m }}
              testID={`fx-mode-${m}`} style={[styles.tab, mode === m && styles.tabOn]}>
              <AppText size="xs" weight="semibold" color={mode === m ? studio.white : studio.muted}>
                {m === 'apply' ? '⚡ Apply now' : '💬 Add to prompt'}
              </AppText>
            </Pressable>
          ))}
        </View>
      ) : null}
      <AppText size="xs" color={studio.muted}>
        {mode === 'apply'
          ? 'Tap a card and it is applied to your edit right away — no AI step. (Person effects still go through the agents.)'
          : 'Tap a card to add it to your prompt, then send it to the agent.'}
      </AppText>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabsScroll} contentContainerStyle={styles.tabs}>
        {FX_TABS.map((t) => {
          const on = t.key === tab;
          return (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              accessibilityRole="tab"
              accessibilityLabel={t.label}
              accessibilityState={{ selected: on }}
              testID={`fx-tab-${t.key}`}
              style={[styles.tab, on && styles.tabOn]}
            >
              <AppText size="xs" weight="semibold" color={on ? studio.white : studio.muted}>
                {t.label}
                {data ? ` ${countFor(t.key)}` : ''}
              </AppText>
            </Pressable>
          );
        })}
      </ScrollView>

      <TextInput
        value={query}
        onChangeText={setQuery}
        placeholder="Search effects…"
        placeholderTextColor={studio.faint}
        style={styles.search}
        testID="fx-search"
        accessibilityLabel="Search effects"
      />

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {!data && !error ? (
          <View style={styles.state} testID="fx-loading">
            <ActivityIndicator color={studio.blue} />
            <AppText size="xs" color={studio.muted}>
              Loading effects…
            </AppText>
          </View>
        ) : null}
        {error ? (
          <View style={styles.state} testID="fx-error">
            <AppText size="xs" color={studio.red}>
              Could not load effects: {error}
            </AppText>
            <AppText size="xs" color={studio.blue} onPress={() => {
                setError(null);
                setAttempt((n) => n + 1);
              }} testID="fx-retry">
              Retry
            </AppText>
          </View>
        ) : null}
        {data && items.length === 0 ? (
          <View style={styles.state} testID="fx-empty">
            <AppText size="xs" color={studio.muted}>
              {query.trim() ? `Nothing matches “${query.trim()}”.` : 'Nothing in this category yet.'}
            </AppText>
          </View>
        ) : null}
        <View style={styles.grid}>
          {items.map((it) => {
            const key = `${tab}:${it.id}`;
            const isAdded = added === key;
            return (
              <Pressable
                key={key}
                onPress={() => pick(it)}
                accessibilityRole="button"
                accessibilityLabel={`Add ${it.name}`}
                testID={`fx-card-${it.id}`}
                style={({ pressed }) => [styles.card, isAdded && styles.cardAdded, pressed && styles.pressed]}
              >
                {tab === 'color' ? (
                  <View testID={`fx-swatch-${it.id}`}>
                    <GradientPreview colors={lookColors(it.id)} width={36} height={24} radius={6} />
                  </View>
                ) : (
                  <View style={styles.glyph}>
                    <AppText size="sm" weight="bold" color={studio.cyan}>
                      {FX_GLYPHS[tab] ?? '✦'}
                    </AppText>
                  </View>
                )}
                <AppText size="sm" weight="semibold" numberOfLines={1}>
                  {it.name}
                </AppText>
                <AppText size="xs" color={studio.muted} numberOfLines={1}>
                  {it.description}
                </AppText>
                {isAdded ? (
                  <View style={styles.addedBadge} testID="fx-added">
                    <AppText size="xs" weight="semibold" color={studio.white}>
                      {mode === 'apply' && manualOpFor(tab, it) ? '⚡ applying' : '+ added'}
                    </AppText>
                  </View>
                ) : null}
              </Pressable>
            );
          })}
        </View>
      </ScrollView>
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
  modeRow: { flexDirection: 'row', gap: 6 },
  headerRow: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  tabsScroll: { flexGrow: 0 },
  tabs: { gap: 6 },
  tab: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5, borderWidth: 1, borderColor: studio.border },
  tabOn: { backgroundColor: studio.blue, borderColor: studio.blue },
  search: {
    backgroundColor: studio.card,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: studio.border,
    color: studio.text,
    paddingHorizontal: 10,
    height: 34,
    fontSize: 13,
  },
  scroll: { flex: 1 },
  content: { paddingBottom: 12, gap: 8 },
  state: { alignItems: 'center', gap: 6, paddingVertical: 16 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  card: {
    width: '48%',
    backgroundColor: studio.card,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: studio.border,
    padding: 8,
    gap: 4,
    position: 'relative',
  },
  cardAdded: { borderColor: studio.green },
  pressed: { opacity: 0.75 },
  glyph: {
    width: 36,
    height: 24,
    borderRadius: 6,
    backgroundColor: studio.cardHover,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addedBadge: {
    position: 'absolute',
    top: 6,
    right: 6,
    backgroundColor: studio.green,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
});
