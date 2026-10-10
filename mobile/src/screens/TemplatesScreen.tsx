import { useEffect, useMemo, useState } from 'react';
import {
  Image,
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
  useWindowDimensions,
  type LayoutChangeEvent,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api, errorMessage } from '../api/client';
import type { Project, Template } from '../api/types';
import { AppText, Button, Chip, EmptyState, ErrorState, InlineError, LoadingState, Screen } from '../components';
import { useAsync } from '../hooks/useAsync';
import { openEditorWithJob, type EditorNavigation } from '../navigation/openEditor';
import { useSettings } from '../store/settings';
import { colors, radius, spacing } from '../theme';

/** Special filters next to the backend's categories. */
export const FILTER_ALL = 'All';
export const FILTER_MINE = 'Mine';

/** Templates shown for a filter chip. */
export function filterTemplates(templates: Template[], filter: string): Template[] {
  if (filter === FILTER_ALL) return templates;
  if (filter === FILTER_MINE) return templates.filter((t) => t.kind === 'mine');
  return templates.filter((t) => t.category === filter);
}

/** Grid columns for a container width: cards are at least ~170 px wide, 1–4 columns. */
export function gridColumns(width: number, minCard = 170, gap = spacing.md): number {
  if (!(width > 0)) return 2;
  return Math.max(1, Math.min(4, Math.floor((width + gap) / (minCard + gap))));
}

/** "15s · 9:16" */
export function templateMeta(t: Pick<Template, 'duration' | 'aspect'>): string {
  return [t.duration ? `${Math.round(t.duration)}s` : null, t.aspect || null].filter(Boolean).join(' · ');
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

interface Props {
  navigation: EditorNavigation & { setOptions?: (o: object) => void };
  route: { params?: { projectId?: string; projectName?: string } };
}

/**
 * Template gallery (bottom tab "Templates", and the editor's "Templates" button with the project preselected).
 * Tap a card → details → "Use this template" → pick a project (+ optional extra prompt) → the editor opens
 * with the live view of that edit.
 */
export function TemplatesScreen({ navigation, route }: Props) {
  const presetProject = route.params?.projectId;
  const { baseUrl } = useSettings();
  const gallery = useAsync(() => api.listTemplates(), baseUrl);
  const [filter, setFilter] = useState(FILTER_ALL);
  const [open, setOpen] = useState<Template | null>(null);
  const { width: windowWidth } = useWindowDimensions();
  const [width, setWidth] = useState(Math.min(windowWidth, 1200) - spacing.lg * 2);
  const cols = gridColumns(width);

  const templates = useMemo(() => gallery.data?.templates ?? [], [gallery.data]);
  const filters = useMemo(
    () => [FILTER_ALL, ...(gallery.data?.categories ?? []).filter((c) => c !== FILTER_ALL && c !== FILTER_MINE), FILTER_MINE],
    [gallery.data],
  );
  const shown = filterTemplates(templates, filter);

  const onLayout = (e: LayoutChangeEvent) => {
    const w = e.nativeEvent.layout.width;
    if (w > 0 && Math.abs(w - width) > 1) setWidth(w);
  };

  let body: React.ReactNode;
  if (gallery.loading && !gallery.data) {
    body = <LoadingState label="Templates aa rahe hain…" />;
  } else if (gallery.error && !gallery.data) {
    body = <ErrorState title="Could not load templates" message={gallery.error} onRetry={() => gallery.reload()} />;
  } else {
    const cardW = (width - spacing.md * (cols - 1)) / cols;
    body = (
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={gallery.refreshing} onRefresh={() => gallery.reload(true)} tintColor={colors.accent} />
        }
        testID="templates-screen"
      >
        {presetProject ? (
          <AppText size="sm" muted testID="templates-for-project">
            {`Template chuno — ${route.params?.projectName ?? 'is project'} pe lagega.`}
          </AppText>
        ) : (
          <AppText size="sm" muted>
            Pro edits, ek tap me. Template chuno, project chuno — agents baaki kar denge.
          </AppText>
        )}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filters}>
          {filters.map((f) => (
            <Chip key={f} label={f} selected={filter === f} onPress={() => setFilter(f)} testID={`template-filter-${slug(f)}`} />
          ))}
        </ScrollView>
        <View style={styles.grid} onLayout={onLayout} testID="templates-grid">
          {shown.length === 0 ? (
            <EmptyState
              title={filter === FILTER_MINE ? 'Abhi koi apna template nahi' : 'No templates here'}
              message={filter === FILTER_MINE ? 'Copy an Edit me "Save as my template" dabao — woh yahan aayega.' : undefined}
              icon="▤"
            />
          ) : (
            shown.map((t) => <TemplateCard key={t.id} template={t} width={cardW} onPress={() => setOpen(t)} />)
          )}
        </View>
      </ScrollView>
    );
  }

  return (
    <Screen style={styles.screen}>
      {gallery.error && gallery.data ? <InlineError message={gallery.error} /> : null}
      {body}
      <TemplateSheet
        key={open?.id ?? 'closed'} // fresh sheet state for every template opened
        template={open}
        presetProjectId={presetProject}
        onClose={() => setOpen(null)}
        onDeleted={(id) => {
          gallery.setData((prev) => (prev ? { ...prev, templates: prev.templates.filter((x) => x.id !== id) } : prev));
          setOpen(null);
        }}
        onApplied={(project, jobId, template) => {
          setOpen(null);
          openEditorWithJob(navigation, {
            projectId: project.id,
            projectName: project.name,
            jobId,
            jobLabel: `▤ Template: ${template.name}`,
          });
        }}
      />
    </Screen>
  );
}

function TemplateCard({ template: t, width, onPress }: { template: Template; width: number; onPress: () => void }) {
  const meta = templateMeta(t);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={t.name}
      testID={`template-card-${t.id}`}
      style={({ pressed }) => [styles.card, { width }, pressed && styles.pressed]}
    >
      <View style={[styles.preview, { backgroundColor: t.colors?.[0] ?? colors.cardAlt }]}>
        {t.preview_url ? (
          <Image source={{ uri: api.mediaUrl(t.preview_url) }} style={styles.previewImg} resizeMode="cover" accessibilityLabel={`${t.name} preview`} />
        ) : null}
        {t.kind === 'mine' ? (
          <View style={styles.mineBadge}>
            <AppText size="xs" weight="bold" color="#FFFFFF">
              Mine
            </AppText>
          </View>
        ) : null}
      </View>
      <View style={styles.cardBody}>
        <AppText weight="semibold" numberOfLines={1}>
          {t.name}
        </AppText>
        <AppText size="xs" muted numberOfLines={2}>
          {t.description}
        </AppText>
        <View style={styles.tags}>
          {t.tags.slice(0, 3).map((tag) => (
            <View key={tag} style={styles.tag}>
              <AppText size="xs" color={colors.textMuted}>
                {`#${tag}`}
              </AppText>
            </View>
          ))}
        </View>
        {meta ? (
          <AppText size="xs" color={colors.textFaint}>
            {`${t.category} · ${meta}`}
          </AppText>
        ) : null}
      </View>
    </Pressable>
  );
}

interface SheetProps {
  template: Template | null;
  presetProjectId?: string;
  onClose: () => void;
  onDeleted: (id: string) => void;
  onApplied: (project: Project, jobId: string, template: Template) => void;
}

/** Details of a template; "Use this template" → choose the project + optional prompt → apply. */
export function TemplateSheet({ template, presetProjectId, onClose, onDeleted, onApplied }: SheetProps) {
  const insets = useSafeAreaInsets();
  const [step, setStep] = useState<'details' | 'project'>('details');
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(presetProjectId ?? null);
  const [extra, setExtra] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (step !== 'project' || projects) return;
    let alive = true;
    api
      .listProjects()
      .then((list) => {
        if (!alive) return;
        setProjects(list);
        setProjectsError(null);
        setProjectId((cur) => cur ?? (list.length === 1 ? list[0].id : null));
      })
      .catch((e) => alive && setProjectsError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [step, projects]);

  if (!template) return null;
  const chosen = projects?.find((p) => p.id === projectId) ?? null;

  const apply = async () => {
    if (!projectId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const prompt = extra.trim();
      const res = await api.applyTemplate(projectId, template.id, prompt || undefined);
      const project = chosen ?? ({ id: projectId, name: '' } as Project);
      onApplied(project, res.job_id, template);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.deleteTemplate(template.id);
      onDeleted(template.id);
    } catch (e) {
      setError(`Delete nahi hua: ${errorMessage(e)}`);
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  };

  const meta = templateMeta(template);

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close template" />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]} testID="template-sheet">
          <View style={styles.handle} />
          <ScrollView contentContainerStyle={styles.sheetContent} keyboardShouldPersistTaps="handled">
            <View style={styles.rowBetween}>
              <AppText size="lg" weight="bold" numberOfLines={2} style={styles.flex}>
                {template.name}
              </AppText>
              <Button title="Close" small variant="ghost" onPress={onClose} testID="template-close" />
            </View>
            {step === 'details' ? (
              <>
                {template.preview_url ? (
                  <Image
                    source={{ uri: api.mediaUrl(template.preview_url) }}
                    style={[styles.sheetPreview, { backgroundColor: template.colors?.[0] ?? colors.cardAlt }]}
                    resizeMode="cover"
                  />
                ) : null}
                <AppText size="sm" testID="template-description">
                  {template.description}
                </AppText>
                <AppText size="xs" muted>
                  {[template.category, meta, template.kind === 'mine' ? 'Mine' : null].filter(Boolean).join(' · ')}
                </AppText>
                <View style={styles.tags}>
                  {template.tags.map((tag) => (
                    <View key={tag} style={styles.tag}>
                      <AppText size="xs" color={colors.textMuted}>{`#${tag}`}</AppText>
                    </View>
                  ))}
                </View>
                <Button title="Use this template" onPress={() => setStep('project')} testID="template-use" />
                {template.kind === 'mine' ? (
                  <Button
                    title={confirmDelete ? 'Pakka delete karein?' : 'Delete template'}
                    variant="danger"
                    onPress={() => void remove()}
                    loading={busy}
                    testID="template-delete"
                  />
                ) : null}
              </>
            ) : (
              <>
                <AppText weight="semibold">Kis project pe lagana hai?</AppText>
                {!projects && !projectsError ? <LoadingState label="Projects…" /> : null}
                {projectsError ? <InlineError message={projectsError} /> : null}
                {projects && projects.length === 0 ? (
                  <AppText size="sm" muted>
                    Pehle ek project banao aur clips daalo (Projects tab).
                  </AppText>
                ) : null}
                {projects?.map((p) => {
                  const selected = p.id === projectId;
                  const empty = p.clips.length === 0;
                  return (
                    <Pressable
                      key={p.id}
                      onPress={() => setProjectId(p.id)}
                      accessibilityRole="radio"
                      accessibilityState={{ selected, disabled: empty }}
                      disabled={empty}
                      testID={`template-project-${p.id}`}
                      style={[styles.projectRow, selected && styles.projectRowOn, empty && styles.off]}
                    >
                      <View style={[styles.radio, selected && styles.radioOn]} />
                      <View style={styles.flex}>
                        <AppText weight="medium" numberOfLines={1}>
                          {p.name}
                        </AppText>
                        <AppText size="xs" muted>
                          {empty ? 'no clips yet' : `${p.clips.length} clip${p.clips.length === 1 ? '' : 's'}`}
                        </AppText>
                      </View>
                    </Pressable>
                  );
                })}
                <TextInput
                  value={extra}
                  onChangeText={setExtra}
                  placeholder="Kuch aur? (optional) e.g. mera naam title me"
                  placeholderTextColor={colors.textFaint}
                  style={styles.input}
                  multiline
                  accessibilityLabel="Extra prompt"
                  testID="template-extra-prompt"
                />
                <Button
                  title={chosen ? `Apply on ${chosen.name}` : 'Apply template'}
                  onPress={() => void apply()}
                  disabled={!projectId}
                  loading={busy}
                  testID="template-apply"
                />
                <Button title="Back" variant="ghost" small onPress={() => setStep('details')} />
              </>
            )}
            {error ? <InlineError message={error} /> : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { maxWidth: 1200 },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  filters: { gap: spacing.sm, paddingVertical: 2 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  pressed: { opacity: 0.85 },
  preview: { width: '100%', aspectRatio: 16 / 10 },
  previewImg: { width: '100%', height: '100%' },
  mineBadge: { position: 'absolute', top: 6, right: 6, backgroundColor: colors.accent, borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 2 },
  cardBody: { padding: spacing.md, gap: 4 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 4 },
  tag: { backgroundColor: colors.cardAlt, borderRadius: radius.pill, paddingHorizontal: 7, paddingVertical: 1 },
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    maxHeight: '90%',
    width: '100%',
    maxWidth: 640,
    alignSelf: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  handle: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: spacing.sm },
  sheetContent: { gap: spacing.md, paddingBottom: spacing.lg },
  sheetPreview: { width: '100%', aspectRatio: 16 / 9, borderRadius: radius.md },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm },
  flex: { flex: 1 },
  projectRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  projectRowOn: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  radio: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: colors.textMuted },
  radioOn: { borderColor: colors.accent, backgroundColor: colors.accent },
  off: { opacity: 0.45 },
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
