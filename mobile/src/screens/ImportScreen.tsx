import * as ImagePicker from 'expo-image-picker';
import { useLayoutEffect, useState } from 'react';
import { FlatList, Image, RefreshControl, StyleSheet, View } from 'react-native';

import { api, errorMessage, type UploadProgress } from '../api/client';
import type { Clip, UploadFile } from '../api/types';
import {
  AppText,
  Button,
  Card,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  ProgressBar,
  Screen,
} from '../components';
import { useAsync } from '../hooks/useAsync';
import type { RootScreenProps } from '../navigation/types';
import { colors, radius, spacing } from '../theme';
import { formatBytes, formatDuration } from '../utils/format';

type Props = RootScreenProps<'Import'>;

/** Convert picker assets into upload descriptors that work on web and native. */
export function assetsToUploadFiles(assets: ImagePicker.ImagePickerAsset[]): UploadFile[] {
  return assets.map((a, i) => {
    const fallbackExt = a.mimeType?.split('/')[1] ?? 'mp4';
    return {
      uri: a.uri,
      name: a.fileName ?? (a.file && 'name' in a.file ? a.file.name : `clip-${Date.now()}-${i}.${fallbackExt}`),
      type: a.mimeType ?? a.file?.type ?? 'video/mp4',
      file: a.file,
    };
  });
}

export function ImportScreen({ navigation, route }: Props) {
  const { projectId, projectName } = route.params;
  const project = useAsync(() => api.getProject(projectId), projectId);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: project.data?.name ?? projectName ?? 'Import clips' });
  }, [navigation, project.data?.name, projectName]);

  const pickAndUpload = async () => {
    setUploadError(null);
    let result: ImagePicker.ImagePickerResult;
    try {
      result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['videos'],
        allowsMultipleSelection: true,
        quality: 1,
      });
    } catch (e) {
      setUploadError(`Could not open the gallery: ${errorMessage(e)}`);
      return;
    }
    if (result.canceled || result.assets.length === 0) return;

    setUploading(true);
    setProgress({ loaded: 0, total: 0, fraction: 0 });
    try {
      const res = await api.uploadClips(projectId, assetsToUploadFiles(result.assets), setProgress);
      project.setData((prev) => (prev ? { ...prev, clips: [...prev.clips, ...res.clips] } : prev));
    } catch (e) {
      setUploadError(errorMessage(e));
    } finally {
      setUploading(false);
      setProgress(null);
    }
  };

  const removeClip = async (clip: Clip) => {
    if (confirmId !== clip.id) {
      setConfirmId(clip.id);
      return;
    }
    setConfirmId(null);
    setDeletingId(clip.id);
    try {
      await api.deleteClip(projectId, clip.id);
      project.setData((prev) => (prev ? { ...prev, clips: prev.clips.filter((c) => c.id !== clip.id) } : prev));
    } catch (e) {
      setUploadError(errorMessage(e));
    } finally {
      setDeletingId(null);
    }
  };

  if (project.loading && !project.data) {
    return (
      <Screen>
        <LoadingState label="Loading clips..." />
      </Screen>
    );
  }
  if (project.error && !project.data) {
    return (
      <Screen>
        <ErrorState title="Could not load project" message={project.error} onRetry={() => project.reload()} />
      </Screen>
    );
  }

  const clips = project.data?.clips ?? [];

  return (
    <Screen>
      <FlatList
        data={clips}
        keyExtractor={(c) => c.id}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl refreshing={project.refreshing} onRefresh={() => project.reload(true)} tintColor={colors.accent} />
        }
        ListHeaderComponent={
          <Card style={styles.header}>
            <AppText size="lg" weight="bold">
              Import clips
            </AppText>
            <AppText size="sm" muted>
              Pick one or more videos from your gallery. They are uploaded to your CutMind backend.
            </AppText>
            <Button
              title={uploading ? 'Uploading...' : 'Pick videos'}
              onPress={pickAndUpload}
              loading={uploading}
              testID="pick-videos"
            />
            {progress ? (
              <View style={styles.progress}>
                <ProgressBar value={progress.fraction} testID="upload-progress" />
                <AppText size="xs" muted>
                  {progress.total > 0
                    ? `${Math.round(progress.fraction * 100)}% · ${formatBytes(progress.loaded)} of ${formatBytes(progress.total)}`
                    : 'Preparing upload...'}
                </AppText>
              </View>
            ) : null}
            {uploadError ? <InlineError message={uploadError} /> : null}
            {clips.length > 0 ? (
              <Button
                title="Continue to editor"
                variant="secondary"
                onPress={() => navigation.navigate('Editor', { projectId, projectName: project.data?.name })}
              />
            ) : null}
          </Card>
        }
        ListEmptyComponent={<EmptyState title="No clips yet" message="Pick videos to add them to this project." icon="+" />}
        ItemSeparatorComponent={() => <View style={styles.sep} />}
        renderItem={({ item }) => (
          <Card style={styles.clipRow} testID={`clip-${item.id}`}>
            <Image
              source={{ uri: api.thumbnailUrl(projectId, item.id) }}
              style={styles.thumb}
              accessibilityLabel={`Thumbnail of ${item.filename}`}
            />
            <View style={styles.flex}>
              <AppText weight="semibold" numberOfLines={1}>
                {item.filename}
              </AppText>
              <AppText size="xs" muted>
                {`${formatDuration(item.duration)} · ${item.width}x${item.height} · ${Math.round(item.fps)} fps`}
              </AppText>
              <AppText size="xs" muted>
                {`${formatBytes(item.size_bytes)}${item.has_audio ? ' · audio' : ' · no audio'}`}
              </AppText>
            </View>
            <Button
              title={confirmId === item.id ? 'Confirm' : 'Delete'}
              variant="danger"
              small
              loading={deletingId === item.id}
              onPress={() => removeClip(item)}
              accessibilityLabel={`Delete ${item.filename}`}
            />
          </Card>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  list: { padding: spacing.lg, paddingBottom: spacing.xxl },
  header: { gap: spacing.sm, marginBottom: spacing.lg },
  progress: { gap: 4 },
  sep: { height: spacing.sm },
  clipRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md },
  thumb: { width: 72, height: 72, borderRadius: radius.sm, backgroundColor: colors.cardAlt },
  flex: { flex: 1, gap: 2 },
});
