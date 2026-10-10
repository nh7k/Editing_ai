/** Desktop studio palette (dark stage with blue / violet / cyan accents). */
export const studio = {
  bg: '#0B0C10',
  panel: '#15171E',
  card: '#1E2029',
  cardHover: '#252836',
  border: '#262935',
  blue: '#2F80FF',
  blueSoft: 'rgba(47, 128, 255, 0.18)',
  violet: '#7C5CFF',
  cyan: '#22D3EE',
  indigo: '#6366F1',
  purple: '#C77DDB',
  green: '#22C55E',
  red: '#F87171',
  text: '#E6E8EE',
  muted: '#8A90A2',
  faint: '#5B6072',
  stage: '#050608',
  white: '#FFFFFF',
} as const;

/** Glow colours used around the preview (cyan → indigo → violet). */
export const glowColors = [studio.cyan, studio.indigo, studio.violet, studio.blue, studio.cyan];
