import { useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage } from '../api/client';
import type { Project } from '../api/types';
import {
  AppText,
  Button,
  Card,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  Screen,
  StatusPill,
} from '../components';
import { useAsync } from '../hooks/useAsync';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import type { TabScreenProps } from '../navigation/types';
import { useSettings } from '../store/settings';
import { colors, radius, spacing } from '../theme';
import { formatDate, formatDuration } from '../utils/format';

type Props = TabScreenProps<'Projects'>;

export function ProjectsScreen({ navigation }: Props) {
  // Re-fetch when the backend URL changes in Settings.
  const { baseUrl } = useSettings();
  const projects = useAsync(() => api.listProjects(), baseUrl);
  useRefreshOnFocus(navigation, () => void projects.reload(true));
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const create = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setCreateError('Give your project a name.');
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const project = await api.createProject(trimmed);
      setName('');
      projects.setData((prev) => [project, ...(prev ?? [])]);
      navigation.navigate('Import', { projectId: project.id, projectName: project.name });
    } catch (e) {
      setCreateError(errorMessage(e));
    } finally {
      setCreating(false);
    }
  };

  const header = (
    <Card style={styles.createCard}>
      <AppText size="lg" weight="bold">
        New project
      </AppText>
      <AppText size="sm" muted>
        Import clips, describe the edit, and let the agents cut it.
      </AppText>
      <View style={styles.createRow}>
        <TextInput
          value={name}
          onChangeText={setName}
          placeholder="e.g. Lisbon trip reel"
          placeholderTextColor={colors.textFaint}
          style={styles.input}
          onSubmitEditing={create}
          returnKeyType="done"
          accessibilityLabel="Project name"
          testID="project-name-input"
        />
        <Button title="Create" onPress={create} loading={creating} testID="create-project" />
      </View>
      {createError ? <InlineError message={createError} /> : null}
    </Card>
  );

  let body: React.ReactNode;
  if (projects.loading && !projects.data) {
    body = <LoadingState label="Loading projects..." />;
  } else if (projects.error && !projects.data) {
    body = <ErrorState title="Could not load projects" message={projects.error} onRetry={() => projects.reload()} />;
  } else {
    body = (
      <FlatList
        data={projects.data ?? []}
        keyExtractor={(p) => p.id}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={projects.refreshing}
            onRefresh={() => projects.reload(true)}
            tintColor={colors.accent}
            colors={[colors.accent]}
          />
        }
        ListEmptyComponent={
          <EmptyState
            title="No projects yet"
            message="Create your first project above to start editing."
            icon="+"
          />
        }
        renderItem={({ item }) => (
          <ProjectRow
            project={item}
            onOpen={() => navigation.navigate('Editor', { projectId: item.id, projectName: item.name })}
            onClips={() => navigation.navigate('Import', { projectId: item.id, projectName: item.name })}
          />
        )}
        ItemSeparatorComponent={() => <View style={styles.sep} />}
      />
    );
  }

  return (
    <Screen>
      {projects.error && projects.data ? <InlineError message={projects.error} /> : null}
      {body}
    </Screen>
  );
}

function ProjectRow({ project, onOpen, onClips }: { project: Project; onOpen: () => void; onClips: () => void }) {
  const total = project.clips.reduce((s, c) => s + (c.duration || 0), 0);
  return (
    // Not pressable itself: on web a pressable card would nest <button>s (invalid HTML).
    <Card testID={`project-${project.id}`}>
      <View style={styles.rowBetween}>
        <AppText size="lg" weight="semibold" numberOfLines={1} style={styles.flex}>
          {project.name}
        </AppText>
        {project.has_output ? <StatusPill label="Rendered" tone="success" /> : <StatusPill label="Draft" />}
      </View>
      <AppText size="sm" muted style={styles.meta}>
        {`${project.clips.length} clip${project.clips.length === 1 ? '' : 's'} · ${formatDuration(total)} · ${formatDate(project.created_at)}`}
      </AppText>
      <View style={styles.actions}>
        <Button title="Open editor" small onPress={onOpen} testID={`open-${project.id}`} />
        <Button title="Clips" small variant="secondary" onPress={onClips} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  list: { padding: spacing.lg, paddingBottom: spacing.xxl },
  createCard: { gap: spacing.sm, marginBottom: spacing.lg },
  createRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center', marginTop: spacing.xs },
  input: {
    flex: 1,
    minHeight: 46,
    backgroundColor: colors.cardAlt,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    color: colors.text,
    fontSize: 15,
  },
  sep: { height: spacing.md },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm },
  flex: { flex: 1 },
  meta: { marginTop: 4 },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
});
