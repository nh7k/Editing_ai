import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { ManualOp, PlanAudio, Song, SongsResponse, UploadFile } from '../../api/types';
import { AppText } from '../AppText';
import { studio } from './theme';

export const MUSIC_STEPS = [0, 25, 50, 75, 100] as const;
export const VOICE_STEPS = [50, 100, 150, 200] as const;

/** Web: open the browser's file picker (audio, or a video whose sound is used). Native: not supported yet. */
export function pickSongFile(): Promise<UploadFile | null> {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return Promise.resolve(null);
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'audio/*,video/*';
    input.style.display = 'none';
    const done = (f: UploadFile | null) => {
      input.remove();
      resolve(f);
    };
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      done(file ? { uri: '', name: file.name, type: file.type || 'audio/mpeg', file } : null);
    });
    input.addEventListener('cancel', () => done(null));
    document.body.appendChild(input);
    input.click();
  });
}

export interface SoundsPanelProps {
  projectId: string;
  /** The current plan's sound settings; null / undefined when there is no edit yet. */
  audio?: PlanAudio | null;
  hasPlan: boolean;
  /** Instant manual change (no AI). */
  onApply: (ops: ManualOp[], label: string) => void;
  /** Start an AI edit cut to this song. */
  onEditToSong: (name: string) => void;
  busy?: boolean;
  /** File picker; defaults to the web file input (tests inject their own). */
  pickFile?: () => Promise<UploadFile | null>;
}

function Step({ label, on, onPress, testID, disabled }: { label: string; on: boolean; onPress: () => void; testID: string; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityState={{ selected: on, disabled }}
      testID={testID} style={[styles.chip, on && styles.chipOn, disabled && styles.off]}>
      <AppText size="xs" weight="semibold" color={on ? studio.white : studio.muted}>
        {label}
      </AppText>
    </Pressable>
  );
}

function SmallButton({ label, onPress, testID, color = studio.blue, disabled }: { label: string; onPress: () => void; testID: string; color?: string; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityState={{ disabled }} testID={testID}
      style={({ pressed }) => [styles.small, { borderColor: color }, (pressed || disabled) && styles.off]}>
      <AppText size="xs" weight="semibold" color={color}>
        {label}
      </AppText>
    </Pressable>
  );
}

function songMeta(s: Song): string {
  const parts: string[] = [];
  if (typeof s.tempo === 'number' && s.tempo > 0) parts.push(`${Math.round(s.tempo)} bpm`);
  if (typeof s.drop === 'number') parts.push(`drop at ${s.drop.toFixed(1)}s`);
  if (typeof s.duration === 'number' && s.duration > 0) parts.push(`${Math.round(s.duration)}s long`);
  return parts.join(' · ');
}

const FEEL_COLOR: Record<string, string> = { slow: studio.cyan, medium: studio.indigo, fast: studio.purple };

/** Songs for the edit (upload your own or pick from the library) + instant sound controls of the current edit. */
export function SoundsPanel({ projectId, audio, hasPlan, onApply, onEditToSong, busy, pickFile = pickSongFile }: SoundsPanelProps) {
  const [data, setData] = useState<SongsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let alive = true;
    api
      .listSongs(projectId)
      .then((r) => {
        if (!alive) return;
        setData(r);
        setError(null);
      })
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [projectId, reloadKey]);

  const canPick = Platform.OS === 'web' || pickFile !== pickSongFile;

  const upload = async () => {
    if (uploading) return;
    setNote(null);
    if (!canPick) {
      setNote('Upload songs from the web app for now.');
      return;
    }
    try {
      const file = await pickFile();
      if (!file) return;
      setUploading(true);
      const song = await api.uploadSong(projectId, file);
      setNote(`“${song.name}” added and selected.`);
      load();
    } catch (e) {
      setNote(`Upload failed: ${errorMessage(e)}`);
    } finally {
      setUploading(false);
    }
  };

  const select = async (name: string | null) => {
    setNote(null);
    try {
      const r = await api.selectSong(projectId, name);
      setData((d) =>
        d
          ? {
              selected: r?.selected ?? name,
              project: d.project.map((s) => ({ ...s, selected: s.name === (r?.selected ?? name) })),
              library: d.library.map((s) => ({ ...s, selected: s.name === (r?.selected ?? name) })),
            }
          : d,
      );
    } catch (e) {
      setNote(errorMessage(e));
    }
  };

  const remove = async (name: string) => {
    setNote(null);
    try {
      await api.deleteSong(projectId, name);
      load();
    } catch (e) {
      setNote(errorMessage(e));
    }
  };

  const muted = !!audio?.mute;
  const musicPct = typeof audio?.music_volume === 'number' ? Math.round(audio.music_volume * 100) : null;
  const voicePct = Math.round((typeof audio?.voice_volume === 'number' ? audio.voice_volume : 1) * 100);
  const currentMusic = typeof audio?.music === 'string' && audio.music ? audio.music : null;

  const renderSong = (s: Song) => {
    const selected = s.selected || data?.selected === s.name;
    const meta = songMeta(s);
    return (
      <View key={`${s.source}-${s.name}`} style={[styles.card, selected && styles.cardOn]} testID={`song-${s.name}`}>
        <View style={styles.row}>
          <AppText size="sm" weight="semibold" numberOfLines={1} style={styles.flex}>
            {s.name}
          </AppText>
          {s.feel ? (
            <View style={[styles.badge, { borderColor: FEEL_COLOR[s.feel] ?? studio.border }]} testID={`song-feel-${s.name}`}>
              <AppText size="xs" color={FEEL_COLOR[s.feel] ?? studio.muted}>
                {s.feel}
              </AppText>
            </View>
          ) : null}
          {s.source === 'project' ? (
            <Pressable onPress={() => void remove(s.name)} accessibilityRole="button" accessibilityLabel={`Delete ${s.name}`}
              testID={`song-delete-${s.name}`} hitSlop={6}>
              <AppText size="sm" color={studio.red}>×</AppText>
            </Pressable>
          ) : null}
        </View>
        {meta ? (
          <AppText size="xs" color={studio.muted}>
            {meta}
          </AppText>
        ) : null}
        <View style={styles.wrap}>
          <SmallButton label={selected ? '✓ In use' : 'Use'} onPress={() => void select(s.name)} testID={`song-use-${s.name}`}
            color={selected ? studio.green : studio.blue} />
          <SmallButton label="✦ Edit to this beat" onPress={() => onEditToSong(s.name)} testID={`song-edit-${s.name}`}
            color={studio.violet} disabled={busy} />
          {hasPlan ? (
            <SmallButton label="Use this song here (no re-cut)" testID={`song-here-${s.name}`} color={studio.cyan} disabled={busy}
              onPress={() => onApply([{ op: 'set_audio', music: s.name }], `Song: ${s.name}`)} />
          ) : null}
        </View>
      </View>
    );
  };

  return (
    <View style={styles.panel} testID="sounds-panel">
      <AppText size="md" weight="semibold">
        Sounds
      </AppText>
      <AppText size="xs" color={studio.muted}>
        Add your own song (or a video&apos;s sound). The agents cut the edit to its beat and drop.
      </AppText>
      <Pressable onPress={() => void upload()} disabled={uploading} accessibilityRole="button" testID="sounds-upload"
        accessibilityState={{ disabled: uploading, busy: uploading }} style={[styles.upload, uploading && styles.off]}>
        {uploading ? <ActivityIndicator color={studio.white} size="small" /> : null}
        <AppText size="sm" weight="semibold" color={studio.white}>
          {uploading ? 'Uploading…' : '♫ Upload your song'}
        </AppText>
      </Pressable>
      {note ? (
        <AppText size="xs" color={note.startsWith('Upload failed') ? studio.red : studio.muted} testID="sounds-note">
          {note}
        </AppText>
      ) : null}
      {!data && !error ? <ActivityIndicator color={studio.blue} /> : null}
      {error ? (
        <AppText size="xs" color={studio.red} testID="sounds-error">
          Could not load songs: {error}
        </AppText>
      ) : null}
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {hasPlan ? (
          <View style={styles.section} testID="sounds-edit">
            <AppText size="xs" weight="semibold" color={studio.muted}>
              Sound of this edit{currentMusic ? ` · ♫ ${currentMusic}` : ''}
            </AppText>
            <View style={styles.wrap}>
              <Step label={muted ? 'Original sound: off' : 'Original sound: on'} on={!muted} testID="audio-mute-toggle"
                disabled={busy} onPress={() => onApply([{ op: 'set_audio', mute: !muted }], muted ? 'Original sound on' : 'Original sound off')} />
              {currentMusic ? (
                <SmallButton label="Remove song" testID="audio-remove-song" color={studio.red} disabled={busy}
                  onPress={() => onApply([{ op: 'set_audio', no_music: true }], 'Remove song')} />
              ) : null}
            </View>
            <AppText size="xs" color={studio.muted}>Music volume</AppText>
            <View style={styles.wrap}>
              {MUSIC_STEPS.map((p) => (
                <Step key={p} label={`${p}%`} on={musicPct === p} testID={`music-vol-${p}`} disabled={busy}
                  onPress={() => onApply([{ op: 'set_audio', music_volume: p / 100 }], `Music volume ${p}%`)} />
              ))}
            </View>
            <AppText size="xs" color={studio.muted}>Voice / original level</AppText>
            <View style={styles.wrap}>
              {VOICE_STEPS.map((p) => (
                <Step key={p} label={`${p}%`} on={voicePct === p} testID={`voice-vol-${p}`} disabled={busy}
                  onPress={() => onApply([{ op: 'set_audio', voice_volume: p / 100 }], `Voice level ${p}%`)} />
              ))}
            </View>
          </View>
        ) : null}
        {data ? (
          <>
            <AppText size="xs" weight="semibold" color={studio.muted}>
              Your songs
            </AppText>
            {data.project.length ? (
              data.project.map(renderSong)
            ) : (
              <AppText size="xs" color={studio.faint} testID="sounds-empty">
                No songs yet — upload one above.
              </AppText>
            )}
            {data.library.length ? (
              <>
                <AppText size="xs" weight="semibold" color={studio.muted}>
                  Library
                </AppText>
                {data.library.map(renderSong)}
              </>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { width: 340, backgroundColor: studio.panel, borderRadius: 16, borderWidth: 1, borderColor: studio.border, padding: 14, gap: 8 },
  scroll: { flex: 1 },
  content: { gap: 8, paddingBottom: 12 },
  section: { backgroundColor: studio.card, borderRadius: 12, borderWidth: 1, borderColor: studio.border, padding: 10, gap: 6 },
  card: { backgroundColor: studio.card, borderRadius: 12, borderWidth: 1, borderColor: studio.border, padding: 10, gap: 5 },
  cardOn: { borderColor: studio.blue, backgroundColor: studio.cardHover },
  row: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  flex: { flex: 1 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 7, paddingVertical: 1 },
  chip: { borderRadius: 999, paddingHorizontal: 9, paddingVertical: 4, borderWidth: 1, borderColor: studio.border },
  chipOn: { backgroundColor: studio.blue, borderColor: studio.blue },
  small: { borderRadius: 8, borderWidth: 1, paddingHorizontal: 8, paddingVertical: 4 },
  upload: { flexDirection: 'row', gap: 8, justifyContent: 'center', backgroundColor: studio.violet, borderRadius: 10,
    paddingVertical: 10, alignItems: 'center' },
  off: { opacity: 0.45 },
});
