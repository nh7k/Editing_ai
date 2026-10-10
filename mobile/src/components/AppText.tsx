import { StyleSheet, Text, type TextProps, type TextStyle } from 'react-native';

import { colors, fallbackWeights, fontSizes, interFamilies, type FontWeightName } from '../theme';
import { useFontsReady } from './FontContext';

export interface AppTextProps extends TextProps {
  size?: keyof typeof fontSizes;
  weight?: FontWeightName;
  color?: string;
  muted?: boolean;
  center?: boolean;
}

export function AppText({ size = 'md', weight = 'regular', color, muted, center, style, ...rest }: AppTextProps) {
  const fontsReady = useFontsReady();
  const fontStyle: TextStyle = fontsReady
    ? { fontFamily: interFamilies[weight] }
    : { fontWeight: fallbackWeights[weight] };
  return (
    <Text
      {...rest}
      style={[
        { fontSize: fontSizes[size], lineHeight: Math.round(fontSizes[size] * 1.4) },
        fontStyle,
        { color: color ?? (muted ? colors.textMuted : colors.text) },
        center && styles.center,
        style,
      ]}
    />
  );
}

const styles = StyleSheet.create({
  center: { textAlign: 'center' },
});
