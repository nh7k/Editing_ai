import { useEffect, useLayoutEffect, useState } from 'react';
import { ActivityIndicator, Image, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage, type UploadProgress } from '../api/client';
import type { Blueprint, BlueprintShot, CopyEditState, UploadFile } from '../api/types';
import { AppText, Button, Card, Chip, ErrorState, InlineError, LoadingState, ProgressBar, Screen } from '../components';
import { useAsync } from '../hooks/useAsync';
import { openEditorWithJob, type EditorNavigation } from '../navigation/openEditor';
import type { RootScreenProps } from '../navigation/types';
import { colors, radius, spacing } from '../theme';
import { pickOneVideo } from '../utils/pickVideo';

type Props = RootScreenProps<'CopyEdit'> & {
  /** File picker; defaults to the gallery / browser picker (tests inject their own). */
  pickFile?: () => Promise<UploadFile | null>;
};

/** Chat label of a Copy-an-Edit job in the editor. */
export const COPY_EDIT_JOB_LABEL = '🎬 Copy an Edit';

/** Badges of one shot of the liked edit. */
export function shotBadges(shot: BlueprintShot): string[] {
  const out: string[] = [];
  if (shot.bw) out.push('B&W');
  if (shot.flash) out.push('Flash');
  if (shot.zoom) out.push('Zoom');
  return out;
}

/** How often the screen asks for the analysis state while the agent watches the video. */
export const COPY_EDIT_POLL_MS = 1500;
/** Stop polling after this many failed requests in a row. */
const MAX_POLL_FAILURES = 5;

/** "0:04" */
function clock(s: number): string {
  const v = Math.max(0, Math.round(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
}

const BADGE_COLOR: Record<string, string> = { 'B&W': colors.text, Flash: colors.amber, Zoom: colors.mint };

/**
 * "Copy an Edit": upload a finished edit you like; the agent watches all of it, shot by shot, and rebuilds the
 * same edit (same shots, lengths, B&W, flashes, zooms, song) from this project's footage.
 */
export function CopyEditScreen({ navigation, route, pickFile = pickOneVideo }: Props) {
  const { projectId, projectName } = route.params;
  const analysis = useAsync<CopyEditState | null>(() => api.getCopyEdit(projectId), projectId);
  const [watching, setWatching] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [extra, setExtra] = useState('');
  const [keepSound, setKeepSound] = useState(true);
  const [running, setRunning] = useState(false);
  const [naming, setNaming] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  useLayoutEffect(() => {
    navigation.setOptions({ title: projectName ? `Copy an Edit · ${projectName}` : 'Copy an Edit' });
  }, [navigation, projectName]);

  // The agent watches the video in the background (1–3 min): poll while it is analysing.
  const status = analysis.data?.status;
  const setAnalysis = analysis.setData;
  useEffect(() => {
    if (status !== 'analyzing') return;
    let alive = true;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const next = await api.getCopyEdit(projectId);
        if (!alive) return;
        failures = 0;
        setPollError(null);
        setAnalysis(() => next);
        if (next?.status === 'ready') setTemplateName(next.blueprint.name.replace(/\.[^.]+$/, ''));
        if (next?.status === 'analyzing') timer = setTimeout(tick, COPY_EDIT_POLL_MS);
      } catch (e) {
        if (!alive) return;
        failures += 1;
        setPollError(errorMessage(e));
        if (failures < MAX_POLL_FAILURES) timer = setTimeout(tick, COPY_EDIT_POLL_MS);
      }
    };
    timer = setTimeout(tick, COPY_EDIT_POLL_MS);
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [status, projectId, setAnalysis]);

  const upload = async () => {
    if (watching) return;
    setError(null);
    let file: UploadFile | null;
    try {
      file = await pickFile();
    } catch (e) {
      setError(`Could not open the picker: ${errorMessage(e)}`);
      return;
    }
    if (!file) return;
    setWatching(true);
    setProgress(null);
    setSaved(null);
    try {
      const next = await api.uploadCopyEdit(projectId, file, setProgress);
      setPollError(null);
      analysis.setData(() => next);
      if (next.status === 'ready') setTemplateName(next.blueprint.name.replace(/\.[^.]+$/, ''));
    } catch (e) {
      setError(`Video samajh nahi aaya: ${errorMessage(e)}`);
    } finally {
      setWatching(false);
      setProgress(null);
    }
  };

  const run = async () => {
    if (running) return;
    setError(null);
    setRunning(true);
    try {
      const prompt = extra.trim();
      const res = await api.runCopyEdit(projectId, { ...(prompt ? { prompt } : {}), keep_sound: keepSound });
      const name = analysis.data?.status === 'ready' ? analysis.data.blueprint.name : undefined;
      openEditorWithJob(navigation as unknown as EditorNavigation, {
        projectId,
        projectName,
        jobId: res.job_id,
        jobLabel: `${COPY_EDIT_JOB_LABEL}${name ? `: ${name}` : ''}${prompt ? ` · ${prompt}` : ''}`,
      });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRunning(false);
    }
  };

  const saveTemplate = async () => {
    const name = templateName.trim();
    if (!name) {
      setError('Template ka naam do.');
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const t = await api.saveCopyEditTemplate(projectId, name);
      setSaved(t.name);
      setNaming(false);
    } catch (e) {
      setError(`Template save nahi hua: ${errorMessage(e)}`);
    } finally {
      setSaving(false);
    }
  };

  if (analysis.loading && analysis.data === undefined && !watching) {
    return (
      <Screen>
        <LoadingState label="Loading…" />
      </Screen>
    );
  }
  if (analysis.error && analysis.data === undefined && !watching) {
    return (
      <Screen>
        <ErrorState title="Could not load Copy an Edit" message={analysis.error} onRetry={() => analysis.reload()} />
      </Screen>
    );
  }

  const current = watching ? null : (analysis.data ?? null);
  const bp = current?.status === 'ready' ? current.blueprint : null;
  const analyzing = current?.status === 'analyzing' ? current : null;
  const failed = current?.status === 'failed' ? current : null;

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" testID="copy-edit-screen">
        <Card style={styles.gap}>
          <AppText size="lg" weight="bold">
            Same edit banao
          </AppText>
          <AppText size="sm" muted>
            Koi edit pasand aaya? Upload karo — agent poora video shot by shot dekhega aur wahi edit tumhari footage se
            banayega: same shots, same lengths, B&amp;W, flashes, zooms aur wahi gaana.
          </AppText>
        </Card>

        {watching ? (
          <Card style={[styles.gap, styles.center]} testID="copy-uploading">
            <ActivityIndicator color={colors.accent} />
            <AppText weight="semibold" center>
              Video upload ho raha hai…
            </AppText>
            {progress ? (
              <>
                <ProgressBar value={progress.fraction} />
                <AppText size="xs" muted center>
                  {`${Math.round(progress.fraction * 100)}%`}
                </AppText>
              </>
            ) : null}
          </Card>
        ) : null}

        {analyzing ? (
          <Card style={styles.gap} testID="copy-watching">
            <View style={styles.rowGap}>
              <ActivityIndicator color={colors.accent} />
              <AppText weight="semibold" style={styles.flex}>
                Agent aapka video dekh raha hai…
              </AppText>
              <AppText size="sm" weight="semibold">
                {`${Math.round(Math.max(0, Math.min(1, analyzing.progress)) * 100)}%`}
              </AppText>
            </View>
            <ProgressBar value={analyzing.progress} testID="copy-progress" />
            <AppText size="xs" muted testID="copy-step">
              {analyzing.step || 'Shots, cuts, colour, flashes, text aur beat dekh raha hai'}
            </AppText>
            <AppText size="xs" color={colors.textFaint}>
              Isme 1–3 minute lagte hain. Aap yeh screen chhod ke wapas aa sakte ho.
            </AppText>
            {pollError ? <InlineError message={`${pollError} (retrying...)`} /> : null}
          </Card>
        ) : null}

        {failed ? (
          <Card style={styles.gap} testID="copy-failed">
            <AppText weight="semibold" color={colors.coral}>
              Video samajh nahi aaya
            </AppText>
            <AppText size="sm" color={colors.coral}>
              {failed.error}
            </AppText>
            <Button title="🎬 Dusra video chuno" onPress={() => void upload()} testID="copy-pick" />
          </Card>
        ) : null}

        {!watching && !current ? (
          <Card style={styles.gap} testID="copy-pick-card">
            <AppText weight="semibold">1. Pasand wala video chuno</AppText>
            <AppText size="sm" muted>
              Reel, short ya koi bhi finished edit (mp4 / mov).
            </AppText>
            <Button title="🎬 Video chuno" onPress={() => void upload()} testID="copy-pick" />
          </Card>
        ) : null}

        {bp ? <BlueprintCard blueprint={bp} onReplace={() => void upload()} /> : null}

        {bp ? (
          <Card style={styles.gap} testID="copy-run-card">
            <AppText weight="semibold">Kuch aur chahiye? (optional)</AppText>
            <TextInput
              value={extra}
              onChangeText={setExtra}
              placeholder="e.g. captions bhi laga, mera naam title me"
              placeholderTextColor={colors.textFaint}
              style={styles.input}
              multiline
              accessibilityLabel="Extra prompt"
              testID="copy-extra-prompt"
            />
            {bp.song ? (
              <View style={styles.row}>
                <Chip
                  label={keepSound ? '♫ Wahi gaana rakho' : '♫ Gaana mat lo'}
                  selected={keepSound}
                  onPress={() => setKeepSound((v) => !v)}
                  testID="copy-keep-sound"
                />
              </View>
            ) : null}
            <Button title="Mere video me same edit karo" onPress={() => void run()} loading={running} testID="copy-run" />
            {naming ? (
              <View style={styles.saveRow}>
                <TextInput
                  value={templateName}
                  onChangeText={setTemplateName}
                  placeholder="Template name"
                  placeholderTextColor={colors.textFaint}
                  style={[styles.input, styles.flex]}
                  accessibilityLabel="Template name"
                  testID="copy-template-name"
                  onSubmitEditing={() => void saveTemplate()}
                />
                <Button title="Save" small onPress={() => void saveTemplate()} loading={saving} testID="copy-template-save" />
                <Button title="Cancel" small variant="ghost" onPress={() => setNaming(false)} />
              </View>
            ) : (
              <Button
                title="Save as my template"
                variant="secondary"
                onPress={() => {
                  setSaved(null);
                  setTemplateName((n) => n || bp.name.replace(/\.[^.]+$/, ''));
                  setNaming(true);
                }}
                testID="copy-save-template"
              />
            )}
            {saved ? (
              <AppText size="sm" color={colors.mint} testID="copy-template-saved">
                {`Saved “${saved}” — Templates → Mine me milega.`}
              </AppText>
            ) : null}
          </Card>
        ) : null}

        {error ? <InlineError message={error} /> : null}
      </ScrollView>
    </Screen>
  );
}

function BlueprintCard({ blueprint: bp, onReplace }: { blueprint: Blueprint; onReplace: () => void }) {
  return (
    <Card style={styles.gap} testID="copy-blueprint">
      <View style={styles.rowBetween}>
        <AppText weight="semibold" numberOfLines={1} style={styles.flex}>
          {`🎬 ${bp.name}`}
        </AppText>
        <Button title="Replace video" small variant="secondary" onPress={onReplace} testID="copy-replace" />
      </View>
      <AppText size="xs" muted>
        Agent ne yeh dekha:
      </AppText>
      <View style={styles.wrap} testID="copy-summary">
        {bp.summary.map((line, i) => (
          <View key={`${i}-${line}`} style={styles.summaryChip}>
            <AppText size="xs">{line}</AppText>
          </View>
        ))}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={styles.strip} testID="copy-shots">
        {bp.shots.map((shot, i) => {
          const thumb = bp.thumbs[i];
          const badges = shotBadges(shot);
          return (
            <View key={`shot-${i}`} style={styles.shot} testID={`copy-shot-${i}`}>
              <View style={styles.shotImageBox}>
                {thumb ? (
                  <Image
                    source={{ uri: api.mediaUrl(thumb) }}
                    style={[styles.shotImage, shot.bw && styles.bwImage]}
                    resizeMode="cover"
                    accessibilityLabel={`Shot ${i + 1}`}
                  />
                ) : null}
                <View style={styles.badges}>
                  {badges.map((b) => (
                    <View key={b} style={styles.badge} testID={`copy-shot-${i}-badge-${b}`}>
                      <AppText size="xs" weight="bold" color={BADGE_COLOR[b]}>
                        {b}
                      </AppText>
                    </View>
                  ))}
                </View>
              </View>
              <AppText size="xs" weight="semibold" center>
                {`${shot.dur.toFixed(1)}s`}
              </AppText>
            </View>
          );
        })}
      </ScrollView>
      {bp.texts?.length ? (
        <View style={styles.gap} testID="copy-texts">
          <AppText size="xs" muted>
            Video me likha text:
          </AppText>
          {bp.texts.map((t, i) => (
            <View key={`${i}-${t.start}`} style={styles.rowGap} testID={`copy-text-${i}`}>
              <AppText size="xs" color={colors.textFaint} style={styles.time}>
                {`${clock(t.start)}–${clock(t.end)}`}
              </AppText>
              <AppText size="sm" style={styles.flex} numberOfLines={2}>
                {t.text}
              </AppText>
            </View>
          ))}
        </View>
      ) : null}
      <AppText size="sm" muted testID="copy-song">
        {bp.song ? `♫ Gaana: ${bp.song}` : '♫ Is video me gaana nahi mila'}
      </AppText>
    </Card>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  gap: { gap: spacing.sm },
  center: { alignItems: 'center' },
  row: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  rowGap: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  time: { width: 76 },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  saveRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  flex: { flex: 1, minWidth: 120 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  summaryChip: { borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 3, backgroundColor: colors.cardAlt, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  strip: { gap: spacing.sm, paddingVertical: 4 },
  shot: { width: 72, gap: 4 },
  shotImageBox: { width: 72, height: 96, borderRadius: radius.sm, overflow: 'hidden', backgroundColor: colors.cardAlt },
  shotImage: { width: '100%', height: '100%' },
  // web honours CSS filters; native shows the frame as is (the badge still says B&W)
  bwImage: { filter: 'grayscale(1)' } as object,
  badges: { position: 'absolute', left: 3, top: 3, gap: 2 },
  badge: { backgroundColor: 'rgba(0,0,0,0.7)', borderRadius: 4, paddingHorizontal: 4 },
  input: {
    minHeight: 46,
    backgroundColor: colors.cardAlt,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontSize: 15,
  },
});
