export const colors = {
  background: '#0E0F13',
  card: '#1A1C23',
  cardAlt: '#22252E',
  border: '#2A2D37',
  text: '#F4F5F7',
  textMuted: '#9A9DAB',
  textFaint: '#6B6E7B',
  accent: '#7C5CFF',
  accentSoft: 'rgba(124, 92, 255, 0.16)',
  mint: '#2DD4A7',
  mintSoft: 'rgba(45, 212, 167, 0.14)',
  coral: '#FF6B57',
  coralSoft: 'rgba(255, 107, 87, 0.14)',
  amber: '#FFB547',
  amberSoft: 'rgba(255, 181, 71, 0.14)',
  overlay: 'rgba(0, 0, 0, 0.6)',
} as const;

/** Palette used to colour timeline segments. */
export const segmentColors = [colors.accent, colors.mint, colors.coral, colors.amber, '#4FA3FF', '#E067D9'];

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

export const radius = { sm: 8, md: 12, lg: 18, xl: 24, pill: 999 } as const;

export type FontWeightName = 'regular' | 'medium' | 'semibold' | 'bold';

/** Inter font family names registered with expo-font (see App.tsx). */
export const interFamilies: Record<FontWeightName, string> = {
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  bold: 'Inter_700Bold',
};

/** Numeric weights used when the Inter font is not (yet) available. */
export const fallbackWeights: Record<FontWeightName, '400' | '500' | '600' | '700'> = {
  regular: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
};

export const fontSizes = { xs: 11, sm: 13, md: 15, lg: 18, xl: 22, xxl: 28 } as const;
