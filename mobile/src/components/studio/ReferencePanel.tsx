import { useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { ReferenceInfo, UploadFile } from '../../api/types';
import { AppText } from '../AppText';
import { studio } from './theme';

/** Prompt that makes the agents copy the uploaded reference edit (rhythm, colour, B&W, flashes, aspect, length, song). */
export const EDIT_LIKE_REFERENCE_PROMPT = 'is reference video jaisa mera video edit karo';

/** Web: open the browser's file picker for a video. Native: not supported yet. */
export function pickReferenceFile(): Promise<UploadFile | null> {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return Promise.resolve(null);
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'video/*';
    input.style.display = 'none';
    const done = (f: UploadFile | null) => {
      input.remove();
      resolve(f);
    };
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      done(file ? { uri: '', name: file.name, type: file.type || 'video/mp4', file } : null);
    });
    input.addEventListener('cancel', () => done(null));
    document.body.appendChild(input);
    input.click();
  });
}

export interface ReferencePanelProps {
  projectId: string;
  /** Start an AI edit that copies the reference (same path as sending a chat prompt). */
  onEditLikeReference: () => void;
  busy?: boolean;
  /** File picker; defaults to the web file input (tests inject their own). */
  pickFile?: () => Promise<UploadFile | null>;
  style?: StyleProp<ViewStyle>;
}

/** "Edit like a video": upload someone else's edit; the agents copy its style onto your footage. */
export function ReferencePanel({ projectId, onEditLikeReference, busy, pickFile = pickReferenceFile, style }: ReferencePanelProps) {
  const [ref, setRef] = useState<ReferenceInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getReference(projectId)
      .then((r) => {
        if (!alive) return;
        setRef(r);
        setError(null);
      })
      .catch((e) => alive && setError(`Could not load the reference: ${errorMessage(e)}`))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [projectId]);

  const canPick = Platform.OS === 'web' || pickFile !== pickReferenceFile;

  const upload = async () => {
    if (uploading) return;
    setNote(null);
    setError(null);
    if (!canPick) {
      setNote('Upload from the web app for now.');
      return;
    }
    try {
      const file = await pickFile();
      if (!file) return;
      setUploading(true);
      const info = await api.uploadReference(projectId, file);
      setRef(info);
    } catch (e) {
      setError(`Upload failed: ${errorMessage(e)}`);
    } finally {
      setUploading(false);
    }
  };

  const remove = async () => {
    if (removing) return;
    setNote(null);
    setError(null);
    setRemoving(true);
    try {
      await api.deleteReference(projectId);
      setRef(null);
    } catch (e) {
      setError(`Could not remove: ${errorMessage(e)}`);
    } finally {
      setRemoving(false);
    }
  };

  const song = typeof ref?.recipe?.song === 'string' && ref.recipe.song ? ref.recipe.song : null;

  return (
    <View style={[styles.panel, style]} testID="reference-panel">
      <AppText size="md" weight="semibold">
        Edit like a video
      </AppText>
      <AppText size="xs" color={studio.muted}>
        Upload an edit you like — the agents copy its cut rhythm, colours, black &amp; white, flashes and its song onto your
        footage.
      </AppText>
      {loading ? <ActivityIndicator color={studio.blue} testID="reference-loading" /> : null}
      {ref ? (
        <View style={styles.card} testID="reference-summary">
          <AppText size="sm" weight="semibold" numberOfLines={1}>
            🎬 {ref.name}
          </AppText>
          <View style={styles.wrap}>
            {ref.summary.map((line, i) => (
              <View key={`${i}-${line}`} style={styles.chip}>
                <AppText size="xs" color={studio.text}>
                  {line}
                </AppText>
              </View>
            ))}
          </View>
          {song ? (
            <AppText size="xs" color={studio.muted}>
              ♫ Its soundtrack is saved as “{song}”.
            </AppText>
          ) : null}
          <Pressable onPress={onEditLikeReference} disabled={busy} accessibilityRole="button" testID="reference-edit"
            accessibilityState={{ disabled: !!busy }} style={({ pressed }) => [styles.primary, (pressed || busy) && styles.off]}>
            <AppText size="sm" weight="semibold" color={studio.white}>
              ✦ Edit my video like this
            </AppText>
          </Pressable>
          <View style={styles.row}>
            <Pressable onPress={() => void upload()} disabled={uploading} accessibilityRole="button" testID="reference-upload"
              accessibilityState={{ disabled: uploading, busy: uploading }}
              style={({ pressed }) => [styles.small, { borderColor: studio.blue }, (pressed || uploading) && styles.off]}>
              <AppText size="xs" weight="semibold" color={studio.blue}>
                {uploading ? 'Uploading…' : 'Replace'}
              </AppText>
            </Pressable>
            <Pressable onPress={() => void remove()} disabled={removing} accessibilityRole="button" testID="reference-remove"
              accessibilityState={{ disabled: removing }}
              style={({ pressed }) => [styles.small, { borderColor: studio.red }, (pressed || removing) && styles.off]}>
              <AppText size="xs" weight="semibold" color={studio.red}>
                Remove
              </AppText>
            </Pressable>
          </View>
        </View>
      ) : !loading ? (
        <Pressable onPress={() => void upload()} disabled={uploading} accessibilityRole="button" testID="reference-upload"
          accessibilityState={{ disabled: uploading, busy: uploading }} style={[styles.upload, uploading && styles.off]}>
          {uploading ? <ActivityIndicator color={studio.white} size="small" /> : null}
          <AppText size="sm" weight="semibold" color={studio.white}>
            {uploading ? 'Uploading… (measuring cuts, colour, beat)' : '🎬 Upload reference video'}
          </AppText>
        </Pressable>
      ) : null}
      {note ? (
        <AppText size="xs" color={studio.muted} testID="reference-note">
          {note}
        </AppText>
      ) : null}
      {error ? (
        <AppText size="xs" color={studio.red} testID="reference-error">
          {error}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { width: 340, backgroundColor: studio.panel, borderRadius: 16, borderWidth: 1, borderColor: studio.border, padding: 14, gap: 8 },
  card: { backgroundColor: studio.card, borderRadius: 12, borderWidth: 1, borderColor: studio.border, padding: 10, gap: 8 },
  row: { flexDirection: 'row', gap: 6 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { borderRadius: 999, paddingHorizontal: 9, paddingVertical: 3, borderWidth: 1, borderColor: studio.border, backgroundColor: studio.cardHover },
  small: { borderRadius: 8, borderWidth: 1, paddingHorizontal: 8, paddingVertical: 4 },
  primary: { backgroundColor: studio.violet, borderRadius: 10, paddingVertical: 10, alignItems: 'center' },
  upload: { flexDirection: 'row', gap: 8, justifyContent: 'center', backgroundColor: studio.violet, borderRadius: 10,
    paddingVertical: 10, alignItems: 'center' },
  off: { opacity: 0.45 },
});
