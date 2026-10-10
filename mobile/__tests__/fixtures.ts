import type { AgentStat, Clip, EditPlan, FxCatalogResponse, Job, JobVariation, Project, ProjectMemory, StyleInfo } from '../src/api/types';

export const clipA: Clip = {
  id: 'c1',
  filename: 'beach.mp4',
  duration: 12,
  width: 1920,
  height: 1080,
  fps: 30,
  has_audio: true,
  size_bytes: 12_000_000,
};

export const clipB: Clip = { ...clipA, id: 'c2', filename: 'city.mp4', duration: 8 };

export const project: Project = {
  id: 'p1',
  name: 'Lisbon reel',
  created_at: '2026-10-01T10:00:00Z',
  clips: [clipA, clipB],
  last_job_id: 'j1',
  has_output: true,
};

export const runningJob: Job = {
  id: 'j1',
  project_id: 'p1',
  prompt: 'Trim to 15s',
  status: 'running',
  progress: 45,
  stage: 'cutter',
  error: null,
  match_percent: null,
  created_at: '2026-10-01T10:01:00Z',
  finished_at: null,
  agents: [
    { name: 'Analyzer', status: 'done', progress: 100, score: 100, attempts: 1, message: 'Analysed 2 clips' },
    { name: 'Cutter', status: 'retrying', progress: 50, score: 55, attempts: 2, message: 'Re-cutting to fit 15s' },
    { name: 'Color', status: 'pending', progress: 0, score: null, attempts: 0, message: '' },
  ],
  logs: [
    { t: '2026-10-01T10:01:01Z', agent: 'Director', level: 'info', msg: 'Parsed intent: 15s' },
    { t: '2026-10-01T10:01:05Z', agent: 'Cutter', level: 'warn', msg: 'Duration 19s exceeds target' },
  ],
  review: {
    checks: [
      { name: 'duration', owner: 'Cutter', passed: false, detail: '19.0s vs 15s target', points: -15 },
      { name: 'plays', owner: 'Director', passed: true, detail: 'decoded fully', points: 10 },
    ],
    agent_scores: { Cutter: 55, Director: 100 },
    match_percent: 72,
  },
  output: null,
};

export const doneJob: Job = {
  ...runningJob,
  status: 'done',
  progress: 100,
  stage: 'done',
  match_percent: 92,
  finished_at: '2026-10-01T10:02:00Z',
  review: { ...runningJob.review!, match_percent: 92 },
  output: { duration: 15, width: 720, height: 1280, has_audio: true, size_bytes: 4_000_000 },
};

export const failedJob: Job = {
  ...runningJob,
  status: 'failed',
  stage: 'renderer',
  error: 'ffmpeg exited with code 1',
  review: null,
};

export const agents: AgentStat[] = [
  {
    name: 'Cutter',
    role: 'Selects and trims segments',
    total_points: 40,
    runs: 5,
    avg_score: 81,
    last_delta: -15,
    recent_lessons: [{ text: 'Respect the target duration', created_at: '2026-10-01T10:00:00Z' }],
  },
  {
    name: 'Color',
    role: 'Grades the footage',
    total_points: 120,
    runs: 5,
    avg_score: 97,
    last_delta: 10,
    recent_lessons: [],
  },
  {
    name: 'Audio',
    role: 'Music and ducking',
    total_points: 75,
    runs: 5,
    avg_score: 90,
    last_delta: 0,
    recent_lessons: [],
  },
];

/** Minimal navigation/route props for rendering screens outside a navigator. */
export function screenProps<P extends object>(params: P) {
  const navigation = {
    navigate: jest.fn(),
    setOptions: jest.fn(),
    goBack: jest.fn(),
    addListener: jest.fn(() => () => undefined),
  };
  return { navigation, route: { key: 'test', name: 'Test', params } };
}

// ---- studio fixtures ----


export const studioPlan: EditPlan = {
  version: '1',
  canvas: { aspect_ratio: '16:9', resolution: 720, fps: 30, reframe: 'crop' },
  clips: [
    { source: 'c1', in: 2, out: 8, order: 0, speed: 1, volume: 1 },
    { source: 'c2', in: 0, out: 8, order: 1, speed: 2, volume: 1 },
  ],
  transitions: [
    { type: 'crossfade', after: 0, duration: 1 },
    { type: 'fade', after: -1, duration: 0.5 },
  ],
  text: [
    { kind: 'title', text: 'Lisbon', start: 0, end: 2 },
    { kind: 'caption', text: 'Hello world', start: 3, end: 5 },
  ],
  overlays: [
    {
      kind: 'glow_frame',
      label: 'Cyan Indigo Glow',
      colors: ['#22D3EE', '#6366F1'],
      motion: 'rotate',
      speed: 1,
      opacity: 0.8,
      thickness: 4,
      start: 0,
      end: 9,
    },
    {
      kind: 'wash',
      label: 'Violet Wash',
      colors: ['#7C5CFF', '#0B0C10'],
      motion: 'drift',
      speed: 0.5,
      opacity: 0.3,
      thickness: 0,
      start: 1,
      end: 100,
    },
  ],
  style: 'midnight_drift',
};

export const variations: JobVariation[] = [
  {
    index: 0,
    style: 'midnight_drift',
    name: 'Midnight Drift',
    description: 'dark blue gradient, slow vertical drift',
    match_percent: 94,
    duration: 9,
    width: 1280,
    height: 720,
    chosen: true,
  },
  {
    index: 1,
    style: 'violet_authority',
    name: 'Violet Authority',
    description: 'blue-violet styling with a bold hook',
    match_percent: 90,
    duration: 9,
    width: 1280,
    height: 720,
    chosen: false,
  },
  {
    index: 2,
    style: 'cyan_kinetic',
    name: 'Cyan Kinetic',
    description: 'cyan-indigo accents, faster energy',
    match_percent: 86,
    duration: 9,
    width: 1280,
    height: 720,
    chosen: false,
  },
];

export const variationsJob: Job = {
  ...doneJob,
  prompt: 'Make three cinematic versions',
  output: { ...doneJob.output!, extras: ['gif'] },
  variations,
};

export const studioStyles: StyleInfo[] = [
  { id: 'midnight_drift', name: 'Midnight Drift', description: 'Dark blue drift', colors: ['#0B1A3A', '#2F80FF'] },
  { id: 'cyan_kinetic', name: 'Cyan Kinetic', description: 'Fast cyan energy', colors: ['#22D3EE', '#6366F1'] },
];

// ---- effects catalog + memory fixtures ----

export const fxCatalog: FxCatalogResponse = {
  catalog: {
    motion: [
      { id: 'pan_left', name: 'Pan Left', description: 'Slow camera pan to the left' },
      { id: 'zoom_in', name: 'Zoom In', description: 'Gentle push in' },
    ],
    video_effect: [
      { id: 'glitch', name: 'Glitch', description: 'Digital glitch with RGB tearing' },
      { id: 'vhs', name: 'VHS', description: 'Retro tape look with scanlines' },
      { id: 'film_grain', name: 'Film Grain', description: 'Organic analogue grain' },
    ],
    transition: [
      { id: 'pixelize', name: 'Pixelize', description: 'Dissolve through big pixels' },
      { id: 'circleopen', name: 'Circle Open', description: 'Iris opens from the centre' },
    ],
    color: [
      { id: 'teal_orange', name: 'Teal & Orange', description: 'Blockbuster teal shadows, warm skin' },
      { id: 'noir', name: 'Noir', description: 'High-contrast black and white' },
    ],
    text_animation: [{ id: 'karaoke', name: 'Karaoke', description: 'Words light up as they are spoken' }],
  },
  counts: { motion: 10, video_effect: 28, transition: 58, color: 10, text_animation: 6 },
};

export const emptyMemory: ProjectMemory = {
  history: [],
  preferences: { edits_remembered: 0 },
  summary: '',
};

export const projectMemory: ProjectMemory = {
  history: [
    {
      job_id: 'h1',
      prompt: 'first quick cut',
      created_at: '2026-10-01T10:00:00Z',
      chosen_style: null,
      rating: null,
      intent: {},
      delivered: { style: 'midnight_drift', aspect_ratio: '16:9', color_preset: null, duration: 20, effects: [], transition: null, captions: false },
    },
    {
      job_id: 'h2',
      prompt: 'vertical reel with captions',
      created_at: '2026-10-02T10:00:00Z',
      chosen_style: 'violet_authority',
      rating: 'up',
      intent: {},
      delivered: { style: 'violet_authority', aspect_ratio: '9:16', color_preset: 'teal_orange', duration: 15, effects: ['glitch'], transition: 'slideleft', captions: true },
    },
    {
      job_id: 'h3',
      prompt: 'glitch effect and karaoke captions',
      created_at: '2026-10-03T10:00:00Z',
      chosen_style: null,
      rating: null,
      intent: {},
      delivered: { style: 'violet_authority', aspect_ratio: '9:16', color_preset: null, duration: 12, effects: ['glitch'], transition: null, captions: true },
    },
    {
      job_id: 'h4',
      prompt: 'newest teal and orange version',
      created_at: '2026-10-04T10:00:00Z',
      chosen_style: 'violet_authority',
      rating: null,
      intent: {},
      delivered: { style: 'violet_authority', aspect_ratio: '9:16', color_preset: 'teal_orange', duration: 30, effects: [], transition: null, captions: true },
    },
  ],
  preferences: {
    edits_remembered: 4,
    favourite_style: 'violet_authority',
    disliked_styles: ['cyan_kinetic'],
    usual_aspect_ratio: '9:16',
    favourite_colour_look: 'teal_orange',
    captions_share: 0.75,
  },
  summary: 'You usually make 9:16 reels in Violet Authority with captions.',
};
