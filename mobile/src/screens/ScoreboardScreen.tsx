import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';

import { api } from '../api/client';
import type { AgentStat } from '../api/types';
import { AppText, Card, EmptyState, ErrorState, InlineError, LoadingState, Screen } from '../components';
import { useAsync } from '../hooks/useAsync';
import { useSettings } from '../store/settings';
import { colors, radius, spacing } from '../theme';
import { formatDate, formatDelta } from '../utils/format';

export function rankAgents(agents: AgentStat[]): AgentStat[] {
  return [...agents].sort((a, b) => b.total_points - a.total_points || (b.avg_score ?? 0) - (a.avg_score ?? 0));
}

export function deltaColor(delta: number): string {
  if (delta > 0) return colors.mint;
  if (delta < 0) return colors.coral;
  return colors.textMuted;
}

export function ScoreboardScreen() {
  const { baseUrl } = useSettings();
  const board = useAsync(async () => rankAgents((await api.getScoreboard()).agents), baseUrl);

  if (board.loading && !board.data) {
    return (
      <Screen>
        <LoadingState label="Loading scoreboard..." />
      </Screen>
    );
  }
  if (board.error && !board.data) {
    return (
      <Screen>
        <ErrorState title="Could not load scoreboard" message={board.error} onRetry={() => board.reload()} />
      </Screen>
    );
  }

  return (
    <Screen>
      {board.error ? <InlineError message={board.error} /> : null}
      <FlatList
        data={board.data ?? []}
        keyExtractor={(a) => a.name}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl refreshing={board.refreshing} onRefresh={() => board.reload(true)} tintColor={colors.accent} />
        }
        ListHeaderComponent={
          <AppText size="sm" muted style={styles.intro}>
            Agents earn +10 per passed review check and lose 15 per failed one. Your thumbs up/down adds ±5.
          </AppText>
        }
        ListEmptyComponent={<EmptyState title="No agents yet" message="Run an edit to see agent scores here." icon="#" />}
        ItemSeparatorComponent={() => <View style={styles.sep} />}
        renderItem={({ item, index }) => <AgentCard agent={item} rank={index + 1} />}
      />
    </Screen>
  );
}

function AgentCard({ agent, rank }: { agent: AgentStat; rank: number }) {
  return (
    <Card testID={`agent-card-${agent.name}`}>
      <View style={styles.row}>
        <View style={[styles.rank, rank === 1 && styles.rankFirst]}>
          <AppText weight="bold" color={rank === 1 ? '#FFFFFF' : colors.text} testID={`rank-${agent.name}`}>
            {`#${rank}`}
          </AppText>
        </View>
        <View style={styles.flex}>
          <AppText size="lg" weight="semibold">
            {agent.name}
          </AppText>
          <AppText size="xs" muted numberOfLines={2}>
            {agent.role}
          </AppText>
        </View>
        <View style={styles.points}>
          <AppText size="lg" weight="bold">
            {`${agent.total_points}`}
          </AppText>
          <AppText size="xs" muted>
            points
          </AppText>
        </View>
      </View>
      <View style={styles.stats}>
        <Stat label="Avg score" value={agent.avg_score === null ? '-' : `${Math.round(agent.avg_score)}`} />
        <Stat label="Runs" value={`${agent.runs}`} />
        <Stat
          label="Last run"
          value={formatDelta(agent.last_delta)}
          color={deltaColor(agent.last_delta)}
          testID={`delta-${agent.name}`}
        />
      </View>
      {agent.recent_lessons.length > 0 ? (
        <View style={styles.lessons}>
          <AppText size="xs" weight="semibold" muted>
            RECENT LESSONS
          </AppText>
          {agent.recent_lessons.slice(0, 3).map((l, i) => (
            <AppText key={`${l.created_at}-${i}`} size="sm" muted>
              {`• ${l.text}`}
              <AppText size="xs" color={colors.textFaint}>{`  ${formatDate(l.created_at)}`}</AppText>
            </AppText>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

function Stat({ label, value, color, testID }: { label: string; value: string; color?: string; testID?: string }) {
  return (
    <View style={styles.stat}>
      <AppText size="md" weight="semibold" color={color} testID={testID}>
        {value}
      </AppText>
      <AppText size="xs" muted>
        {label}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  list: { padding: spacing.lg, paddingBottom: spacing.xxl },
  intro: { marginBottom: spacing.md },
  sep: { height: spacing.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  rank: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.cardAlt,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rankFirst: { backgroundColor: colors.accent },
  flex: { flex: 1 },
  points: { alignItems: 'flex-end' },
  stats: {
    flexDirection: 'row',
    marginTop: spacing.md,
    backgroundColor: colors.cardAlt,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
  },
  stat: { flex: 1, alignItems: 'center' },
  lessons: { marginTop: spacing.md, gap: 4 },
});
