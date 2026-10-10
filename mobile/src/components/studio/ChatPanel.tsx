import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { IntentChoice, Job, JobAgent, JobEvent, JobVariation, UnclearPart, Understood } from '../../api/types';
import { isTerminal } from '../../hooks/useJobPolling';
import { useJobEvents } from '../../hooks/useJobEvents';
import { useVoicePrompt } from '../../hooks/useVoicePrompt';
import { LiveActivity } from './LiveActivity';
import { formatDuration, formatPercent } from '../../utils/format';
import { buildLiveState, workingAgent } from '../../utils/liveTimeline';
import { ThoughtFeed } from './ThoughtFeed';
import { AppText } from '../AppText';
import { studio } from './theme';
import { IconButton } from './ui';

/** One-tap edits for people who don't know editing words. Prompts are worded for the planner. */
export const ONE_TAP = [
  { id: 'auto', label: '✨ Auto edit', prompt: 'mast sa edit kar do' },
  { id: 'arrange', label: '↕ Arrange clips', prompt: 'arrange the clips in the right order' },
  { id: 'captions', label: '㏄ Captions', prompt: 'add captions of what I say' },
] as const;

export interface ChatTurn {
  key: string;
  prompt: string;
  job: Job | null;
  /** What the prompt coach made of the user's words (null when the coach wasn't reachable). */
  understood?: Understood | null;
  /** Why each edit was made (from the finished plan). */
  decisions?: { decision: string; where: string; reason: string; skill: string }[];
  /** Events of the job when the screen already streams them (the turn then opens no stream of its own). */
  events?: JobEvent[];
  /** Sent, the agent has not answered yet (shown at once, before the server replies). */
  pending?: boolean;
  /** The agent's answer when no edit was started ("samajh nahi aaya…", a network error). */
  error?: string | null;
  /** An unclear request: up to 3 readings to tap (the first is the best guess). */
  choices?: IntentChoice[];
  /** The resolver applied its reading directly — what it did, in plain words (undo is one tap away). */
  did?: string;
}

export interface ChatPanelProps {
  turns: ChatTurn[];
  /** True while the latest job is still being polled. */
  running: boolean;
  pollError?: string | null;
  onSend: (prompt: string) => void;
  sending?: boolean;
  sendError?: string | null;
  disabled?: boolean;
  threeVariations: boolean;
  onToggleThree: () => void;
  onNewChat: () => void;
  onAttach: () => void;
  /** Variant currently playing in the preview (null = default). */
  playingVariant: number | null;
  onPlayVariant: (job: Job, index: number) => void;
  /** Called after POST /jobs/{id}/choose succeeded. */
  onChosen: (job: Job, index: number) => void;
  /** Controlled prompt text (optional; uncontrolled when omitted). */
  draft?: string;
  onDraftChange?: (text: string) => void;
  /** Increment to focus the prompt input (e.g. after a phrase was added from elsewhere). */
  focusRequest?: number;
  /** Rendered between the header and the transcript (e.g. the memory card). */
  topSlot?: ReactNode;
  /** The user tapped one reading of an unclear request. */
  onPickChoice?: (turnKey: string, choice: IntentChoice) => void;
}

export function ChatPanel(props: ChatPanelProps) {
  const { turns, running, pollError, onSend, sending, sendError, disabled, threeVariations, onToggleThree, onNewChat, onAttach } = props;
  const { draft, onDraftChange, focusRequest, topSlot } = props;
  const [innerText, setInnerText] = useState('');
  const text = draft ?? innerText;
  const setText = (t: string) => {
    if (onDraftChange) onDraftChange(t);
    if (draft === undefined) setInnerText(t);
  };
  const inputRef = useRef<TextInput>(null);
  const voice = useVoicePrompt((heard) => {
    setText(heard);
    inputRef.current?.focus();
  });
  const scrollRef = useRef<ScrollView>(null);
  const canSend = !disabled && !sending && text.trim().length > 0;

  useEffect(() => {
    if (!focusRequest) return;
    inputRef.current?.focus();
  }, [focusRequest]);

  // a new message, the agent's answer, a finished edit: always show the newest part of the chat
  const last = turns[turns.length - 1];
  const lastState = `${turns.length}|${last?.pending ? 1 : 0}|${last?.error ?? ''}|${last?.job?.status ?? ''}`;
  useEffect(() => {
    const id = setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
    return () => clearTimeout(id);
  }, [lastState]);

  const send = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText('');
  };

  return (
    <View style={styles.panel} testID="chat-panel">
      <View style={styles.header}>
        <Pressable style={styles.titleBtn} accessibilityRole="button" accessibilityLabel="Agent menu">
          <AppText size="md" weight="semibold">
            CutMind agent ▾
          </AppText>
        </Pressable>
        <IconButton glyph="✎" label="New chat" onPress={onNewChat} testID="new-chat" />
      </View>

      {topSlot}

      <ScrollView
        ref={scrollRef}
        style={styles.scroll}
        contentContainerStyle={styles.transcript}
        onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
        testID="chat-transcript"
      >
        {turns.length === 0 ? (
          <View style={styles.empty}>
            <AppText size="sm" color={studio.muted}>
              Describe the edit you want — e.g. “cinematic 15s cut with animated gradient frame”.
            </AppText>
          </View>
        ) : null}
        {turns.map((t) => (
          <TurnView key={t.key} turn={t} {...props} />
        ))}
      </ScrollView>

      <View style={styles.footer}>
        {running ? (
          <View style={styles.status} testID="chat-running">
            <ActivityIndicator size="small" color={studio.cyan} />
            <AppText size="xs" color={studio.muted}>
              This edit is still running…
            </AppText>
          </View>
        ) : null}
        {pollError ? (
          <AppText size="xs" color={studio.red}>
            {pollError}
          </AppText>
        ) : null}
        {sendError ? (
          <AppText size="xs" color={studio.red} testID="chat-send-error">
            {sendError}
          </AppText>
        ) : null}
        {voice.state !== 'idle' || voice.error ? (
          <AppText size="xs" color={voice.error ? studio.red : studio.cyan} testID="voice-status">
            {voice.error ??
              (voice.state === 'recording'
                ? '● Listening… speak in Hindi or English, tap the mic again to stop'
                : 'Understanding what you said…')}
          </AppText>
        ) : null}
        <View style={styles.chips}>
          <Pressable
            onPress={onToggleThree}
            accessibilityRole="switch"
            accessibilityState={{ checked: threeVariations }}
            testID="variations-toggle"
            style={[styles.chip, threeVariations && styles.chipOn]}
          >
            <AppText size="xs" weight="semibold" color={threeVariations ? studio.white : studio.muted}>
              {threeVariations ? '✓ ' : ''}3 variations
            </AppText>
          </Pressable>
          {ONE_TAP.map((q) => (
            <Pressable
              key={q.label}
              onPress={() => !disabled && !sending && onSend(q.prompt)}
              accessibilityRole="button"
              accessibilityLabel={q.label}
              testID={`one-tap-${q.id}`}
              style={styles.chip}
            >
              <AppText size="xs" weight="semibold" color={studio.muted}>
                {q.label}
              </AppText>
            </Pressable>
          ))}
        </View>
        <View style={styles.inputRow}>
          <IconButton glyph="+" label="Attach clips" onPress={onAttach} style={styles.roundGhost} testID="chat-attach" />
          <TextInput
            ref={inputRef}
            value={text}
            onChangeText={setText}
            placeholder="Ask CutMind…"
            placeholderTextColor={studio.muted}
            style={styles.input}
            onSubmitEditing={send}
            editable={!sending}
            testID="studio-prompt"
            multiline={false}
          />
          <IconButton
            glyph={voice.state === 'recording' ? '■' : '◉'}
            label={voice.state === 'recording' ? 'Stop recording' : 'Voice input'}
            onPress={voice.toggle}
            testID="chat-mic"
          />
          <Pressable
            onPress={send}
            disabled={!canSend}
            accessibilityRole="button"
            accessibilityLabel="Send"
            accessibilityState={{ disabled: !canSend }}
            testID="studio-send"
            style={[styles.send, !canSend && styles.sendOff]}
          >
            {sending ? (
              <ActivityIndicator size="small" color={studio.white} />
            ) : (
              <AppText size="md" weight="bold" color={studio.white}>
                ↑
              </AppText>
            )}
          </Pressable>
        </View>
      </View>
    </View>
  );
}

/** A failed review check, said simply (what could not be done and why). */
export function plainProblem(name: string, detail: string): string {
  const known: Record<string, string> = {
    captions_present: 'Captions nahi bane — awaaz se shabd nahi mile.',
    speech_detected: detail.includes('could not read')
      ? 'Captions nahi bane — log bol rahe hain, par awaaz se shabd saaf padh nahi paaya (bahut shor / Hindi ke liye model chhota hai).'
      : 'Captions nahi bane — is video me koi bolta nahi (captions bolne se bante hain).',
    music_present: 'Gaana nahi lag paaya.',
    duration: `Length thodi alag bani: ${detail}`,
    subject_tracked: 'Video me wo insaan saaf nahi mila, isliye focus / tracking nahi ho paaya.',
    silence_removed: 'Chup wale hisse poore nahi hate.',
  };
  return known[name] ?? `${name.replace(/_/g, ' ')}: ${detail}`;
}

function TurnView({ turn, playingVariant, onPlayVariant, onChosen, onSend, disabled, sending, onPickChoice }: { turn: ChatTurn } & ChatPanelProps) {
  const job = turn.job;
  const failedChecks = job?.review?.checks.filter((c) => !c.passed) ?? [];
  const passed = job?.review?.checks.filter((c) => c.passed).length ?? 0;
  const variations = job?.variations ?? [];
  const jobRunning = !!job && !isTerminal(job);
  const ownEvents = useJobEvents(job?.id ?? null, job?.events, jobRunning && !turn.events);
  const events = turn.events ?? ownEvents;
  const thoughts = useMemo(() => buildLiveState(job, events).thoughts, [job, events]);
  const u = turn.understood;
  const unclear = u?.unclear ?? [];
  const finished = !!job && isTerminal(job);
  // a finished edit shows the agent's answer; the step-by-step log folds away (tap to open)
  const [showSteps, setShowSteps] = useState(false);
  const stepsVisible = !finished || showSteps;
  return (
    <View style={styles.turn}>
      <View style={styles.userBubble}>
        <AppText size="sm">{turn.prompt || job?.prompt}</AppText>
      </View>

      {turn.error ? (
        <View style={[styles.agentBubble, styles.agentBubbleError]} testID="agent-error">
          <AppText size="sm" color={studio.text}>
            {turn.error}
          </AppText>
          {turn.choices?.length ? (
            <View style={styles.suggestRow} testID="agent-choices">
              {turn.choices.map((c, i) => (
                <Pressable
                  key={`ch-${c.id}`}
                  onPress={() => !disabled && !sending && onPickChoice?.(turn.key, c)}
                  style={[styles.suggestChip, i === 0 && styles.choiceBest]}
                  accessibilityRole="button"
                  accessibilityLabel={c.label}
                  testID={`agent-choice-${i}`}
                >
                  <AppText size="xs" weight={i === 0 ? 'semibold' : 'regular'} color={studio.text}>
                    {i === 0 ? '★ ' : ''}
                    {c.label}
                  </AppText>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}
      {turn.did ? (
        <View style={styles.agentBubble} testID="agent-did">
          <AppText size="sm" color={studio.text}>
            ✓ Kiya: {turn.did} — pasand na aaye to ↶ Undo
          </AppText>
        </View>
      ) : null}
      {turn.pending && !job && !turn.error ? (
        <View style={[styles.agentBubble, styles.row]} testID="agent-thinking">
          <ActivityIndicator size="small" color={studio.cyan} />
          <AppText size="sm" color={studio.muted}>
            Agent aapki baat samajh raha hai…
          </AppText>
        </View>
      ) : null}

      {u && (u.changed || unclear.length > 0) ? (
        <View style={styles.coach} testID="coach-card">
          {u.changed ? (
            <>
              <AppText size="sm" weight="semibold">
                Samajh gaya 👌 Main ye karunga:
              </AppText>
              {u.understood.slice(0, 10).map((x) => (
                <AppText key={x} size="xs" color={studio.text}>
                  • {x}
                </AppText>
              ))}
              <AppText size="xs" color={studio.muted} testID="coach-prompt">
                English prompt: {u.solid_prompt}
              </AppText>
              {u.pro_brief ? (
                <AppText size="xs" color={studio.text} testID="coach-brief">
                  Pro editor brief: {u.pro_brief}
                </AppText>
              ) : null}
            </>
          ) : null}
          {unclear.length > 0 ? (
            <View style={styles.spec} testID="coach-unclear">
              <AppText size="xs" weight="semibold" color={studio.text}>
                Ye samajh nahi aaya:
              </AppText>
              {unclear.map((part, i) => (
                <UnclearItem
                  key={`${part.text}-${i}`}
                  index={i}
                  part={part}
                  canApply={!disabled && !sending}
                  onApply={(command) => onSend(command)}
                />
              ))}
            </View>
          ) : null}
          {u.changed && u.spec ? (
            <View style={styles.spec} testID="coach-spec">
              {u.spec.genres.length || u.spec.platform ? (
                <AppText size="xs" color={studio.cyan}>
                  {[...u.spec.genres.map((g) => g.name), u.spec.platform?.name].filter(Boolean).join(' · ')}
                </AppText>
              ) : null}
              {u.spec.inferred.slice(0, 6).map((d) => (
                <AppText key={`${d.field}-${String(d.value)}`} size="xs" color={studio.text}>
                  ＋ {d.field.replace(/_/g, ' ')}: {String(d.value)} — {d.reason.split(':')[0]}
                </AppText>
              ))}
              {u.spec.inferred.length > 6 ? (
                <AppText size="xs" color={studio.muted}>…and {u.spec.inferred.length - 6} more pro choices</AppText>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}

      {finished ? (
        <Pressable onPress={() => setShowSteps((s) => !s)} accessibilityRole="button" testID="steps-toggle">
          <AppText size="xs" color={studio.cyan}>
            {showSteps ? '▾ Steps chhupao' : '▸ Agent ne kaise kiya (steps)'}
          </AppText>
        </Pressable>
      ) : null}
      {!stepsVisible ? null : events.length ? (
        <LiveActivity events={events} job={job} />
      ) : job ? (
        job.agents.map((a) => <AgentStep key={a.name} agent={a} />)
      ) : null}
      {job && !job.agents.length && !isTerminal(job) ? (
        <AppText size="sm" color={studio.muted}>
          {job.status === 'queued' ? `Queued${job.queue_position ? ` (${job.queue_position} ahead)` : ''}…` : job.stage}
        </AppText>
      ) : null}

      {job ? <ThoughtFeed thoughts={thoughts} running={jobRunning} worker={workingAgent(job, thoughts)} /> : null}

      {stepsVisible && failedChecks.map((c) => (
        <View key={c.name} style={styles.step}>
          <AppText size="sm" color={studio.red}>
            ✗
          </AppText>
          <View style={styles.stepText}>
            <AppText size="sm">{c.name} check failed</AppText>
            <AppText size="xs" color={studio.muted}>
              {c.detail}
            </AppText>
          </View>
        </View>
      ))}

      {stepsVisible && turn.decisions && turn.decisions.length ? (
        <View style={styles.spec} testID="decisions">
          <AppText size="xs" weight="semibold" color={studio.cyan}>
            Why these edits ({turn.decisions.length})
          </AppText>
          {turn.decisions.slice(0, 8).map((d, i) => (
            <AppText key={`${d.decision}-${i}`} size="xs" color={studio.text}>
              • {d.decision}{d.where && d.where !== 'whole edit' ? ` (${d.where})` : ''} — {d.reason}
            </AppText>
          ))}
        </View>
      ) : null}

      {job?.review ? (
        <AppText size="xs" color={studio.muted} testID="review-summary">
          Review: match {formatPercent(job.review.match_percent)} · {passed}/{job.review.checks.length} checks passed
        </AppText>
      ) : null}

      {job?.status === 'failed' ? (
        <AppText size="sm" color={studio.red}>
          Edit failed{job.error ? `: ${job.error}` : ''}
        </AppText>
      ) : null}

      {job && variations.length > 0 ? (
        <View style={styles.variations} testID="variations-list">
          <AppText size="sm">
            Created {variations.length} versions, ranked best first:
          </AppText>
          {variations.map((v, i) => (
            <VariationRow
              key={v.index}
              n={i + 1}
              v={v}
              playing={playingVariant === v.index}
              onPlay={() => onPlayVariant(job, v.index)}
              job={job}
              onChosen={onChosen}
            />
          ))}
        </View>
      ) : null}

      {job?.status === 'done' ? (
        <View style={styles.agentBubble} testID="agent-reply">
          <AppText size="sm" weight="semibold">
            {failedChecks.length ? '⚠ Edit bana, par sab nahi ho paaya' : '✅ Ho gaya'}
            {job.output ? ` · ${formatDuration(job.output.duration)}` : ''}
          </AppText>
          {job.explain?.summary && u?.understood?.length ? (
            <AppText size="sm" color={studio.muted} testID="agent-understood">
              Samjha: {u.understood.slice(0, 4).join(' · ')}
            </AppText>
          ) : null}
          {job.explain?.summary ? (
            <AppText size="sm" color={studio.text} testID="agent-explain">
              {job.explain.summary}
            </AppText>
          ) : null}
          {(job.explain?.warnings ?? []).map((w) => (
            <AppText key={`ew-${w}`} size="sm" color={studio.red} testID="agent-explain-warning">
              ⚠ {w}
            </AppText>
          ))}
          {(job.explain?.summary ? [] : u?.understood?.length ? u.understood : []).slice(0, 5).map((x) => (
            <AppText key={x} size="sm" color={studio.text}>
              • {x}
            </AppText>
          ))}
          {!job.explain?.summary && !u?.understood?.length && turn.decisions?.length
            ? turn.decisions
                // what was changed, in plain words — not the agents' internal bookkeeping
                .filter((d) => !['learning', 'song_driven'].includes(d.skill) && !d.decision.startsWith('learned'))
                .slice(0, 4)
                .map((d, i) => (
                <AppText key={`${d.decision}-${i}`} size="sm" color={studio.text}>
                  • {d.decision}
                </AppText>
              ))
            : null}
          {[...new Set(failedChecks.map((c) => plainProblem(c.name, c.detail)))].slice(0, 3).map((msg) => (
            <AppText key={`warn-${msg}`} size="sm" color={studio.red} testID="agent-warning">
              ⚠ {msg}
            </AppText>
          ))}
          {(job.explain?.suggestions ?? []).length ? (
            <View style={styles.suggestRow} testID="agent-suggestions">
              {(job.explain?.suggestions ?? []).map((sg) => (
                <Pressable
                  key={`sg-${sg}`}
                  onPress={() => !disabled && !sending && onSend(sg)}
                  style={styles.suggestChip}
                  accessibilityRole="button"
                  testID={`agent-suggestion-${sg}`}
                >
                  <AppText size="xs" color={studio.text}>
                    {sg}
                  </AppText>
                </Pressable>
              ))}
            </View>
          ) : null}
          <RateRow jobId={job.id} />
          <AppText size="xs" color={studio.muted}>
            Play dabao aur dekho. Kuch badalna ho to seedha likho — jaise “thoda slow karo”.
          </AppText>
        </View>
      ) : null}
    </View>
  );
}

/** 👍 / 👎 on an edit: it trains the taste (ratings reward the style knobs this edit used). */
function RateRow({ jobId }: { jobId: string }) {
  const [state, setState] = useState<'idle' | 'sending' | 'up' | 'down' | 'error'>('idle');
  const rate = async (rating: 'up' | 'down') => {
    setState('sending');
    try {
      await api.sendFeedback(jobId, { rating });
      setState(rating);
    } catch {
      setState('error');
    }
  };
  if (state === 'up' || state === 'down') {
    return (
      <AppText size="xs" color={studio.muted} testID="agent-rated">
        {state === 'up' ? '👍 Shukriya — aisa hi aage bhi.' : '👎 Noted — agli baar alag try karunga.'}
      </AppText>
    );
  }
  return (
    <View style={styles.suggestRow} testID="agent-rate">
      <Pressable onPress={() => rate('up')} disabled={state === 'sending'} style={styles.suggestChip} testID="agent-rate-up"
        accessibilityRole="button" accessibilityLabel="Accha laga">
        <AppText size="xs">👍</AppText>
      </Pressable>
      <Pressable onPress={() => rate('down')} disabled={state === 'sending'} style={styles.suggestChip}
        testID="agent-rate-down" accessibilityRole="button" accessibilityLabel="Accha nahi laga">
        <AppText size="xs">👎</AppText>
      </Pressable>
      {state === 'error' ? (
        <AppText size="xs" color={studio.red}>
          Rating nahi gayi — dobara dabao.
        </AppText>
      ) : null}
    </View>
  );
}

/** One part of the prompt the agent didn't get: tap a guess to teach it, or ignore it. */
function UnclearItem({
  index,
  part,
  canApply,
  onApply,
}: {
  index: number;
  part: UnclearPart;
  canApply: boolean;
  onApply: (command: string) => void;
}) {
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [learned, setLearned] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (hidden) return null;

  const teach = async (command: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.teachPhrase(part.text, command);
      setLearned(command);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.unclearItem}>
      <AppText size="xs" color={studio.text}>
        “{part.text}”
      </AppText>
      {learned ? (
        <View style={styles.chips}>
          <AppText size="xs" color={studio.green} testID={`unclear-learned-${index}`}>
            Seekh liya ✓ — agli baar samajh jaunga
          </AppText>
          <Pressable
            onPress={() => canApply && onApply(learned)}
            disabled={!canApply}
            accessibilityRole="button"
            accessibilityLabel="Ab ye bhi lagao"
            accessibilityState={{ disabled: !canApply }}
            testID={`unclear-apply-${index}`}
            style={({ pressed }) => [styles.applyBtn, (pressed || !canApply) && styles.pressed]}
          >
            <AppText size="xs" weight="semibold" color={studio.white}>
              Ab ye bhi lagao
            </AppText>
          </Pressable>
        </View>
      ) : (
        <View style={styles.chips}>
          {part.suggestions.map((s, j) => (
            <Pressable
              key={`${s.command}-${j}`}
              onPress={() => !busy && void teach(s.command)}
              disabled={busy}
              accessibilityRole="button"
              accessibilityLabel={s.label}
              testID={`unclear-chip-${index}-${j}`}
              style={({ pressed }) => [styles.chip, (pressed || busy) && styles.pressed]}
            >
              <AppText size="xs" weight="semibold" color={studio.text}>
                {s.label}
              </AppText>
            </Pressable>
          ))}
          <Pressable
            onPress={() => setHidden(true)}
            accessibilityRole="button"
            accessibilityLabel="Kuch aur / ignore"
            testID={`unclear-ignore-${index}`}
            style={styles.chip}
          >
            <AppText size="xs" color={studio.muted}>
              Kuch aur / ignore
            </AppText>
          </Pressable>
          {busy ? <ActivityIndicator size="small" color={studio.cyan} /> : null}
        </View>
      )}
      {error ? (
        <AppText size="xs" color={studio.red} testID={`unclear-error-${index}`}>
          {error}
        </AppText>
      ) : null}
    </View>
  );
}

function AgentStep({ agent }: { agent: JobAgent }) {
  const icon =
    agent.status === 'done' ? (
      <AppText size="sm" color={studio.green}>
        ✓
      </AppText>
    ) : agent.status === 'failed' ? (
      <AppText size="sm" color={studio.red}>
        ✗
      </AppText>
    ) : agent.status === 'pending' ? (
      <AppText size="sm" color={studio.faint}>
        ○
      </AppText>
    ) : (
      <ActivityIndicator size="small" color={studio.cyan} />
    );
  return (
    <View style={styles.step} testID={`step-${agent.name}`}>
      <View style={styles.stepIcon}>{icon}</View>
      <View style={styles.stepText}>
        <AppText size="sm" color={agent.status === 'pending' ? studio.muted : studio.text}>
          {agent.name}
          {agent.status === 'retrying' ? ` (retry ${agent.attempts})` : ''}
          {agent.status === 'failed' ? ' — failed' : ''}
        </AppText>
        {agent.message ? (
          <AppText size="xs" color={studio.muted}>
            {agent.message}
          </AppText>
        ) : null}
      </View>
    </View>
  );
}

function VariationRow({
  n,
  v,
  playing,
  onPlay,
  job,
  onChosen,
}: {
  n: number;
  v: JobVariation;
  playing: boolean;
  onPlay: () => void;
  job: Job;
  onChosen: (job: Job, index: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const choose = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.chooseVariant(job.id, v.index);
      onChosen(job, res?.chosen ?? v.index);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={[styles.variation, playing && styles.variationPlaying]} testID={`variation-${v.index}`}>
      <Pressable onPress={onPlay} accessibilityRole="button" accessibilityLabel={`Play ${v.name}`} style={styles.variationText} testID={`play-variant-${v.index}`}>
        <AppText size="sm">
          {n}.{' '}
          <AppText size="sm" weight="bold">
            {v.name}
          </AppText>
          : {v.description}
        </AppText>
        <AppText size="xs" color={studio.muted}>
          {playing ? '▶ playing · ' : ''}match {formatPercent(v.match_percent)} · {formatDuration(v.duration)}
        </AppText>
        {error ? (
          <AppText size="xs" color={studio.red}>
            {error}
          </AppText>
        ) : null}
      </Pressable>
      {v.chosen ? (
        <View style={styles.inUse}>
          <AppText size="xs" weight="semibold" color={studio.green}>
            In use
          </AppText>
        </View>
      ) : (
        <Pressable
          onPress={choose}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel={`Use ${v.name}`}
          testID={`use-variant-${v.index}`}
          style={({ pressed }) => [styles.useBtn, (pressed || busy) && styles.pressed]}
        >
          {busy ? <ActivityIndicator size="small" color={studio.white} /> : (
            <AppText size="xs" weight="semibold" color={studio.white}>
              Use this
            </AppText>
          )}
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  suggestRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6, alignItems: 'center' },
  choiceBest: { borderColor: studio.cyan, backgroundColor: 'rgba(34, 211, 238, 0.12)' },
  suggestChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: studio.border,
    backgroundColor: studio.panel,
  },
  panel: {
    width: 420,
    backgroundColor: studio.panel,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: studio.border,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  titleBtn: { paddingVertical: 4 },
  scroll: { flex: 1 },
  transcript: { paddingHorizontal: 16, paddingBottom: 16, gap: 18 },
  empty: { paddingVertical: 24 },
  turn: { gap: 10 },
  agentBubble: {
    alignSelf: 'flex-start',
    maxWidth: '92%',
    backgroundColor: studio.card,
    borderRadius: 14,
    borderTopLeftRadius: 4,
    paddingHorizontal: 12,
    paddingVertical: 9,
    gap: 4,
    borderWidth: 1,
    borderColor: studio.cyan,
  },
  agentBubbleError: { borderColor: studio.red },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  userBubble: {
    alignSelf: 'flex-end',
    maxWidth: '85%',
    backgroundColor: studio.card,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: studio.border,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  step: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  stepIcon: { width: 18, alignItems: 'center', paddingTop: 1 },
  stepText: { flex: 1, gap: 2 },
  variations: { gap: 8 },
  variation: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'center',
    padding: 8,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  variationPlaying: { borderColor: studio.blue, backgroundColor: studio.blueSoft },
  variationText: { flex: 1, gap: 2 },
  useBtn: { backgroundColor: studio.blue, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, minWidth: 70, alignItems: 'center' },
  inUse: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5, backgroundColor: 'rgba(34,197,94,0.14)' },
  pressed: { opacity: 0.7 },
  footer: { padding: 12, gap: 8, borderTopWidth: 1, borderTopColor: studio.border },
  status: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: studio.card,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  spec: { gap: 2, paddingTop: 4, borderTopWidth: 1, borderTopColor: 'rgba(124, 92, 255, 0.25)' },
  coach: { backgroundColor: 'rgba(124, 92, 255, 0.12)', borderRadius: 12, padding: 10, gap: 3, borderWidth: 1,
    borderColor: 'rgba(124, 92, 255, 0.35)' },
  chip: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: studio.border,
  },
  chipOn: { backgroundColor: studio.violet, borderColor: studio.violet },
  unclearItem: { gap: 4, paddingTop: 4 },
  applyBtn: { backgroundColor: studio.blue, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: studio.card,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: studio.border,
    paddingHorizontal: 6,
    height: 52,
  },
  roundGhost: { borderRadius: 999 },
  input: { flex: 1, color: studio.text, fontSize: 15, height: 40 },
  send: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: studio.blue,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendOff: { backgroundColor: studio.cardHover },
});
