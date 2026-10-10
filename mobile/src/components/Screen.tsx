import type { ReactNode } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

import { colors } from '../theme';

export interface ScreenProps {
  children: ReactNode;
  edges?: Edge[];
  style?: StyleProp<ViewStyle>;
}

/** Full-screen dark container that respects safe areas and caps width on large (web) screens. */
export function Screen({ children, edges = ['bottom', 'left', 'right'], style }: ScreenProps) {
  return (
    <SafeAreaView edges={edges} style={styles.root}>
      <View style={[styles.inner, style]}>{children}</View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  inner: { flex: 1, width: '100%', maxWidth: 760, alignSelf: 'center' },
});
