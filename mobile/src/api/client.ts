import { Platform } from 'react-native';

import { getApiKey, getBaseUrl } from '../store/settings';
import type {
  Blueprint,
  ChooseVariantResponse,
  CopyEditRunRequest,
  CopyEditState,
  EditPlan,
  EditRequest,
  EditResponse,
  FeedbackRequest,
  FeedbackResponse,
  FxCatalogResponse,
  Health,
  Job,
  ManualOp,
  OkResponse,
  OutputFormat,
  PhraseBookResponse,
  Project,
  ProjectMemory,
  PromptLibraryResponse,
  ReferenceInfo,
  Scoreboard,
  SelectSongResponse,
  Song,
  SongsResponse,
  StylesResponse,
  TeachPhraseResponse,
  Template,
  TemplatesResponse,
  TextStylesResponse,
  Understood,
  VersionInfo,
  ToolCall,
  UploadClipsResponse,
  UploadFile,
  Waveform,
} from './types';

export const DEFAULT_TIMEOUT_MS = 15_000;
// starting an edit may first run the Hinglish translator on the CPU (a few seconds, more on a busy machine)
export const EDIT_TIMEOUT_MS = 90_000;
export const UPLOAD_TIMEOUT_MS = 10 * 60_000;

/** Error raised for every failed API call. `code` follows the backend's snake_case codes. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  /** The rest of the backend's error object (e.g. `choices` + `request_id` of a 422 "choose"). */
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, status = 0, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Human readable message for any thrown value. */
export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

function joinUrl(path: string, baseUrl: string = getBaseUrl()): string {
  return `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`;
}

/**
 * Build an ApiError from a response body that may follow
 * `{"error": {"code", "message"}}`, FastAPI's `{"detail": ...}`, or be non-JSON.
 */
export function parseErrorBody(status: number, bodyText: string): ApiError {
  let parsed: unknown;
  try {
    parsed = bodyText ? JSON.parse(bodyText) : undefined;
  } catch {
    parsed = undefined;
  }
  if (parsed && typeof parsed === 'object') {
    const obj = parsed as Record<string, unknown>;
    const err = obj.error;
    if (err && typeof err === 'object') {
      const { code, message, ...details } = err as Record<string, unknown>;
      return new ApiError(
        typeof code === 'string' ? code : `http_${status}`,
        typeof message === 'string' ? message : `Request failed (${status})`,
        status,
        details,
      );
    }
    if (typeof obj.detail === 'string') {
      return new ApiError(`http_${status}`, obj.detail, status);
    }
  }
  const snippet = bodyText.trim().slice(0, 200);
  return new ApiError(`http_${status}`, snippet || `Request failed with status ${status}`, status);
}

/** Header carrying the optional API key (backend env CUTMIND_API_KEY). */
export const API_KEY_HEADER = 'X-API-Key';

/**
 * Error for a non-2xx response. A 401 means the backend requires an API key and ours is
 * missing or wrong, so the message points the user to Settings.
 */
function httpError(status: number, bodyText: string): ApiError {
  const err = parseErrorBody(status, bodyText);
  if (status !== 401) return err;
  const base = err.code === 'unauthorized' ? err.message : 'Unauthorized.';
  const hint = getApiKey()
    ? 'Check the API key in Settings (it must match CUTMIND_API_KEY on the backend).'
    : 'Set the API key in Settings (the backend has CUTMIND_API_KEY set).';
  return new ApiError('unauthorized', `${base} ${hint}`, status);
}

/**
 * Append `api_key=<key>` to a media URL (video/image elements cannot send headers).
 * Returns the URL unchanged when no key is configured.
 */
export function withApiKey(url: string, apiKey: string = getApiKey()): string {
  if (!apiKey) return url;
  return `${url}${url.includes('?') ? '&' : '?'}api_key=${encodeURIComponent(apiKey)}`;
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { [API_KEY_HEADER]: key } : {};
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  timeoutMs?: number;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, timeoutMs = DEFAULT_TIMEOUT_MS } = opts;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  let res: Response;
  try {
    res = await fetch(joinUrl(path), {
      method,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...authHeaders(),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (e) {
    if (timedOut) {
      throw new ApiError('timeout', `Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw new ApiError('network_error', `Cannot reach the backend at ${getBaseUrl()} (${errorMessage(e)})`);
  } finally {
    clearTimeout(timer);
  }

  const text = await res.text();
  if (res.status === 404 && path === '/projects') {
    // CutMind always has /projects: a 404 here means another app answers at this address (e.g. port 8000 in use).
    throw new ApiError(
      'not_cutmind',
      `The server at ${getBaseUrl()} is not CutMind (another app answered). Open Settings and enter the CutMind backend address, e.g. http://localhost:8010.`,
      404,
    );
  }
  if (!res.ok) throw httpError(res.status, text);
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError('invalid_response', 'The backend returned an invalid JSON response', res.status);
  }
}

const enc = encodeURIComponent;

// ---------------------------------------------------------------- uploads

async function appendFile(form: FormData, file: UploadFile, field = 'files'): Promise<void> {
  if (Platform.OS === 'web') {
    let blob = file.file;
    if (!blob) {
      const res = await fetch(file.uri);
      blob = await res.blob();
    }
    form.append(field, blob, file.name);
  } else {
    // React Native's FormData accepts {uri, name, type} objects for files.
    form.append(field, { uri: file.uri, name: file.name, type: file.type } as unknown as Blob);
  }
}

export interface UploadProgress {
  loaded: number;
  total: number;
  fraction: number;
}

/** POST a multipart form with upload progress (fetch has no upload progress events). */
function postForm<T>(path: string, form: FormData, onProgress?: (p: UploadProgress) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', joinUrl(path));
    xhr.setRequestHeader('Accept', 'application/json');
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && ev.total > 0) {
          onProgress({ loaded: ev.loaded, total: ev.total, fraction: ev.loaded / ev.total });
        }
      };
    }
    xhr.onload = () => {
      const text = typeof xhr.responseText === 'string' ? xhr.responseText : '';
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(text) as T);
        } catch {
          reject(new ApiError('invalid_response', 'The backend returned an invalid JSON response', xhr.status));
        }
      } else {
        reject(httpError(xhr.status, text));
      }
    };
    xhr.onerror = () => reject(new ApiError('network_error', `Upload failed: cannot reach ${getBaseUrl()}`));
    xhr.ontimeout = () => reject(new ApiError('timeout', 'Upload timed out'));
    xhr.send(form);
  });
}

function uploadClips(
  projectId: string,
  files: UploadFile[],
  onProgress?: (p: UploadProgress) => void,
): Promise<UploadClipsResponse> {
  return (async () => {
    const form = new FormData();
    for (const f of files) {
      await appendFile(form, f);
    }
    return postForm<UploadClipsResponse>(`/projects/${enc(projectId)}/clips`, form, onProgress);
  })();
}

/** Upload a song (audio file, or a video whose sound is used); the backend also selects it. */
function uploadSong(projectId: string, file: UploadFile, onProgress?: (p: UploadProgress) => void): Promise<Song> {
  return (async () => {
    const form = new FormData();
    await appendFile(form, file, 'file');
    return postForm<Song>(`/projects/${enc(projectId)}/music`, form, onProgress);
  })();
}

/** Voice prompt: a recorded Blob (web) → English text from the backend's local Whisper. */
async function transcribeVoice(audio: Blob, filename = 'voice.webm'): Promise<{ text: string; language: string | null }> {
  const form = new FormData();
  form.append('audio', audio, filename);
  let res: Response;
  try {
    res = await fetch(joinUrl('/transcribe'), { method: 'POST', headers: { Accept: 'application/json', ...authHeaders() }, body: form });
  } catch (e) {
    throw new ApiError('network_error', `Cannot reach the backend at ${getBaseUrl()} (${errorMessage(e)})`);
  }
  const text = await res.text();
  if (!res.ok) throw httpError(res.status, text);
  return JSON.parse(text) as { text: string; language: string | null };
}

/** Upload a reference video (someone else's edit); the backend measures it and makes a song from its sound. */
function uploadReference(
  projectId: string,
  file: UploadFile,
  onProgress?: (p: UploadProgress) => void,
): Promise<ReferenceInfo> {
  return (async () => {
    const form = new FormData();
    await appendFile(form, file, 'file');
    return postForm<ReferenceInfo>(`/projects/${enc(projectId)}/reference`, form, onProgress);
  })();
}

/** The project's reference video, or null when none was uploaded (404 no_reference). */
async function getReference(projectId: string): Promise<ReferenceInfo | null> {
  try {
    return await request<ReferenceInfo>(`/projects/${enc(projectId)}/reference`);
  } catch (e) {
    if (e instanceof ApiError && (e.code === 'no_reference' || e.status === 404)) return null;
    throw e;
  }
}

/**
 * Normalise a Copy-an-Edit response: `{status: analyzing|ready|failed, ...}`; a bare Blueprint (older backend)
 * counts as ready.
 */
export function toCopyEditState(raw: unknown): CopyEditState {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  if (r.status === 'ready' && r.blueprint && typeof r.blueprint === 'object') {
    return { status: 'ready', blueprint: r.blueprint as Blueprint };
  }
  if (r.status === 'failed') return { status: 'failed', error: typeof r.error === 'string' ? r.error : 'Analysis failed' };
  if (Array.isArray(r.shots)) return { status: 'ready', blueprint: r as unknown as Blueprint };
  const progress = typeof r.progress === 'number' && Number.isFinite(r.progress) ? r.progress : 0;
  return { status: 'analyzing', progress, step: typeof r.step === 'string' ? r.step : null };
}

/**
 * "Copy an Edit": upload the liked edit. The backend answers 202 `{status: "analyzing"}` at once and watches the
 * video in the background (1–3 min); poll getCopyEdit for the blueprint.
 */
function uploadCopyEdit(projectId: string, file: UploadFile, onProgress?: (p: UploadProgress) => void): Promise<CopyEditState> {
  return (async () => {
    const form = new FormData();
    await appendFile(form, file, 'file');
    return toCopyEditState(await postForm<unknown>(`/projects/${enc(projectId)}/copy-edit`, form, onProgress));
  })();
}

/** State of the project's Copy-an-Edit analysis, or null when no video was uploaded (404 no_blueprint). */
async function getCopyEdit(projectId: string): Promise<CopyEditState | null> {
  try {
    return toCopyEditState(await request<unknown>(`/projects/${enc(projectId)}/copy-edit`));
  } catch (e) {
    if (e instanceof ApiError && (e.code === 'no_blueprint' || e.status === 404)) return null;
    throw e;
  }
}

/**
 * Image URL for a server path the backend hands out (`thumb`, `preview_url`, blueprint `thumbs`):
 * prefixed with the API base URL, with `api_key` when a key is set. Absolute URLs are only given the key.
 */
function mediaUrl(path: string): string {
  return withApiKey(/^https?:\/\//i.test(path) ? path : joinUrl(path));
}

// ---------------------------------------------------------------- endpoints

export const api = {
  health: () => request<Health>('/health', { timeoutMs: 5_000 }),

  listProjects: () => request<Project[]>('/projects'),
  createProject: (name: string) => request<Project>('/projects', { method: 'POST', body: { name } }),
  getProject: (id: string) => request<Project>(`/projects/${enc(id)}`),
  deleteProject: (id: string) => request<OkResponse>(`/projects/${enc(id)}`, { method: 'DELETE' }),

  uploadClips,
  transcribeVoice,
  /** Prompt coach: rough Hinglish → clean English prompt + what was understood (instant, no model call). */
  understand: (prompt: string, projectId?: string) =>
    request<Understood>('/understand', { method: 'POST', body: { prompt, ...(projectId ? { project_id: projectId } : {}) }, timeoutMs: EDIT_TIMEOUT_MS }),
  /** Teach the agent that `phrase` (and its Hinglish word forms) means `command`. */
  teachPhrase: (phrase: string, command: string) =>
    request<TeachPhraseResponse>('/phrasebook', { method: 'POST', body: { phrase, command } }),
  /** Taught phrases, recent misses and the teachable commands. */
  getPhraseBook: () => request<PhraseBookResponse>('/phrasebook'),
  /** Hand-made changes, applied directly (no AI); text-only changes re-use the cached cut. */
  manualEdit: (projectId: string, ops: ManualOp[]) =>
    request<EditResponse>(`/projects/${enc(projectId)}/manual`, { method: 'POST', body: { ops } }),
  getTextStyles: () => request<TextStylesResponse>('/text-styles'),
  getPrompts: () => request<PromptLibraryResponse>('/prompts'),
  /** SSE URL of a job's live events (EventSource can't send headers, so the API key goes in the query). */
  jobEventsUrl: (jobId: string, after = 0) => withApiKey(joinUrl(`/jobs/${enc(jobId)}/events?after=${after}`)),
  deleteClip: (projectId: string, clipId: string) =>
    request<OkResponse>(`/projects/${enc(projectId)}/clips/${enc(clipId)}`, { method: 'DELETE' }),
  /** Image URL; carries `api_key` as a query param when a key is set (images can't send headers). */
  thumbnailUrl: (projectId: string, clipId: string) =>
    withApiKey(joinUrl(`/projects/${enc(projectId)}/clips/${enc(clipId)}/thumbnail`)),

  startEdit: (projectId: string, body: EditRequest) =>
    request<EditResponse>(`/projects/${enc(projectId)}/edit`, { method: 'POST', body, timeoutMs: EDIT_TIMEOUT_MS }),
  getJob: (jobId: string) => request<Job>(`/jobs/${enc(jobId)}`),
  /** Run Tier 1 tool calls on the latest version (a tapped choice of an unclear request). */
  runTools: (projectId: string, calls: ToolCall[], prompt = '') =>
    request<EditResponse>(`/projects/${enc(projectId)}/tools`, { method: 'POST', body: { calls, prompt } }),
  /** Remember which reading the user tapped (local memory for the same words next time). */
  pickChoice: (requestId: string, choiceId: string) =>
    request<{ ok: boolean }>('/tools/resolve/pick', { method: 'POST', body: { request_id: requestId, choice_id: choiceId } }),
  getPlan: (projectId: string) => request<EditPlan>(`/projects/${enc(projectId)}/plan`),
  /**
   * URL of the rendered video (or its gif / mp3 extra); `version` busts caches after a new render.
   * `format` is only sent when it is not the default mp4.
   * Carries `api_key` as a query param when a key is set (video players can't send headers).
   */
  outputUrl: (
    projectId: string,
    version?: string | null,
    format: OutputFormat = 'mp4',
    /** Index of a job variation; omitted = the chosen / best version. */
    variant?: number | null,
  ) => {
    const params: string[] = [];
    if (version) params.push(`v=${enc(version)}`);
    if (variant !== undefined && variant !== null) params.push(`variant=${enc(String(variant))}`);
    if (format !== 'mp4') params.push(`format=${enc(format)}`);
    const query = params.length ? `?${params.join('&')}` : '';
    return withApiKey(joinUrl(`/projects/${enc(projectId)}/output${query}`));
  },

  /** Pick which variation becomes the project's output. */
  chooseVariant: (jobId: string, variant: number) =>
    request<ChooseVariantResponse>(`/jobs/${enc(jobId)}/choose`, { method: 'POST', body: { variant } }),
  listStyles: () => request<StylesResponse>('/styles'),
  /** JPEG strip of `frames` thumbnails (each 160×90) side by side. Carries `api_key` like thumbnailUrl. */
  filmstripUrl: (projectId: string, clipId: string, frames = 10) =>
    withApiKey(joinUrl(`/projects/${enc(projectId)}/clips/${enc(clipId)}/filmstrip?frames=${enc(String(frames))}`)),
  getWaveform: (projectId: string, clipId: string, points = 200) =>
    request<Waveform>(`/projects/${enc(projectId)}/clips/${enc(clipId)}/waveform?points=${enc(String(points))}`),

  sendFeedback: (jobId: string, body: FeedbackRequest) =>
    request<FeedbackResponse>(`/jobs/${enc(jobId)}/feedback`, { method: 'POST', body }),
  getScoreboard: () => request<Scoreboard>('/agents/scoreboard'),

  /** Catalogue of motion presets, video effects, transitions, colour looks and text animations. */
  getFxCatalog: () => request<FxCatalogResponse>('/fx'),
  /** What CutMind remembers about this project's past edits (history, preferences, summary). */
  listVersions: (projectId: string) =>
    request<{ versions: VersionInfo[] }>(`/projects/${enc(projectId)}/versions`),
  /** Back to the version before (no re-render: the old output is reused). Returns the new current job. */
  undo: (projectId: string) => request<{ job_id: string }>(`/projects/${enc(projectId)}/undo`, { method: 'POST' }),
  redo: (projectId: string) => request<{ job_id: string }>(`/projects/${enc(projectId)}/redo`, { method: 'POST' }),
  restoreVersion: (projectId: string, jobId: string) =>
    request<{ job_id: string }>(`/projects/${enc(projectId)}/versions/${enc(jobId)}/restore`, { method: 'POST' }),
  getProjectMemory: (projectId: string) => request<ProjectMemory>(`/projects/${enc(projectId)}/memory`),

  /** Songs: the project's own uploads + the built-in library, with tempo / feel / drop. */
  listSongs: (projectId: string) => request<SongsResponse>(`/projects/${enc(projectId)}/music`),
  uploadSong,
  /** Pick the song AI edits use (null = none). */
  selectSong: (projectId: string, name: string | null) =>
    request<SelectSongResponse>(`/projects/${enc(projectId)}/music/selected`, { method: 'PUT', body: { name } }),
  /** Remove one of the project's own songs (library songs can't be deleted). */
  deleteSong: (projectId: string, name: string) =>
    request<OkResponse>(`/projects/${enc(projectId)}/music/${enc(name)}`, { method: 'DELETE' }),
  /** Audio URL for previewing a song; carries `api_key` like thumbnailUrl. */
  songFileUrl: (projectId: string, name: string) =>
    withApiKey(joinUrl(`/projects/${enc(projectId)}/music/${enc(name)}/file`)),

  /** "Edit like a video": the reference edit whose rhythm, colour, flashes and song the agents copy. */
  getReference,
  uploadReference,
  deleteReference: (projectId: string) =>
    request<OkResponse>(`/projects/${enc(projectId)}/reference`, { method: 'DELETE' }),

  mediaUrl,

  /** Copy an Edit: rebuild a liked edit (same shots, lengths, B&W, flashes, song) from your footage. */
  uploadCopyEdit,
  getCopyEdit,
  deleteCopyEdit: (projectId: string) =>
    request<{ deleted: boolean }>(`/projects/${enc(projectId)}/copy-edit`, { method: 'DELETE' }),
  runCopyEdit: (projectId: string, body: CopyEditRunRequest = {}) =>
    request<EditResponse>(`/projects/${enc(projectId)}/copy-edit/run`, { method: 'POST', body, timeoutMs: EDIT_TIMEOUT_MS }),
  /** Save the blueprint as one of "my" templates. */
  saveCopyEditTemplate: (projectId: string, name: string) =>
    request<Template>(`/projects/${enc(projectId)}/copy-edit/template`, { method: 'POST', body: { name } }),

  /** Template gallery (built-ins + mine) and its categories. */
  listTemplates: () => request<TemplatesResponse>('/templates'),
  applyTemplate: (projectId: string, templateId: string, prompt?: string) =>
    request<EditResponse>(`/projects/${enc(projectId)}/templates/${enc(templateId)}/apply`, {
      method: 'POST',
      body: prompt ? { prompt } : {},
      timeoutMs: EDIT_TIMEOUT_MS,
    }),
  /** Only "mine" templates can be deleted. */
  deleteTemplate: (templateId: string) => request<unknown>(`/templates/${enc(templateId)}`, { method: 'DELETE' }),

  /** Test a base URL without saving it. /health is public, so no API key is sent. */
  healthAt: async (baseUrl: string): Promise<Health> => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5_000);
    try {
      const res = await fetch(joinUrl('/health', baseUrl), { signal: controller.signal });
      const text = await res.text();
      if (!res.ok) throw parseErrorBody(res.status, text);
      return JSON.parse(text) as Health;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      if (controller.signal.aborted) throw new ApiError('timeout', 'Health check timed out after 5s');
      throw new ApiError('network_error', `Cannot reach ${baseUrl} (${errorMessage(e)})`);
    } finally {
      clearTimeout(timer);
    }
  },
};

export type Api = typeof api;
