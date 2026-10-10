import type { FxCategory, FxItem } from '../../api/types';

/** Tabs of the Effects panel, in display order. */
export const FX_TABS: { key: FxCategory; label: string }[] = [
  { key: 'motion', label: 'Motion' },
  { key: 'video_effect', label: 'Effects' },
  { key: 'transition', label: 'Transitions' },
  { key: 'color', label: 'Looks' },
  { key: 'text_animation', label: 'Text anim' },
];

/** Glyph shown on non-colour cards. */
export const FX_GLYPHS: Record<FxCategory, string> = {
  motion: '↔',
  video_effect: '✦',
  transition: '⇄',
  color: '◐',
  text_animation: 'Aa',
};

/** Two-colour swatches for the colour looks (unknown ids fall back to indigo → violet). */
export const LOOK_COLORS: Record<string, [string, string]> = {
  teal_orange: ['#0F766E', '#F97316'],
  golden_hour: ['#F59E0B', '#FB7185'],
  moody_blue: ['#1E3A8A', '#64748B'],
  cyberpunk: ['#EC4899', '#22D3EE'],
  forest: ['#14532D', '#84CC16'],
  faded_film: ['#D6C7A1', '#8B7E74'],
  pastel: ['#F9A8D4', '#A5B4FC'],
  noir: ['#111111', '#A3A3A3'],
  warm_film: ['#B45309', '#FDE68A'],
  arctic: ['#E0F2FE', '#38BDF8'],
};
export const DEFAULT_LOOK_COLORS: [string, string] = ['#6366F1', '#7C5CFF'];

export function lookColors(id: string): [string, string] {
  return LOOK_COLORS[id] ?? DEFAULT_LOOK_COLORS;
}

/** Natural-language phrase the prompt parser understands for a catalogue item. */
export function fxPhrase(category: FxCategory, item: FxItem): string {
  switch (category) {
    case 'motion':
      return item.name.toLowerCase();
    case 'video_effect':
      return `${item.name} effect`;
    case 'transition':
      return `${item.name} transitions`;
    case 'color':
      return `${item.name} look`;
    case 'text_animation':
      return `${item.name} captions`;
    default:
      return item.name;
  }
}

/**
 * Append `phrase` to a chat draft: empty → phrase; a draft ending in a space or comma
 * ("same as before but ") continues directly; otherwise the phrase is joined with ", ".
 */
export function appendPhrase(draft: string, phrase: string): string {
  if (!draft.trim()) return phrase;
  if (/,\s*$/.test(draft)) return `${draft.replace(/\s*$/, '')} ${phrase}`;
  if (/\s$/.test(draft)) return `${draft}${phrase}`;
  return `${draft}, ${phrase}`;
}

/** Put a memory shortcut ("same as before but ") in front of whatever is already typed. */
export function prefixPhrase(draft: string, prefix: string): string {
  const rest = draft.trimStart();
  if (rest.toLowerCase().startsWith(prefix.trim().toLowerCase())) return draft;
  return `${prefix}${rest}`;
}

/** Built-in style ids → display names (unknown ids are title-cased). */
export const STYLE_NAMES: Record<string, string> = {
  midnight_drift: 'Midnight Drift',
  violet_authority: 'Violet Authority',
  cyan_kinetic: 'Cyan Kinetic',
};

export function titleCaseId(id: string): string {
  return id
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export function styleName(id: string): string {
  return STYLE_NAMES[id] ?? titleCaseId(id);
}

/** Total shown in the panel header: `counts.total` when present, else the sum of the categories. */
export function totalCount(counts: Record<string, number> | undefined): number {
  if (!counts) return 0;
  if (typeof counts.total === 'number') return counts.total;
  return Object.values(counts).reduce((a, n) => a + (Number.isFinite(n) ? n : 0), 0);
}
