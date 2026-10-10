import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { colors, radius, spacing } from '../theme';
import { AppText } from './AppText';
import { Chip } from './Chip';

export const QUICK_PROMPTS = [
  '30s travel reel, fast cuts, warm color, captions, remove silence',
  'Trim to 15s',
  'Remove silence',
  'Add captions',
  '9:16 reel with warm color',
  'Fast cuts with music',
  'Add fade transitions',
] as const;

/** A quick-prompt chip: `label` is shown, `prompt` is what goes into the input (and to the backend). */
export interface QuickPrompt {
  label: string;
  prompt: string;
}

/** Chips for newer backend features; prompts are worded so the planner parses them reliably. */
export const FEATURE_PROMPTS: readonly QuickPrompt[] = [
  { label: '✨ Auto edit', prompt: 'mast sa edit kar do' },
  { label: 'Arrange clips', prompt: 'arrange the clips in the right order' },
  { label: 'Rotate 90° & mirror', prompt: 'rotate 90 and mirror it' },
  { label: 'Play backwards', prompt: 'play the video backwards' },
  { label: 'Sepia + vignette', prompt: 'sepia color with vignette' },
  { label: 'Mute + calm music', prompt: 'mute the sound and add calm music' },
  { label: 'Remove idle parts', prompt: 'remove idle parts' },
  { label: 'Export GIF & MP3', prompt: 'export gif and mp3' },
  { label: 'Louder + sharpen', prompt: 'make it louder and sharpen' },
];

/** Every chip in display order: the classic prompts (label = prompt) followed by the feature chips. */
export const QUICK_PROMPT_CHIPS: readonly QuickPrompt[] = [
  ...QUICK_PROMPTS.map((p) => ({ label: p, prompt: p })),
  ...FEATURE_PROMPTS,
];

export interface ChatInputProps {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  sending?: boolean;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({ value, onChangeText, onSend, sending, disabled, placeholder }: ChatInputProps) {
  const [voiceHint, setVoiceHint] = useState(false);
  const canSend = !disabled && !sending && value.trim().length > 0;

  useEffect(() => {
    if (!voiceHint) return;
    const t = setTimeout(() => setVoiceHint(false), 2500);
    return () => clearTimeout(t);
  }, [voiceHint]);

  return (
    <View style={styles.wrap}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {QUICK_PROMPT_CHIPS.map((c) => (
          <Chip
            key={c.label}
            label={c.label}
            onPress={() => onChangeText(c.prompt)}
            selected={value === c.prompt}
            disabled={sending}
          />
        ))}
      </ScrollView>
      {voiceHint ? (
        <AppText size="xs" color={colors.amber} testID="voice-hint">
          Voice input coming soon
        </AppText>
      ) : null}
      <View style={styles.row}>
        <Pressable
          onPress={() => setVoiceHint(true)}
          style={({ pressed }) => [styles.iconBtn, pressed && styles.pressed]}
          accessibilityRole="button"
          accessibilityLabel="Voice input"
          testID="mic-button"
        >
          <AppText size="lg">🎙</AppText>
        </Pressable>
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder ?? 'Describe your edit...'}
          placeholderTextColor={colors.textFaint}
          style={styles.input}
          multiline
          editable={!sending}
          accessibilityLabel="Edit prompt"
          testID="prompt-input"
        />
        <Pressable
          onPress={onSend}
          disabled={!canSend}
          style={({ pressed }) => [styles.sendBtn, !canSend && styles.disabled, pressed && styles.pressed]}
          accessibilityRole="button"
          accessibilityLabel="Send prompt"
          accessibilityState={{ disabled: !canSend, busy: !!sending }}
          testID="send-button"
        >
          <AppText weight="bold" color="#FFFFFF">
            {sending ? '...' : '↑'}
          </AppText>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  chips: { gap: spacing.sm, paddingVertical: 2 },
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: spacing.sm },
  input: {
    flex: 1,
    minHeight: 46,
    maxHeight: 120,
    backgroundColor: colors.card,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingTop: 12,
    paddingBottom: 12,
    color: colors.text,
    fontSize: 15,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  iconBtn: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  sendBtn: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  disabled: { opacity: 0.4 },
  pressed: { opacity: 0.8 },
});
