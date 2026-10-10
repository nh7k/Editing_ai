import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { PromptLibraryResponse } from '../../api/types';
import { AppText } from '../AppText';
import { studio } from './theme';

/** Ready-made professional briefs ("boost prompts"): one tap sends the brief to the agents. */
export function TemplatesPanel({ onSend, busy, style }: { onSend: (prompt: string) => void; busy?: boolean; style?: StyleProp<ViewStyle> }) {
  const [data, setData] = useState<PromptLibraryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getPrompts()
      .then((r) => alive && setData(r))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <View style={[styles.panel, style]} testID="templates-panel">
      <AppText size="md" weight="semibold">
        Pro templates
      </AppText>
      <AppText size="xs" color={studio.muted}>
        Briefs written like a professional editor would. Tap one — the agents do the rest.
        {data ? ` ${data.prompts.length} templates · ${data.genres.length} video types · ${data.skills} skills.` : ''}
      </AppText>
      {!data && !error ? <ActivityIndicator color={studio.blue} /> : null}
      {error ? (
        <AppText size="xs" color={studio.red}>
          Could not load templates: {error}
        </AppText>
      ) : null}
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {data?.prompts.map((p) => (
          <Pressable key={p.id} onPress={() => !busy && onSend(p.prompt)} accessibilityRole="button"
            accessibilityLabel={p.title} testID={`template-${p.id}`}
            style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
            <AppText size="sm" weight="semibold">
              {p.title}
            </AppText>
            <AppText size="xs" color={studio.muted}>
              {p.does}
            </AppText>
          </Pressable>
        ))}
      </ScrollView>
      <View />
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { width: 340, backgroundColor: studio.panel, borderRadius: 16, borderWidth: 1, borderColor: studio.border, padding: 14, gap: 8 },
  scroll: { flex: 1 },
  content: { gap: 8, paddingBottom: 12 },
  card: { backgroundColor: studio.card, borderRadius: 12, borderWidth: 1, borderColor: studio.border, padding: 10, gap: 3 },
  pressed: { opacity: 0.75 },
});
