import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { Platform, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage, type ClaudeConnect } from '../api/client';
import type { Health, LlmHealth } from '../api/types';
import { AppText, Button, Card, InlineError, Screen, StatusPill } from '../components';
import { useAsync } from '../hooks/useAsync';
import {
  DEFAULT_BASE_URL,
  isValidBaseUrl,
  normalizeBaseUrl,
  setApiKey,
  setBaseUrl,
  useSettings,
} from '../store/settings';
import { colors, radius, spacing } from '../theme';

interface HealthRow {
  key: string;
  label: string;
  ok: boolean;
}

function flag(v: boolean | string | null | undefined): { label: string; ok: boolean } {
  if (typeof v === 'boolean') return { label: v ? 'yes' : 'no', ok: v };
  if (typeof v === 'string') return { label: v, ok: !/^(false|no|missing|unavailable|error)$/i.test(v) };
  return { label: 'unknown', ok: false };
}

/** The in-process planner model: null = mock planner (rules only), false = still downloading. */
export function llmRow(llm: LlmHealth | null | undefined): { label: string; ok: boolean } {
  const model = llm?.model ?? 'unknown model';
  if (!llm || llm.available === null || llm.available === undefined) {
    return { label: 'rules only (mock planner)', ok: true };
  }
  return llm.available
    ? { label: `ready · ${model}`, ok: true }
    : { label: `downloading / not cached · ${model}`, ok: false };
}

function healthRows(h: Health): HealthRow[] {
  return [
    { key: 'ffmpeg', ...flag(h.ffmpeg) },
    { key: 'whisper', ...flag(h.whisper) },
    { key: 'AI model', ...llmRow(h.llm) },
    { key: 'auth', label: h.auth_required ? 'required' : 'off', ok: true },
  ];
}

/** "Connect to Claude": the claude.ai connector URL + the steps (like a remote-agents setup page). */
function ConnectClaudeCard() {
  const settings = useSettings();
  const state = useAsync<ClaudeConnect>(() => api.connectClaude(), settings.baseUrl);
  const info = state.data ?? null;
  const error = state.error;
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!info?.url) return;
    await Clipboard.setStringAsync(info.url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <Card style={styles.gap} testID="connect-claude">
      <AppText size="lg" weight="bold">
        Connect to Claude
      </AppText>
      <AppText size="sm" muted>
        Edit by chatting on claude.ai: Claude uses CutMind&apos;s tools and the edits appear here as new versions. The
        link is a secret — anyone with it can edit your projects.
      </AppText>
      {info?.url ? (
        <>
          <StatusPill label="READY" tone="success" />
          <AppText size="xs" selectable style={styles.url} testID="connect-claude-url">
            {info.url}
          </AppText>
          <Button title={copied ? 'Copied' : 'Copy link'} onPress={copy} testID="connect-claude-copy" />
          {info.steps.map((s, i) => (
            <AppText key={s} size="sm">{`${i + 1}. ${s}`}</AppText>
          ))}
        </>
      ) : info ? (
        <>
          <StatusPill label="NOT RUNNING" tone="warning" />
          <AppText size="sm">Start it on the laptop (a terminal in the CutMind folder), then refresh:</AppText>
          <AppText size="xs" selectable style={styles.url}>
            {info.start}
          </AppText>
        </>
      ) : null}
      {error ? <InlineError message={error} /> : null}
      <Button title="Refresh" variant="ghost" small onPress={() => state.reload()} />
    </Card>
  );
}

export function SettingsScreen() {
  const settings = useSettings();
  // null = untouched: show the stored URL.
  const [draftValue, setDraft] = useState<string | null>(null);
  const draft = draftValue ?? settings.baseUrl;
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  // API key draft: null = untouched (show the stored key, masked).
  const [keyDraftValue, setKeyDraft] = useState<string | null>(null);
  const keyDraft = keyDraftValue ?? settings.apiKey;
  const [keySaving, setKeySaving] = useState(false);
  const [keySaved, setKeySaved] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  const saveKey = async () => {
    setKeySaving(true);
    setKeyError(null);
    try {
      await setApiKey(keyDraft);
      setKeyDraft(null);
      setKeySaved(true);
      setTimeout(() => setKeySaved(false), 2000);
    } catch (e) {
      setKeyError(errorMessage(e));
    } finally {
      setKeySaving(false);
    }
  };
  const keyDirty = keyDraft.trim() !== settings.apiKey;

  const save = async () => {
    if (!isValidBaseUrl(draft)) {
      setError('Enter a valid URL, e.g. http://192.168.1.20:8000');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await setBaseUrl(draft);
      setDraft(null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setError(null);
    setHealth(null);
    try {
      setHealth(await api.healthAt(normalizeBaseUrl(draft)));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setTesting(false);
    }
  };

  const dirty = normalizeBaseUrl(draft) !== settings.baseUrl;

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Card style={styles.gap}>
          <AppText size="lg" weight="bold">
            Backend URL
          </AppText>
          <AppText size="sm" muted>
            Where the CutMind backend runs. Android emulator: http://10.0.2.2:8000. Real phone: your PC&apos;s LAN IP, e.g.
            http://192.168.1.20:8000.
          </AppText>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType={Platform.OS === 'web' ? 'default' : 'url'}
            placeholder={DEFAULT_BASE_URL}
            placeholderTextColor={colors.textFaint}
            style={styles.input}
            accessibilityLabel="Backend URL"
            testID="base-url-input"
          />
          <View style={styles.row}>
            <Button title={saved ? 'Saved' : 'Save'} onPress={save} loading={saving} disabled={!dirty && !saved} style={styles.flex} />
            <Button title="Test connection" variant="secondary" onPress={test} loading={testing} style={styles.flex} />
          </View>
          <Button title="Reset to default" variant="ghost" small onPress={() => setDraft(DEFAULT_BASE_URL)} />
          {error ? <InlineError message={error} /> : null}
          {health ? (
            <View style={styles.health} testID="health-result">
              <View style={styles.row}>
                <StatusPill label={health.status === 'ok' ? 'CONNECTED' : health.status.toUpperCase()} tone={health.status === 'ok' ? 'success' : 'warning'} />
                <AppText size="sm" muted>{`v${health.version} · planner ${health.planner_mode}`}</AppText>
              </View>
              {healthRows(health).map((r) => (
                <View key={r.key} style={styles.row}>
                  <AppText size="sm" style={styles.key}>
                    {r.key}
                  </AppText>
                  <AppText size="sm" color={r.ok ? colors.mint : colors.coral} style={styles.flex}>
                    {r.label}
                  </AppText>
                </View>
              ))}
              {health.auth_required && !settings.apiKey ? (
                <AppText size="xs" color={colors.coral}>
                  This backend requires an API key. Set it below.
                </AppText>
              ) : null}
            </View>
          ) : null}
        </Card>
        <Card style={styles.gap}>
          <AppText size="lg" weight="bold">
            API key (optional)
          </AppText>
          <AppText size="sm" muted>
            Only needed when the backend runs with CUTMIND_API_KEY set. It is sent as the X-API-Key header (and as
            api_key on video/thumbnail links). Leave empty otherwise.
          </AppText>
          <TextInput
            value={keyDraft}
            onChangeText={setKeyDraft}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
            textContentType="password"
            autoComplete="off"
            placeholder="No API key"
            placeholderTextColor={colors.textFaint}
            style={styles.input}
            accessibilityLabel="API key"
            testID="api-key-input"
          />
          <Button
            title={keySaved ? 'Saved' : 'Save API key'}
            onPress={saveKey}
            loading={keySaving}
            disabled={!keyDirty && !keySaved}
          />
          {keyError ? <InlineError message={keyError} /> : null}
        </Card>
        <ConnectClaudeCard />
        <AppText size="xs" muted center>
          CutMind mobile · UI only, all editing runs on your backend.
        </AppText>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md },
  gap: { gap: spacing.sm },
  row: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center' },
  flex: { flex: 1 },
  input: {
    minHeight: 46,
    backgroundColor: colors.cardAlt,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    color: colors.text,
    fontSize: 15,
  },
  health: { gap: 6, backgroundColor: colors.cardAlt, borderRadius: radius.md, padding: spacing.md },
  key: { width: 80 },
  url: { backgroundColor: colors.cardAlt, borderRadius: radius.md, padding: spacing.sm, color: colors.text },
});
