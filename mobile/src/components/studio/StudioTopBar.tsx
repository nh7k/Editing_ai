import { Pressable, StyleSheet, View } from 'react-native';

import type { AspectRatio, OutputFormat } from '../../api/types';
import { AppText } from '../AppText';
import { studio } from './theme';
import { Dropdown, IconButton, type MenuItem } from './ui';

export const ASPECTS: AspectRatio[] = ['16:9', '9:16', '1:1'];
/** Preview zoom levels relative to "fit". */
export const ZOOM_LEVELS = [0.5, 0.75, 1, 1.25, 1.5, 2];

export const EXPORT_FORMATS: { key: OutputFormat; label: string }[] = [
  { key: 'mp4', label: 'MP4 video' },
  { key: 'gif', label: 'GIF' },
  { key: 'mp3', label: 'MP3 audio' },
];

/** Formats that can be downloaded right now: mp4 once a render exists, gif / mp3 only when rendered as extras. */
export function exportAvailability(hasOutput: boolean, extras: readonly string[] | undefined): Record<OutputFormat, boolean> {
  const ex = extras ?? [];
  return { mp4: hasOutput, gif: hasOutput && ex.includes('gif'), mp3: hasOutput && ex.includes('mp3') };
}

export interface StudioTopBarProps {
  title: string;
  aspect: AspectRatio;
  onAspect: (a: AspectRatio) => void;
  zoom: number;
  onZoom: (z: number) => void;
  hasOutput: boolean;
  extras?: readonly string[];
  onShare: () => void;
  onExport: (format: OutputFormat) => void;
  onHome: () => void;
  onHistory?: () => void;
  /** Undo / redo the last edit (versions are kept, nothing is rendered again). */
  onUndo?: () => void;
  onRedo?: () => void;
  /** Opens "Copy an Edit" (rebuild a liked edit from this footage). */
  onCopyEdit?: () => void;
  /** Opens the template gallery with this project preselected. */
  onTemplates?: () => void;
}

export function StudioTopBar({
  title,
  aspect,
  onAspect,
  zoom,
  onZoom,
  hasOutput,
  extras,
  onShare,
  onExport,
  onHome,
  onHistory,
  onUndo,
  onRedo,
  onCopyEdit,
  onTemplates,
}: StudioTopBarProps) {
  const avail = exportAvailability(hasOutput, extras);
  const zoomIdx = ZOOM_LEVELS.indexOf(zoom);
  const stepZoom = (dir: 1 | -1) => {
    const i = zoomIdx < 0 ? ZOOM_LEVELS.indexOf(1) : zoomIdx;
    const next = ZOOM_LEVELS[Math.max(0, Math.min(ZOOM_LEVELS.length - 1, i + dir))];
    onZoom(next);
  };
  const exportItems: MenuItem[] = EXPORT_FORMATS.map((f) => ({
    key: f.key,
    label: f.label,
    disabled: !avail[f.key],
    hint: avail[f.key] ? undefined : f.key === 'mp4' ? 'no render yet' : 'ask for it in chat',
  }));

  return (
    <View style={styles.bar} testID="studio-topbar">
      <View style={styles.left}>
        <Pressable onPress={onHome} accessibilityRole="button" accessibilityLabel="Back to projects" style={styles.brand}>
          <View style={styles.logo}>
            <AppText size="sm" weight="bold" color={studio.white}>
              ◆
            </AppText>
          </View>
          <AppText size="lg" weight="bold">
            CutMind
          </AppText>
          <AppText size="lg" weight="regular" color={studio.muted}>
            Studio
          </AppText>
        </Pressable>
        <AppText size="sm" numberOfLines={1} style={styles.title} testID="studio-title">
          {title}
        </AppText>
      </View>

      <View style={styles.center}>
        <Dropdown
          testID="aspect-select"
          accessibilityLabel="Aspect ratio"
          triggerStyle={styles.pill}
          trigger={
            <AppText size="sm" weight="medium">
              ▭ {aspect} ▾
            </AppText>
          }
          items={ASPECTS.map((a) => ({ key: a, label: a }))}
          onSelect={(k) => onAspect(k as AspectRatio)}
          menuWidth={110}
        />
        <View style={styles.pill}>
          <IconButton glyph="−" label="Zoom out" size={26} onPress={() => stepZoom(-1)} disabled={zoomIdx === 0} testID="zoom-out" />
          <Dropdown
            testID="zoom-select"
            accessibilityLabel="Preview zoom"
            triggerStyle={styles.zoomLabel}
            trigger={
              <AppText size="sm" weight="medium">
                {zoom === 1 ? 'Fit' : `${Math.round(zoom * 100)}%`} ▾
              </AppText>
            }
            items={[{ key: '1', label: 'Fit' }, ...ZOOM_LEVELS.filter((z) => z !== 1).map((z) => ({ key: String(z), label: `${z * 100}%` }))]}
            onSelect={(k) => onZoom(Number(k))}
            menuWidth={100}
          />
          <IconButton
            glyph="+"
            label="Zoom in"
            size={26}
            onPress={() => stepZoom(1)}
            disabled={zoomIdx === ZOOM_LEVELS.length - 1}
            testID="zoom-in"
          />
        </View>
        <IconButton glyph="↶" label="Undo" size={28} disabled={!onUndo} onPress={onUndo} testID="topbar-undo" />
        <IconButton glyph="↷" label="Redo" size={28} disabled={!onRedo} onPress={onRedo} testID="topbar-redo" />
      </View>

      <View style={styles.right}>
        {onCopyEdit ? (
          <Pressable onPress={onCopyEdit} accessibilityRole="button" accessibilityLabel="Copy an Edit" testID="studio-copy-edit"
            style={({ pressed }) => [styles.shareBtn, pressed && styles.pressed]}>
            <AppText size="sm" weight="semibold" numberOfLines={1}>
              🎬 Copy an Edit
            </AppText>
          </Pressable>
        ) : null}
        {onTemplates ? (
          <Pressable onPress={onTemplates} accessibilityRole="button" accessibilityLabel="Templates" testID="studio-templates"
            style={({ pressed }) => [styles.shareBtn, pressed && styles.pressed]}>
            <AppText size="sm" weight="semibold" numberOfLines={1}>
              ▤ Templates
            </AppText>
          </Pressable>
        ) : null}
        <IconButton glyph="⟲" label="Version history" onPress={onHistory} />
        <Pressable
          onPress={onShare}
          disabled={!hasOutput}
          accessibilityRole="button"
          accessibilityLabel="Share"
          testID="share-button"
          style={({ pressed }) => [styles.shareBtn, pressed && styles.pressed, !hasOutput && styles.disabled]}
        >
          <AppText size="sm" weight="semibold">
            Share
          </AppText>
        </Pressable>
        <Dropdown
          testID="export"
          accessibilityLabel="Export"
          align="right"
          menuWidth={190}
          triggerStyle={styles.exportBtn}
          trigger={
            <AppText size="sm" weight="semibold" color="#0B0C10">
              ⇪ Export ▾
            </AppText>
          }
          items={exportItems}
          onSelect={(k) => onExport(k as OutputFormat)}
        />
        <View style={styles.avatar} accessibilityLabel="Account">
          <AppText size="sm" weight="bold" color={studio.white}>
            U
          </AppText>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    height: 56,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    backgroundColor: studio.bg,
    zIndex: 30,
  },
  left: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 20, minWidth: 0 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  logo: {
    width: 26,
    height: 26,
    borderRadius: 8,
    backgroundColor: studio.violet,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { flexShrink: 1, color: studio.text },
  center: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  right: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 10 },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    height: 36,
    paddingHorizontal: 10,
    borderRadius: 10,
    backgroundColor: studio.panel,
    borderWidth: 1,
    borderColor: studio.border,
    justifyContent: 'center',
  },
  zoomLabel: { paddingHorizontal: 8, height: 30, justifyContent: 'center' },
  shareBtn: {
    height: 36,
    paddingHorizontal: 16,
    borderRadius: 10,
    backgroundColor: studio.card,
    borderWidth: 1,
    borderColor: studio.border,
    justifyContent: 'center',
  },
  exportBtn: {
    height: 36,
    paddingHorizontal: 16,
    borderRadius: 10,
    backgroundColor: studio.white,
    justifyContent: 'center',
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: studio.violet,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pressed: { opacity: 0.75 },
  disabled: { opacity: 0.4 },
});
