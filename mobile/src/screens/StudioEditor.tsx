import { useVideoPlayer } from 'expo-video';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { api, errorMessage, isApiError } from '../api/client';
import type { AspectRatio, EditRequest, IntentChoice, Job, ManualOp, OutputFormat, StyleId, StyleInfo, Understood, Waveform } from '../api/types';
import { AppText } from '../components/AppText';
import { ChatPanel, type ChatTurn } from '../components/studio/ChatPanel';
import { EffectsPanel } from '../components/studio/EffectsPanel';
import { TemplatesPanel } from '../components/studio/TemplatesPanel';
import { TextPanel } from '../components/studio/TextPanel';
import { appendPhrase, prefixPhrase } from '../components/studio/fxPhrases';
import { IconRail, RAIL_ITEMS, type RailKey } from '../components/studio/IconRail';
import { LiveProgressCard } from '../components/studio/LiveProgressCard';
import { MediaPanel } from '../components/studio/MediaPanel';
import { MemoryCard } from '../components/studio/MemoryCard';
import { ComingSoonPanel, OverlaysPanel } from '../components/studio/OverlaysPanel';
import { PreviewStage } from '../components/studio/PreviewStage';
import { EDIT_LIKE_REFERENCE_PROMPT, ReferencePanel } from '../components/studio/ReferencePanel';
import { SoundsPanel } from '../components/studio/SoundsPanel';
import { commentTimeLabel, StudioTimeline, type TimelineComment } from '../components/studio/StudioTimeline';
import { StudioTopBar } from '../components/studio/StudioTopBar';
import { studio } from '../components/studio/theme';
import { useAsync } from '../hooks/useAsync';
import { useJobEvents } from '../hooks/useJobEvents';
import { isTerminal, useJobPolling } from '../hooks/useJobPolling';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import type { RootScreenProps } from '../navigation/types';
import { saveVideo, shareVideo } from '../utils/media';
import { buildLiveState } from '../utils/liveTimeline';
import { buildLiveStudioTimeline, buildStudioTimeline } from '../utils/studioTimeline';
import { loadPlanOrNull } from './EditorScreen';

type Props = RootScreenProps<'Editor'>;

interface Turn {
  key: string;
  prompt: string;
  jobId: string;
  /** Final job state, frozen once a newer turn starts. */
  snapshot: Job | null;
  understood?: Understood | null;
  /** Sent, waiting for the server (the message shows at once). */
  pending?: boolean;
  /** No edit was started: the agent's answer ("samajh nahi aaya…", network error). */
  error?: string | null;
  /** An unclear request: the readings to tap, and the id that remembers which one was tapped. */
  choices?: IntentChoice[];
  requestId?: string;
  /** Applied directly by the resolver: what it did. */
  did?: string;
  /** replace = other readings of the applied edit; add = parts that were not done. */
  choiceMode?: 'replace' | 'add';
  /** The answer to a message that was not an edit. */
  reply?: string;
}

const WAVEFORM_POINTS = 200;
/** Prompt of the Sounds panel's "Edit to this beat" button (sent with `music_track`). */
export const EDIT_TO_SONG_PROMPT = 'make an edit on my song with nice animations';

/** Desktop "studio" editor: icon rail + media panel, glowing preview, agent chat and a multi-track timeline. */
export function StudioEditor({ navigation, route }: Props) {
  const { projectId, projectName, jobId: routeJobId, jobLabel } = route.params;
  const project = useAsync(() => api.getProject(projectId), projectId);
  const plan = useAsync(() => loadPlanOrNull(projectId), projectId);
  const memory = useAsync(() => api.getProjectMemory(projectId), projectId);
  useRefreshOnFocus(navigation, () => {
    void project.reload(true);
    void plan.reload(true);
  });

  const [rail, setRail] = useState<RailKey>('media');
  const [aspect, setAspect] = useState<AspectRatio | null>(null);
  const [zoom, setZoom] = useState(1);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [cleared, setCleared] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  // off by default: one version renders ~3x faster; "3 versions" / "edit like a pro" in the prompt still asks for more
  const [threeVariations, setThreeVariations] = useState(false);
  const [playingVariant, setPlayingVariant] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [waveforms, setWaveforms] = useState<Record<string, Waveform>>({});
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [chosenOverride, setChosenOverride] = useState<Record<string, number>>({});
  const [draft, setDraft] = useState('');
  const [focusRequest, setFocusRequest] = useState(0);
  const [comments, setComments] = useState<TimelineComment[]>([]);

  const addPhrase = useCallback((phrase: string) => {
    setDraft((d) => appendPhrase(d, phrase));
    setFocusRequest((n) => n + 1);
  }, []);
  const prefixDraft = useCallback((prefix: string) => {
    setDraft((d) => prefixPhrase(d, prefix));
    setFocusRequest((n) => n + 1);
  }, []);

  // the newest turn that started a job (a message the agent did not understand starts none)
  const lastTurn = [...turns].reverse().find((t) => t.jobId);
  const activeJobId = lastTurn ? lastTurn.jobId : cleared ? null : (project.data?.last_job_id ?? null);

  const reloadProject = project.reload;
  const reloadPlan = plan.reload;
  const reloadMemory = memory.reload;
  const onFinished = useCallback(() => {
    void reloadProject(true);
    void reloadPlan(true);
    void reloadMemory(true);
  }, [reloadProject, reloadPlan, reloadMemory]);
  const poll = useJobPolling(activeJobId, onFinished);

  /** Apply a local "Use this" choice on top of the server copy until the next poll reflects it. */
  const withChoice = useCallback(
    (job: Job | null): Job | null => {
      if (!job || !(job.id in chosenOverride) || !job.variations?.length) return job;
      const chosen = chosenOverride[job.id];
      return { ...job, variations: job.variations.map((v) => ({ ...v, chosen: v.index === chosen })) };
    },
    [chosenOverride],
  );
  const activeJob = withChoice(poll.job);
  const running = !!activeJobId && poll.polling && !isTerminal(poll.job);

  // Live edit: one event stream for the running job feeds the bottom timeline, the centre card and the chat.
  const liveEvents = useJobEvents(activeJobId, activeJob?.events, running);
  const liveState = useMemo(
    () => (running ? buildLiveState(activeJob, liveEvents) : null),
    [running, activeJob, liveEvents],
  );

  const chatTurns: ChatTurn[] = useMemo(() => {
    if (!turns.length) {
      return activeJob && !cleared
        ? [{ key: `initial-${activeJob.id}`, prompt: activeJob.prompt, job: activeJob, events: liveEvents }]
        : [];
    }
    return turns.map((t) => {
      const isActive = !!t.jobId && !!activeJob && t.jobId === activeJob.id;
      return {
        key: t.key,
        prompt: t.prompt,
        job: !t.jobId ? null : isActive ? activeJob : withChoice(t.snapshot),
        understood: t.understood,
        decisions: isActive && activeJob?.status === 'done' ? plan.data?.decisions : undefined,
        events: isActive ? liveEvents : undefined,
        pending: t.pending,
        error: t.error,
        choices: t.choices,
        did: t.did,
        choiceMode: t.choiceMode,
        reply: t.reply,
      };
    });
  }, [turns, activeJob, cleared, withChoice, plan.data?.decisions, liveEvents]);

  const clips = useMemo(() => project.data?.clips ?? [], [project.data?.clips]);
  // while the agents edit, the timeline shows the edit being built (live tracks); afterwards the finished plan
  const model = useMemo(
    () =>
      liveState ? buildLiveStudioTimeline(liveState, clips, activeJob) : buildStudioTimeline(plan.data, clips),
    [liveState, plan.data, clips, activeJob],
  );
  const effectiveAspect: AspectRatio = aspect ?? plan.data?.canvas?.aspect_ratio ?? '16:9';

  // Waveforms for every clip on the main track (failures just leave the flat line).
  const clipIds = useMemo(() => Array.from(new Set(model.segments.map((s) => s.clipId))).sort().join(','), [model.segments]);
  useEffect(() => {
    if (!clipIds) return;
    let alive = true;
    for (const cid of clipIds.split(',')) {
      api
        .getWaveform(projectId, cid, WAVEFORM_POINTS)
        .then((w) => {
          if (alive && w && Array.isArray(w.peaks)) setWaveforms((prev) => ({ ...prev, [cid]: w }));
        })
        .catch(() => undefined);
    }
    return () => {
      alive = false;
    };
  }, [clipIds, projectId]);

  const version = project.data?.output_job_id ?? project.data?.last_job_id ?? null;
  const hasOutput = !!project.data?.has_output || activeJob?.status === 'done';
  // Only a finished job's id: a running job's URL used to get the OLD video, which the browser then mixed with the
  // new one once it was ready (the video stopped halfway after every effect).
  const shownVersion = activeJob?.status === 'done' ? activeJob.id : version;
  const outputUrl = hasOutput ? api.outputUrl(projectId, shownVersion, 'mp4', playingVariant) : null;
  const player = useVideoPlayer(outputUrl, (p) => {
    p.loop = true;
  });

  // The play button follows the REAL player: a new version (new source) loads paused, and the browser may pause
  // on its own. Before, `playing` stayed true while the player had stopped — the timecode froze at 00:02 with ⏸ shown.
  useEffect(() => {
    setPlaying(false);
  }, [outputUrl]);
  useEffect(() => {
    const sub = player?.addListener?.('playingChange', ({ isPlaying }: { isPlaying: boolean }) => setPlaying(isPlaying));
    return () => sub?.remove();
  }, [player]);

  // Track playback time for the playhead / timecode.
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const t = Number(player?.currentTime ?? 0);
      if (Number.isFinite(t)) setCurrentTime(t);
    }, 200);
    return () => clearInterval(id);
  }, [playing, player]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  const togglePlay = () => {
    try {
      if (playing) player.pause();
      else player.play();
    } catch {
      // Player not ready.
    }
    setPlaying((p) => !p);
  };

  const seek = (t: number) => {
    setCurrentTime(t);
    if (!hasOutput) return;
    try {
      player.seekBy(t - player.currentTime);
    } catch {
      // Player not ready yet; ignore.
    }
  };

  /**
   * Send an edit. `shown` is the chat text when it differs from the prompt (a timeline comment shows as
   * "📍 12.4s: WOW likh do" but sends just "WOW likh do" + `at`). Resolves true when a job started.
   */
  const startEdit = async (prompt: string, extra: Partial<EditRequest> = {}, shown?: string): Promise<boolean> => {
    setSending(true);
    setSendError(null);
    // the user's message shows in the chat at once; the agent's answer fills in when the server replies
    const pendingKey = `pending-${Date.now()}`;
    const frozenNow = poll.job;
    setTurns((prev) => {
      const base: Turn[] =
        prev.length === 0 && frozenNow && !cleared
          ? [{ key: `initial-${frozenNow.id}`, prompt: frozenNow.prompt, jobId: frozenNow.id, snapshot: frozenNow }]
          : prev.map((t) => (t.jobId && t.jobId === frozenNow?.id ? { ...t, snapshot: frozenNow } : t));
      return [...base, { key: pendingKey, prompt: shown ?? prompt, jobId: '', snapshot: null, pending: true }];
    });
    try {
      // prompt coach: desi / rough wording → the clean English prompt the agents follow (shown in the chat);
      // a timeline comment is about one moment, so the whole-video coach reading is skipped
      const understood =
        extra.style || extra.at !== undefined ? null : await api.understand(prompt, projectId).catch(() => null);
      // the agents get the user's own words (same meaning to the parser, plus the style / genre the clean
      // version leaves out); the clean English prompt is shown as "Samajh gaya"
      const sent = prompt;
      const body: EditRequest = { prompt: sent, ...(threeVariations ? { variations: 3 } : {}), ...extra };
      // "yaha …" in the chat points at the player's position (the backend uses it only when the words say "here")
      if (extra.at === undefined && currentTime > 0) body.playhead = Math.round(currentTime * 100) / 100;
      if (aspect) body.aspect_ratio = aspect;
      const res = await api.startEdit(projectId, body);
      // "3 variations" is for THIS message only: left on, every later chat message rendered 3 looks again
      if (body.variations === 3) setThreeVariations(false);
      // act / partial: the edit runs, and the other readings (or the parts not done) wait as one-tap chips
      const alts = res.alternatives?.length ? res.alternatives : undefined;
      const adds = res.unclear?.flatMap((u) => u.choices.slice(0, 2)) ?? [];
      const chipsExtra = alts
        ? { choices: alts, choiceMode: 'replace' as const }
        : adds.length
          ? { choices: adds, choiceMode: 'add' as const }
          : {};
      setTurns((prev) =>
        prev.map((t) =>
          t.key === pendingKey
            ? { ...t, jobId: res.job_id, pending: false, understood, ...(res.did ? { did: res.did } : {}), ...chipsExtra,
                ...(res.request_id ? { requestId: res.request_id } : {}) }
            : t,
        ),
      );
      setPlayingVariant(null);
      return true;
    } catch (e) {
      // e.g. "Ye samajh nahi aaya … Aise likho: …" — the agent's answer, in the chat where the user looks;
      // an unclear request comes with readings to tap (never a dead end)
      const msg = errorMessage(e);
      const choices =
        isApiError(e) && e.code === 'choose' && Array.isArray(e.details.choices) ? (e.details.choices as IntentChoice[]) : undefined;
      const requestId = isApiError(e) && typeof e.details.request_id === 'string' ? e.details.request_id : undefined;
      // a greeting / a question about the app: an answer, not an error
      const answer = isApiError(e) && e.code === 'non_edit';
      setTurns((prev) =>
        prev.map((t) =>
          t.key === pendingKey
            ? answer
              ? { ...t, pending: false, reply: msg }
              : { ...t, pending: false, error: msg, choices, requestId }
            : t,
        ),
      );
      return false;
    } finally {
      setSending(false);
    }
  };

  /** One reading of an unclear request was tapped: run it as tool calls (a new version) and remember the pick. */
  const pickChoice = async (turnKey: string, choice: IntentChoice) => {
    const asked = turns.find((t) => t.key === turnKey);
    setSending(true);
    setSendError(null);
    try {
      // another reading of an edit that was already applied: take that edit back first, then apply this one
      if (asked?.did && asked.choiceMode === 'replace') await api.undo(projectId);
      const res = await api.runTools(projectId, choice.calls, asked?.prompt ?? choice.label);
      if (asked?.requestId) void api.pickChoice(asked.requestId, choice.id).catch(() => undefined);
      const frozen = poll.job;
      setTurns((prev) => {
        const base = prev.map((t) =>
          t.key === turnKey ? { ...t, choices: undefined } : t.jobId && t.jobId === frozen?.id ? { ...t, snapshot: frozen } : t,
        );
        return [...base, { key: `${res.job_id}-${base.length}`, prompt: `👉 ${choice.label}`, jobId: res.job_id, snapshot: null, understood: null }];
      });
      setPlayingVariant(null);
    } catch (e) {
      setSendError(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  /** Timeline comment: an edit for one moment of the current output; pinned on the ruler once accepted. */
  const comment = async (text: string, at: number) => {
    const sec = Math.round(at * 100) / 100;
    const ok = await startEdit(text, { at: sec }, `📍 ${commentTimeLabel(sec)}: ${text}`);
    if (ok) setComments((prev) => [...prev, { key: `c${prev.length}-${sec}`, at: sec, text }]);
  };

  /** Undo / redo: the backend makes the old version current again (no render) — shown as its own chat turn. */
  const versionStep = async (kind: 'undo' | 'redo') => {
    setSending(true);
    try {
      const res = kind === 'undo' ? await api.undo(projectId) : await api.redo(projectId);
      const frozen = poll.job;
      setTurns((prev) => {
        const base = prev.map((t) => (t.jobId && t.jobId === frozen?.id ? { ...t, snapshot: frozen } : t));
        return [...base, { key: `${res.job_id}-${base.length}`, prompt: kind === 'undo' ? '↶ Undo' : '↷ Redo', jobId: res.job_id, snapshot: null, understood: null }];
      });
      setPlayingVariant(null);
    } catch (e) {
      setToast(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  /** Hand-made change: applied directly by the backend (no AI), shown as its own turn with live progress. */
  const manual = async (ops: ManualOp[], label: string) => {
    setSending(true);
    setSendError(null);
    try {
      const res = await api.manualEdit(projectId, ops);
      const frozen = poll.job;
      setTurns((prev) => {
        const base = prev.map((t, i) => (i === prev.length - 1 && t.jobId === frozen?.id ? { ...t, snapshot: frozen } : t));
        return [...base, { key: `${res.job_id}-${base.length}`, prompt: `⚡ ${label}`, jobId: res.job_id, snapshot: null, understood: null }];
      });
      setPlayingVariant(null);
    } catch (e) {
      setSendError(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  // A job started elsewhere (Copy an Edit / Templates) arrives as the `jobId` route param: it becomes the
  // newest chat turn, so the live view and the chat follow it like any edit started here.
  const pollJob = poll.job;
  const [seenRouteJob, setSeenRouteJob] = useState<string | undefined>(undefined);
  if (routeJobId && routeJobId !== seenRouteJob) {
    setSeenRouteJob(routeJobId);
    setTurns((prev) => {
      if (prev.some((t) => t.jobId === routeJobId)) return prev;
      const base = prev.map((t, i) => (i === prev.length - 1 && t.jobId === pollJob?.id ? { ...t, snapshot: pollJob } : t));
      return [...base, { key: `${routeJobId}-${base.length}`, prompt: jobLabel ?? 'Edit', jobId: routeJobId, snapshot: null, understood: null }];
    });
    setCleared(false);
    setPlayingVariant(null);
  }

  const applyStyle = (s: StyleInfo) => {
    void startEdit(`Restyle this edit with the ${s.name} look`, { style: s.id as StyleId, variations: 1 });
  };

  const fileBase = (project.data?.name ?? 'cutmind').replace(/[^\w-]+/g, '_');
  const share = async () => {
    if (!outputUrl) return;
    try {
      const res = await shareVideo(outputUrl, `${fileBase}.mp4`);
      setToast(res.message);
    } catch (e) {
      setToast(errorMessage(e));
    }
  };
  const doExport = async (format: OutputFormat) => {
    try {
      const url = api.outputUrl(projectId, shownVersion, format, playingVariant);
      const res = await saveVideo(url, `${fileBase}.${format}`);
      setToast(res.message);
    } catch (e) {
      setToast(errorMessage(e));
    }
  };

  const goImport = () => navigation.navigate('Import', { projectId, projectName: project.data?.name });

  if (project.loading && !project.data) {
    return (
      <View style={[styles.root, styles.center]} testID="studio-loading">
        <ActivityIndicator color={studio.blue} />
        <AppText color={studio.muted}>Opening studio…</AppText>
      </View>
    );
  }
  if (project.error && !project.data) {
    return (
      <View style={[styles.root, styles.center]}>
        <AppText weight="semibold">Could not open project</AppText>
        <AppText size="sm" color={studio.muted}>
          {project.error}
        </AppText>
        <AppText size="sm" color={studio.blue} onPress={() => project.reload()}>
          Retry
        </AppText>
      </View>
    );
  }

  const overlays = plan.data?.overlays ?? [];
  const variantName =
    playingVariant !== null ? activeJob?.variations?.find((v) => v.index === playingVariant)?.name : undefined;
  const title = project.data?.name ?? projectName ?? 'Untitled';

  return (
    <View style={styles.root} testID="studio-editor">
      <StudioTopBar
        title={title}
        aspect={effectiveAspect}
        onAspect={setAspect}
        zoom={zoom}
        onZoom={setZoom}
        hasOutput={hasOutput}
        extras={activeJob?.output?.extras}
        onShare={share}
        onExport={doExport}
        onHome={() => navigation.navigate('Tabs')}
        onUndo={running || sending || !hasOutput ? undefined : () => void versionStep('undo')}
        onRedo={running || sending || !hasOutput ? undefined : () => void versionStep('redo')}
        onCopyEdit={() => navigation.navigate('CopyEdit', { projectId, projectName: title })}
        onTemplates={() => navigation.navigate('TemplatesGallery', { projectId, projectName: title })}
        onHistory={() => setToast(`${chatTurns.length} edit(s) in this session`)}
      />
      <View style={styles.body}>
        <View style={styles.workArea}>
          <View style={styles.upper}>
            <IconRail active={rail} onSelect={setRail} />
            {rail === 'media' ? (
              <MediaPanel
                projectId={projectId}
                clips={clips}
                overlays={overlays}
                onAdd={goImport}
                onSeeAllOverlays={() => setRail('overlays')}
              />
            ) : rail === 'effects' ? (
              <EffectsPanel onAddPhrase={addPhrase} onApply={manual} />
            ) : rail === 'text' || rail === 'captions' ? (
              <TextPanel key={rail} mode={rail} onApply={manual} busy={sending} texts={plan.data?.text} />
            ) : rail === 'sounds' ? (
              <SoundsPanel
                projectId={projectId}
                audio={plan.data?.audio ?? null}
                hasPlan={!!plan.data}
                onApply={manual}
                onEditToSong={(name) => void startEdit(EDIT_TO_SONG_PROMPT, { music_track: name })}
                busy={sending}
              />
            ) : rail === 'more' ? (
              <View style={styles.railColumn}>
                <ReferencePanel
                  projectId={projectId}
                  onEditLikeReference={() => void startEdit(EDIT_LIKE_REFERENCE_PROMPT)}
                  busy={sending}
                />
                <TemplatesPanel onSend={(p) => void startEdit(p)} busy={sending} style={styles.fill} />
              </View>
            ) : rail === 'overlays' ? (
              <OverlaysPanel
                overlays={overlays}
                activeStyle={plan.data?.style ?? null}
                onApplyStyle={applyStyle}
                onRemoveStyle={() => void manual([{ op: 'set_style', style: null }], 'Look hataya (gradient tracks)')}
                busy={sending}
              />
            ) : (
              <ComingSoonPanel title={RAIL_ITEMS.find((r) => r.key === rail)?.label ?? ''} />
            )}
            <PreviewStage
              player={player}
              hasOutput={hasOutput}
              aspect={effectiveAspect}
              zoom={zoom}
              label={variantName ? `Previewing: ${variantName}` : undefined}
              overlay={
                running ? (
                  <LiveProgressCard job={activeJob} look={model.live?.color ?? null} pollError={poll.error} />
                ) : undefined
              }
            />
          </View>
          <StudioTimeline
            projectId={projectId}
            model={model}
            currentTime={currentTime}
            duration={activeJob?.output?.duration ?? model.total}
            playing={playing}
            onTogglePlay={togglePlay}
            onSeek={seek}
            waveforms={waveforms}
            onComment={hasOutput && clips.length > 0 ? (text, at) => void comment(text, at) : undefined}
            comments={comments}
          />
        </View>
        <ChatPanel
          turns={chatTurns}
          running={running}
          pollError={poll.error}
          onSend={(p) => void startEdit(p)}
          onPickChoice={(key, c) => void pickChoice(key, c)}
          sending={sending}
          sendError={sendError}
          disabled={clips.length === 0}
          threeVariations={threeVariations}
          onToggleThree={() => setThreeVariations((v) => !v)}
          onNewChat={() => {
            setTurns([]);
            setCleared(true);
            setSendError(null);
          }}
          onAttach={goImport}
          draft={draft}
          onDraftChange={setDraft}
          focusRequest={focusRequest}
          topSlot={
            <MemoryCard
              initiallyCollapsed
              memory={memory.data}
              loading={memory.loading}
              error={memory.error}
              onRetry={() => void memory.reload()}
              onQuickPhrase={prefixDraft}
            />
          }
          playingVariant={playingVariant}
          onPlayVariant={(_job, index) => {
            setPlayingVariant(index);
            setPlaying(false);
            setCurrentTime(0);
          }}
          onChosen={(job, index) => {
            setChosenOverride((m) => ({ ...m, [job.id]: index }));
            setPlayingVariant(index);
            setToast('Ye look ab current edit hai — timeline aur agla edit isi se chalega.');
            void reloadProject(true);
            void reloadPlan(true);
            void reloadMemory(true);
          }}
        />
      </View>
      {toast ? (
        <View style={styles.toast} testID="studio-toast">
          <AppText size="sm">{toast}</AppText>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: studio.bg },
  center: { alignItems: 'center', justifyContent: 'center', gap: 8 },
  body: { flex: 1, flexDirection: 'row', gap: 12, paddingHorizontal: 12, paddingBottom: 12, minHeight: 0 },
  workArea: { flex: 1, gap: 12, minWidth: 0, minHeight: 0 },
  upper: { flex: 1, flexDirection: 'row', gap: 12, minHeight: 0 },
  railColumn: { width: 340, gap: 12, minHeight: 0 },
  fill: { flex: 1, minHeight: 0 },
  toast: {
    position: 'absolute',
    bottom: 24,
    alignSelf: 'center',
    backgroundColor: studio.card,
    borderColor: studio.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
});
