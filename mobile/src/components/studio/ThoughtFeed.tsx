import { useEffect, useState, type ReactNode } from 'react';
import { Animated, Platform, Pressable, StyleSheet, View } from 'react-native';

import type { LiveThoughtEntry } from '../../utils/liveTimeline';
import { AppText } from '../AppText';
import { studio } from './theme';

const NATIVE_DRIVER = Platform.OS !== 'web';

/** Chip colour of each workflow agent (unknown agents: muted). */
const AGENT_COLORS: Record<string, string> = {
  director: studio.violet,
  analyzer: studio.cyan,
  audio: studio.green,
  cutter: studio.blue,
  color: studio.purple,
  colour: studio.purple,
  effects: studio.indigo,
  render: studio.muted,
  renderer: studio.muted,
  review: studio.text,
  reviewer: studio.text,
};

export function agentColor(agent: string): string {
  return AGENT_COLORS[agent.trim().toLowerCase()] ?? studio.muted;
}

function AgentChip({ agent }: { agent: string }) {
  const c = agentColor(agent);
  return (
    <View style={[styles.chip, { borderColor: c, backgroundColor: `${c}26` }]}>
      <AppText size="xs" weight="semibold" color={c} numberOfLines={1}>
        {agent.toLowerCase()}
      </AppText>
    </View>
  );
}

/** Fades + slides a thought in when it mounts. */
function SlideIn({ children, testID }: { children: ReactNode; testID?: string }) {
  const [v] = useState(() => new Animated.Value(0));
  useEffect(() => {
    const anim = Animated.timing(v, { toValue: 1, duration: 280, useNativeDriver: NATIVE_DRIVER });
    anim.start();
    return () => anim.stop();
  }, [v]);
  const translateY = v.interpolate({ inputRange: [0, 1], outputRange: [8, 0] });
  return (
    <Animated.View testID={testID} style={[styles.thought, { opacity: v, transform: [{ translateY }] }]}>
      {children}
    </Animated.View>
  );
}

/** "•••" that cycles while an agent works. */
function TypingDots() {
  const [n, setN] = useState(1);
  useEffect(() => {
    const id = setInterval(() => setN((x) => (x % 3) + 1), 450);
    return () => clearInterval(id);
  }, []);
  return (
    <AppText size="sm" weight="bold" color={studio.cyan} style={styles.dots}>
      {'•'.repeat(n)}
    </AppText>
  );
}

function ThoughtList({ thoughts }: { thoughts: LiveThoughtEntry[] }) {
  return (
    <>
      {thoughts.map((t) => (
        <SlideIn key={t.key} testID={`chat-thought-${t.key}`}>
          <AgentChip agent={t.agent} />
          <AppText size="xs" color={studio.text} style={styles.text}>
            {t.text}
          </AppText>
        </SlideIn>
      ))}
    </>
  );
}

export interface ThoughtFeedProps {
  thoughts: LiveThoughtEntry[];
  /** The job is still running: thoughts are listed open, one by one, with a typing indicator. */
  running: boolean;
  /** Agent working right now (typing indicator), null when unknown. */
  worker: string | null;
}

/**
 * The agents' plain-words decisions inside a chat turn. While the job runs they appear one by one with
 * the agent's chip and a typing indicator; afterwards they fold under "Agent ne kya socha (N)".
 */
export function ThoughtFeed({ thoughts, running, worker }: ThoughtFeedProps) {
  const [open, setOpen] = useState(false);
  if (!running && !thoughts.length) return null;

  if (running) {
    return (
      <View style={styles.box} testID="chat-thoughts">
        <AppText size="xs" weight="semibold" color={studio.cyan}>
          AGENT KYA SOCH RAHA HAI
        </AppText>
        <ThoughtList thoughts={thoughts} />
        <View style={styles.typing} testID="chat-thought-typing">
          {worker ? <AgentChip agent={worker} /> : null}
          <AppText size="xs" color={studio.muted}>
            {thoughts.length ? 'soch raha hai' : 'Agents tayyar ho rahe hain'}
          </AppText>
          <TypingDots />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.box} testID="chat-thoughts">
      <Pressable
        onPress={() => setOpen((o) => !o)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        testID="chat-thoughts-toggle"
      >
        <AppText size="xs" weight="semibold" color={studio.cyan}>
          {open ? '▾' : '▸'} Agent ne kya socha ({thoughts.length})
        </AppText>
      </Pressable>
      {open ? <ThoughtList thoughts={thoughts} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { backgroundColor: studio.card, borderRadius: 12, padding: 10, gap: 6, borderWidth: 1, borderColor: studio.border },
  thought: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  chip: { borderRadius: 999, borderWidth: 1, paddingHorizontal: 7, paddingVertical: 1, maxWidth: 96 },
  text: { flex: 1, paddingTop: 1 },
  typing: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dots: { minWidth: 24 },
});
