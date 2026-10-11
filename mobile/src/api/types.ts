// Types mirror the REST contract in ../../ARCHITECTURE.md ("REST API").

export type AspectRatio = '9:16' | '1:1' | '16:9';
export type Resolution = 360 | 480 | 720 | 1080;

/** In-process Hugging Face planner model. */
export interface LlmHealth {
  model: string | null;
  file?: string;
  /** null in mock mode (rules only), false while the model is downloading / not cached. */
  available: boolean | null;
}

export interface Health {
  status: string;
  version: string;
  planner_mode: 'mock' | 'local' | (string & {});
  ffmpeg: boolean;
  whisper: boolean;
  /** True when the backend sets CUTMIND_API_KEY and requests need `X-API-Key`. */
  auth_required: boolean;
  llm: LlmHealth;
}

export interface Clip {
  id: string;
  filename: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  has_audio: boolean;
  size_bytes: number;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  clips: Clip[];
  last_job_id: string | null;
  /** The last FINISHED job (the version the player shows); last_job_id may still be running or failed. */
  output_job_id?: string | null;
  has_output: boolean;
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed';
export type AgentRunStatus = 'pending' | 'running' | 'done' | 'retrying' | 'failed';
export type LogLevel = 'info' | 'warn' | 'error';

export interface JobAgent {
  name: string;
  status: AgentRunStatus;
  progress: number;
  score: number | null;
  attempts: number;
  message: string;
}

export interface JobLog {
  t: string;
  agent: string;
  level: LogLevel;
  msg: string;
}

export interface ReviewCheck {
  name: string;
  owner: string;
  passed: boolean;
  detail: string;
  points: number;
}

export interface Review {
  checks: ReviewCheck[];
  agent_scores: Record<string, number>;
  match_percent: number;
}

export interface JobOutput {
  duration: number;
  width: number;
  height: number;
  has_audio: boolean;
  size_bytes: number;
  /** Extra files rendered alongside the mp4 (only when the prompt asked for them). */
  extras?: OutputExtra[];
}

/** Extra download formats of `GET /projects/{id}/output?format=...`. */
export type OutputExtra = 'gif' | 'mp3';
export type OutputFormat = 'mp4' | OutputExtra;

/** What an edit changed compared with the version before it (plain words). */
export interface JobExplain {
  summary: string;
  changed?: string[];
  kept?: string[];
  duration_before?: number | null;
  duration_after?: number | null;
  warnings?: string[];
  /** 2-3 next tweaks a pro would offer (tap = send as the next message). */
  suggestions?: string[];
}

export interface VersionInfo {
  n: number;
  job_id: string;
  prompt: string;
  created_at: string;
  duration: number | null;
  match_percent: number | null;
  kind: 'ai' | 'manual' | 'restore';
  current?: boolean;
}

export interface Job {
  id: string;
  /** Explain-back after the edit finished. */
  explain?: JobExplain | null;
  project_id: string;
  prompt: string;
  status: JobStatus;
  progress: number;
  stage: string;
  error: string | null;
  match_percent: number | null;
  created_at: string;
  /** When the worker picked the job up (null while queued). */
  started_at?: string | null;
  finished_at: string | null;
  /** Number of edits ahead of this one in the (single-worker) queue. */
  queue_position?: number;
  agents: JobAgent[];
  logs: JobLog[];
  review: Review | null;
  output: JobOutput | null;
  /** Alternative renders, ranked best first (empty array / absent when only one version was made). */
  variations?: JobVariation[];
  /** Every real step of the job, in order (also streamed live from GET /jobs/{id}/events). */
  events?: JobEvent[];
  /** Latest state of every live timeline track (see LIVE_COPY_TEMPLATES_API.md). */
  timeline?: LiveTimeline;
  /** The agents' plain-words decisions, oldest first (last 200). */
  thoughts?: JobThought[];
  /** Latest render step while the video is rendered (also streamed as `render_step` events). */
  render_step?: RenderStep | null;
}

/** Kind of a `render_step` event ("start" = any other render message, e.g. "rendering 9 segments"). */
export type RenderStepKind = 'start' | 'segment' | 'join' | 'finish' | 'reuse' | 'done';

/**
 * One render step (`render_step` event / `job.render_step`, see LIVE_COPY_TEMPLATES_API.md "Render steps").
 * Segments render in parallel, so for `segment` `done` counts finished shots (not their index).
 */
export interface RenderStep {
  step: RenderStepKind | (string & {});
  done: number | null;
  total: number | null;
  text: string;
  /** Review round (0 = first render, 1+ = re-render after a retry); events only. */
  round?: number;
}

// ---- Live editing view (`thought` / `timeline` events, job snapshot `timeline` / `thoughts`) ----

export type LiveTrack = 'video' | 'text' | 'fx' | 'music' | 'color';

/** One shot on the output timeline (all times in seconds on the OUTPUT timeline). */
export interface LiveVideoItem {
  clip_id: string;
  filename: string;
  start: number;
  dur: number;
  in?: number;
  out?: number;
  speed?: number;
  /** Server path of a small frame (`/projects/{pid}/clips/{cid}/frame?t=..`); prefix with the API base URL. */
  thumb?: string | null;
}

export interface LiveTextItem {
  start: number;
  dur: number;
  text: string;
  kind: 'title' | 'caption' | 'word' | (string & {});
}

export interface LiveFxItem {
  start: number;
  dur: number;
  type: string;
}

export interface LiveMusicItem {
  start: number;
  dur: number;
  name: string;
}

export interface LiveColorItem {
  preset: string | null;
  lut: string | null;
  /** Name of the styled version being rendered ("Violet Authority"), when the job renders variations. */
  name?: string | null;
}

export interface LiveTimeline {
  video?: LiveVideoItem[];
  text?: LiveTextItem[];
  fx?: LiveFxItem[];
  music?: LiveMusicItem[];
  color?: LiveColorItem[];
}

/** One plain-words decision of an agent ("Picked 9 shots of ~4 s from 3 clips"). */
export interface JobThought {
  t: number;
  agent: string;
  text: string;
}

/** One live event (Server-Sent Events from GET /jobs/{id}/events). */
export interface JobEvent {
  seq: number;
  /** seconds since the job started */
  t: number;
  type: string;
  node?: string;
  ms?: number;
  agent?: string;
  status?: string;
  message?: string;
  score?: number | null;
  stage?: string;
  progress?: number;
  level?: string;
  msg?: string;
  error?: string;
  match_percent?: number;
  agents?: { id: string; name: string; category: string }[];
  [key: string]: unknown;
}

/** POST /understand: the prompt coach's clean English version of what the user said. */
export interface Understood {
  solid_prompt: string;
  /** The whole edit as a professional brief: what you said + what the editorial brain decided. */
  pro_brief?: string;
  understood: string[];
  changed: boolean;
  auto: boolean;
  spec?: EditSpecInfo | null;
  /** Parts of the prompt the agent did not understand, each with up to 3 guesses. */
  unclear?: UnclearPart[];
}

/** One guess for an unclear part of a prompt: `command` is an English sentence the agent understands. */
export interface Suggestion {
  command: string;
  label: string;
  score: number;
}

/** A part of the prompt the agent did not understand (POST /understand `unclear`). */
export interface UnclearPart {
  text: string;
  suggestions: Suggestion[];
}

/** POST /phrasebook: the agent learned that `phrase` means `command`. */
export interface TeachPhraseResponse {
  ok: boolean;
  phrase: string;
  command: string;
}

/** GET /phrasebook: taught phrases, recent misses and the commands that can be taught. */
export interface PhraseBookResponse {
  taught: Record<string, string>;
  misses: { phrase: string; count: number; last_at: string }[];
  commands: Record<string, string>;
}

/** Built-in visual styles (`GET /styles`, `style` of POST /projects/{id}/edit). */
export type StyleId = 'midnight_drift' | 'violet_authority' | 'cyan_kinetic';

/** One alternative render of a multi-version edit. */
export interface JobVariation {
  index: number;
  style: StyleId | (string & {});
  name: string;
  description: string;
  match_percent: number;
  duration: number;
  width: number;
  height: number;
  chosen: boolean;
}

export interface ChooseVariantResponse {
  ok: boolean;
  chosen: number;
  /** The new current version made from the chosen look (null for an old edit whose versions kept no plan). */
  job_id?: string | null;
  version?: number | null;
}

export interface StyleInfo {
  id: StyleId | (string & {});
  name: string;
  description: string;
  colors: string[];
}

export interface StylesResponse {
  styles: StyleInfo[];
}

/** `GET /projects/{id}/clips/{cid}/waveform` — peaks are normalised to 0..1. */
export interface Waveform {
  peaks: number[];
  duration: number;
}

export interface AgentLesson {
  text: string;
  created_at: string;
}

export interface AgentStat {
  name: string;
  role: string;
  total_points: number;
  runs: number;
  /** null until the agent has been scored at least once. */
  avg_score: number | null;
  last_delta: number;
  recent_lessons: AgentLesson[];
}

export interface Scoreboard {
  agents: AgentStat[];
}

export interface EditRequest {
  prompt: string;
  aspect_ratio?: AspectRatio;
  resolution?: Resolution;
  /** Number of alternative versions to render (default 1). */
  variations?: 1 | 2 | 3;
  style?: StyleId;
  /** Name of a project / library song to cut this edit to (GET /projects/{id}/music). */
  music_track?: string;
  /**
   * Timeline comment: seconds in the CURRENT edited output the prompt is about ("WOW likh do" at 12.4 s).
   * The edit then applies to that moment only; a comment that can't be read there answers 422 `not_understood`.
   */
  at?: number;
  /** Chat: where the player stands; "yaha / here" in the message means this second. */
  playhead?: number;
}

export interface EditResponse {
  job_id: string;
  status: JobStatus;
  /** The resolver applied its reading directly: what it did, in plain words ("4.3s par white flash"). */
  did?: string;
  /** apply | act (best guess applied, alternatives shown) | partial (the rest is in `unclear`) | undo. */
  decision?: string;
  /** Other readings of the same words: tapping one replaces the best guess (undo + apply). */
  alternatives?: IntentChoice[];
  /** Parts of the message that were not done, each with choices that ADD to the edit. */
  unclear?: { text: string; supported: boolean; choices: IntentChoice[] }[];
  request_id?: string | null;
}

/** A Tier 1 tool call (POST /projects/{id}/tools). */
export interface ToolCall {
  id: string;
  params?: Record<string, unknown>;
  time?: Record<string, unknown> | null;
}

/** One tap-able reading of an unclear request (422 "choose"). */
export interface IntentChoice {
  id: string;
  label: string;
  calls: ToolCall[];
}

export interface FeedbackRequest {
  rating: 'up' | 'down';
  comment?: string;
  agent?: string;
}

export interface FeedbackResponse {
  ok: boolean;
  points_delta: number;
}

export interface OkResponse {
  ok: boolean;
}

export interface UploadClipsResponse {
  clips: Clip[];
}

// ---- Edit Plan (subset of fields the app reads; extra fields are tolerated) ----

export interface PlanClip {
  source: string;
  in: number;
  out: number;
  order: number;
  speed: number;
  volume: number;
}

export interface PlanTransition {
  type: 'fade' | 'crossfade' | 'zoom' | 'wipe';
  after: number;
  duration: number;
}

export interface PlanText {
  kind: 'caption' | 'title' | 'watermark' | (string & {});
  text: string;
  start: number;
  end: number;
  /** Drawn behind the person in the shot. */
  behind?: boolean;
}

/** Sound settings of the plan (`audio`). */
export interface PlanAudio {
  music?: string | null;
  /** 0..1 */
  music_volume?: number;
  /** The video's own sound: 1 = as recorded (0..3). */
  voice_volume?: number;
  /** Seconds into the song where the music starts. */
  music_start?: number;
  /** Original sound off. */
  mute?: boolean;
  ducking?: boolean;
  [key: string]: unknown;
}

export interface PlanOverlay {
  kind: 'glow_frame' | 'wash' | 'bar' | (string & {});
  label: string;
  colors: string[];
  motion: 'rotate' | 'drift' | 'static' | (string & {});
  speed: number;
  opacity: number;
  thickness: number;
  start: number;
  end: number;
}

/** An emoji sticker placed for a moment of the edit ("rose ka sticker" at 12 s). */
export interface PlanSticker {
  emoji: string;
  word: string;
  start: number;
  end: number;
  position: string;
  size: number;
}

export interface EditPlan {
  version: string;
  /** Why each edit was made (editorial brain + agents). */
  decisions?: { decision: string; where: string; reason: string; skill: string }[];
  canvas: {
    aspect_ratio: AspectRatio;
    resolution: Resolution;
    fps: number;
    reframe: 'crop' | 'blur_pad';
  };
  clips: PlanClip[];
  transitions?: PlanTransition[];
  text?: PlanText[];
  /** Animated graphic overlays (glow frames, colour washes, bars). */
  overlays?: PlanOverlay[];
  /** Emoji stickers (timeline comments like "rose ka sticker"). */
  stickers?: PlanSticker[];
  audio?: PlanAudio;
  style?: string | null;
  [key: string]: unknown;
}

/** A file to upload, normalised across web and native. */
export interface UploadFile {
  /** Local URI (file://, content://, blob: or data:). */
  uri: string;
  name: string;
  type: string;
  /** On web the picker can hand us the underlying File directly. */
  file?: Blob;
}

// ---- Effects catalog (`GET /fx`) ----

/** Categories of `GET /fx`; unknown future categories are tolerated. */
export type FxCategory = 'motion' | 'video_effect' | 'transition' | 'color' | 'text_animation';

export interface FxItem {
  id: string;
  name: string;
  description: string;
}

export interface FxCatalogResponse {
  catalog: Partial<Record<FxCategory, FxItem[]>>;
  counts: Record<string, number>;
}

// ---- Project memory (`GET /projects/{id}/memory`) ----

export interface MemoryDelivered {
  style: string | null;
  aspect_ratio: AspectRatio | (string & {}) | null;
  color_preset: string | null;
  duration: number | null;
  effects: string[];
  transition: string | null;
  captions: boolean | null;
}

export interface MemoryHistoryItem {
  job_id: string;
  prompt: string;
  created_at: string;
  chosen_style: string | null;
  rating: 'up' | 'down' | null;
  intent: Record<string, unknown>;
  delivered: MemoryDelivered | null;
}

export interface MemoryPreferences {
  edits_remembered: number;
  favourite_style?: string | null;
  disliked_styles?: string[];
  usual_aspect_ratio?: string | null;
  favourite_colour_look?: string | null;
  captions_share?: number;
}

export interface ProjectMemory {
  history: MemoryHistoryItem[];
  preferences: MemoryPreferences;
  summary: string;
}

/** One hand-made change for POST /projects/{id}/manual (applied as given, no AI). */
export type ManualOp =
  | { op: 'add_text'; text: string; preset?: string; font?: string; color?: string; size?: number; position?: string;
      animation?: string; start?: number; end?: number; track?: 'none' | 'person' | 'face'; behind?: boolean }
  | { op: 'update_text'; index: number; text?: string; preset?: string; font?: string; color?: string; animation?: string;
      behind?: boolean }
  | { op: 'remove_text'; index: number }
  | { op: 'style_captions'; preset?: string; font?: string; color?: string; animation?: string; size?: number; position?: string }
  | { op: 'remove_captions' }
  | { op: 'add_effect'; type: string; start?: number; end?: number }
  | { op: 'remove_effect'; type: string }
  | { op: 'set_transition'; type: string | null; duration?: number }
  | { op: 'set_look'; preset: string }
  | { op: 'set_style'; style: string | null }
  | { op: 'delete_segment'; index: number }
  | { op: 'set_speed'; index: number; speed: number }
  | { op: 'move_segment'; index: number; to: number }
  | { op: 'set_audio'; music?: string; no_music?: boolean; music_volume?: number; voice_volume?: number; mute?: boolean;
      music_start?: number };

// ---- Songs (`GET /projects/{id}/music`) ----

export type SongFeel = 'slow' | 'medium' | 'fast';

export interface Song {
  name: string;
  source: 'project' | 'library';
  selected: boolean;
  /** seconds */
  duration?: number;
  /** bpm */
  tempo?: number;
  feel?: SongFeel;
  /** Seconds into the song where the beat drops (null / absent = none found). */
  drop?: number | null;
}

export interface SongsResponse {
  selected: string | null;
  project: Song[];
  library: Song[];
}

export interface SelectSongResponse {
  selected: string | null;
}

/** GET /text-styles */
export interface TextStylesResponse {
  fonts: { id: string; family: string; look: string }[];
  presets: { id: string; name: string; font: string; color: string; outline_color: string | null; box_color: string | null; uppercase: boolean }[];
  colors: { word: string; hex: string }[];
  animations: { id: string; description: string }[];
}

/** GET /prompts — ready-made professional briefs. */
export interface PromptLibraryResponse {
  prompts: { id: string; title: string; genre: string; prompt: string; does: string }[];
  genres: { id: string; name: string; structure: string }[];
  platforms: { id: string; name: string; aspect: string }[];
  skills: number;
}

/** The editorial spec POST /understand returns for vague / creative requests. */
export interface EditSpecInfo {
  concepts: string[];
  genres: { id: string; name: string; why: string }[];
  platform: { id: string; name: string; aspect: string } | null;
  skills: { id: string; name: string; why: string }[];
  explicit: string[];
  inferred: { field: string; value: unknown; reason: string; skill: string; source: string }[];
  unknown: string[];
  avoid: string[];
  structure: string;
}

/** GET / POST /projects/{pid}/reference — a video someone else edited, measured so the agents can copy its style. */
export interface ReferenceInfo {
  name: string;
  /** Human lines, e.g. "16s 9:16", "18 shots, median 0.67s", "warm". */
  summary: string[];
  /** Measurements the agents copy; `song` is the project song made from its soundtrack (null when silent). */
  recipe: Record<string, unknown> & { song?: string | null };
}

// ---- Copy an Edit (`/projects/{pid}/copy-edit`) ----

export interface BlueprintShot {
  start: number;
  dur: number;
  bw: boolean;
  flash: boolean;
  zoom: boolean;
  motion?: number;
  bright?: number;
  text?: boolean;
}

/** What the agent saw in the liked edit, shot by shot. */
export interface Blueprint {
  name: string;
  duration: number;
  aspect: AspectRatio | (string & {});
  song: string | null;
  shots: BlueprintShot[];
  summary: string[];
  color?: { preset: string | null } | null;
  /** Server paths of one JPEG per shot; prefix with the API base URL. */
  thumbs: string[];
  /** On-screen text the agent read from the liked video (OCR). */
  texts?: BlueprintText[];
}

export interface BlueprintText {
  start: number;
  end: number;
  text: string;
  position?: string | null;
  size?: number | string | null;
}

/** Copy an Edit is analysed in the background (1–3 min on CPU): GET /projects/{pid}/copy-edit. */
export type CopyEditState =
  | { status: 'analyzing'; progress: number; step?: string | null }
  | { status: 'ready'; blueprint: Blueprint }
  | { status: 'failed'; error: string };

export interface CopyEditRunRequest {
  prompt?: string;
  keep_sound?: boolean;
}

// ---- Templates (`/templates`) ----

export interface Template {
  id: string;
  name: string;
  category: string;
  kind: 'builtin' | 'mine';
  description: string;
  tags: string[];
  prompt: string;
  duration: number | null;
  aspect: AspectRatio | (string & {}) | null;
  colors: string[];
  /** Server path of the JPEG preview card; prefix with the API base URL. */
  preview_url: string;
}

export interface TemplatesResponse {
  templates: Template[];
  categories: string[];
}
