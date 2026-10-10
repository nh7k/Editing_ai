import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { Clip, PlanOverlay } from '../../api/types';
import { formatTimecode } from '../../utils/studioTimeline';
import { AppText } from '../AppText';
import { studio } from './theme';
import { Badge, GradientPreview, IconButton } from './ui';

interface Asset {
  projectId: string;
  clip: Clip;
}

export interface MediaPanelProps {
  projectId: string;
  clips: Clip[];
  overlays: PlanOverlay[];
  /** Opens the clip picker / upload flow. */
  onAdd: () => void;
  onSeeAllOverlays: () => void;
}

const CARD_W = 146;
const THUMB_H = 86;

export function MediaPanel({ projectId, clips, overlays, onAdd, onSeeAllOverlays }: MediaPanelProps) {
  const [scope, setScope] = useState<'project' | 'all'>('project');
  const [query, setQuery] = useState('');
  const [longestFirst, setLongestFirst] = useState(false);
  const [all, setAll] = useState<Asset[] | null>(null);
  const [allError, setAllError] = useState<string | null>(null);

  useEffect(() => {
    if (scope !== 'all' || all) return;
    let alive = true;
    api
      .listProjects()
      .then((ps) => {
        if (alive) setAll(ps.flatMap((p) => p.clips.map((clip) => ({ projectId: p.id, clip }))));
      })
      .catch((e) => {
        if (alive) setAllError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, [scope, all]);

  const assets = useMemo(() => {
    const base: Asset[] = scope === 'project' ? clips.map((clip) => ({ projectId, clip })) : (all ?? []);
    const q = query.trim().toLowerCase();
    const filtered = q ? base.filter((a) => a.clip.filename.toLowerCase().includes(q)) : base;
    return longestFirst ? [...filtered].sort((a, b) => b.clip.duration - a.clip.duration) : filtered;
  }, [scope, clips, projectId, all, query, longestFirst]);

  return (
    <View style={styles.panel} testID="media-panel">
      <View style={styles.segment}>
        {(['project', 'all'] as const).map((s) => (
          <Pressable
            key={s}
            onPress={() => setScope(s)}
            accessibilityRole="tab"
            accessibilityState={{ selected: scope === s }}
            testID={`media-scope-${s}`}
            style={[styles.segBtn, scope === s && styles.segBtnOn]}
          >
            <AppText size="sm" weight={scope === s ? 'semibold' : 'regular'} color={scope === s ? studio.text : studio.muted}>
              {s === 'project' ? 'This project' : 'All assets'}
            </AppText>
          </Pressable>
        ))}
      </View>

      <View style={styles.searchRow}>
        <View style={styles.search}>
          <AppText size="sm" color={studio.muted}>
            ⌕
          </AppText>
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Search"
            placeholderTextColor={studio.muted}
            style={styles.searchInput}
            testID="media-search"
          />
        </View>
        <IconButton glyph="+" label="Add clips" onPress={onAdd} style={styles.squareBtn} testID="media-add" />
        <IconButton
          glyph="⏷"
          label={longestFirst ? 'Sorted longest first' : 'Sort by length'}
          active={longestFirst}
          onPress={() => setLongestFirst((v) => !v)}
          style={styles.squareBtn}
          testID="media-filter"
        />
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>
        <View style={styles.grid}>
          {scope === 'project' ? (
            <Pressable onPress={onAdd} accessibilityRole="button" accessibilityLabel="Add media" style={styles.addTile} testID="media-add-tile">
              <AppText size="xl" color={studio.muted}>
                ⊕
              </AppText>
              <AppText size="sm" color={studio.muted}>
                Add
              </AppText>
            </Pressable>
          ) : null}
          {assets.map((a) => (
            <View key={`${a.projectId}/${a.clip.id}`} style={styles.card} testID={`clip-card-${a.clip.id}`}>
              <View style={styles.thumbWrap}>
                <Image source={{ uri: api.thumbnailUrl(a.projectId, a.clip.id) }} style={styles.thumb} resizeMode="cover" />
                <View style={styles.duration}>
                  <AppText size="xs" weight="semibold" color={studio.white}>
                    {formatTimecode(a.clip.duration)}
                  </AppText>
                </View>
                <View style={styles.ready}>
                  <Badge label="Ready" color={studio.blue} />
                </View>
              </View>
              <AppText size="xs" color={studio.muted} numberOfLines={1}>
                {a.clip.filename}
              </AppText>
            </View>
          ))}
        </View>
        {scope === 'all' && !all && !allError ? <ActivityIndicator color={studio.blue} /> : null}
        {allError ? (
          <AppText size="xs" color={studio.red}>
            {allError}
          </AppText>
        ) : null}
        {scope === 'project' && clips.length === 0 ? (
          <AppText size="sm" color={studio.muted}>
            No clips yet — add some to start editing.
          </AppText>
        ) : null}

        <View style={styles.overlayHeader}>
          <AppText size="md" weight="semibold" testID="overlay-count">
            {overlays.length} {overlays.length === 1 ? 'overlay' : 'overlays'}
          </AppText>
          <Pressable onPress={onSeeAllOverlays} accessibilityRole="button" testID="overlays-see-all">
            <AppText size="sm" color={studio.muted}>
              See all
            </AppText>
          </Pressable>
        </View>
        <View style={styles.grid}>
          {overlays.slice(0, 4).map((o, i) => (
            <OverlayCard key={`${o.label}-${i}`} overlay={o} />
          ))}
        </View>
        {overlays.length === 0 ? (
          <AppText size="xs" color={studio.muted}>
            Overlays from your edit plan show up here.
          </AppText>
        ) : null}
      </ScrollView>
    </View>
  );
}

export function OverlayCard({ overlay, width = CARD_W }: { overlay: PlanOverlay; width?: number }) {
  return (
    <View style={[styles.overlayCard, { width }]} testID="overlay-card">
      <GradientPreview colors={overlay.colors ?? []} width={width} height={THUMB_H} radius={12} />
      <View style={styles.onTimeline}>
        <Badge label="On timeline" color={studio.blue} />
      </View>
      <AppText size="xs" color={studio.muted} numberOfLines={1} style={styles.overlayLabel}>
        {overlay.label}
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
    gap: 12,
  },
  segment: { flexDirection: 'row', backgroundColor: studio.card, borderRadius: 12, padding: 3 },
  segBtn: { flex: 1, alignItems: 'center', paddingVertical: 7, borderRadius: 10 },
  segBtnOn: { backgroundColor: studio.bg },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  search: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: studio.card,
    borderRadius: 10,
    paddingHorizontal: 10,
    height: 36,
  },
  searchInput: { flex: 1, color: studio.text, fontSize: 14, height: 34 },
  squareBtn: { backgroundColor: studio.card, width: 36, height: 36 },
  scroll: { flex: 1 },
  scrollContent: { gap: 12, paddingBottom: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  addTile: {
    width: CARD_W,
    height: THUMB_H,
    borderRadius: 12,
    backgroundColor: studio.card,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  card: { width: CARD_W, gap: 4 },
  thumbWrap: { width: CARD_W, height: THUMB_H, borderRadius: 12, overflow: 'hidden', backgroundColor: studio.card },
  thumb: { width: '100%', height: '100%' },
  duration: {
    position: 'absolute',
    top: 6,
    right: 6,
    backgroundColor: 'rgba(0,0,0,0.65)',
    borderRadius: 6,
    paddingHorizontal: 5,
    paddingVertical: 1,
  },
  ready: { position: 'absolute', left: 6, bottom: 6 },
  overlayHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 },
  overlayCard: { gap: 4 },
  onTimeline: { position: 'absolute', top: 6, left: 6 },
  overlayLabel: { marginTop: 2 },
});
