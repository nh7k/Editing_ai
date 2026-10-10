// Web: Skia needs CanvasKit (WASM). It is served from /canvaskit.wasm (copied into public/
// by `npm run setup:skia-web`) and the Skia component is lazy-loaded once CanvasKit is ready.
import { WithSkiaWeb } from '@shopify/react-native-skia/lib/module/web';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { colors } from '../../theme';
import { TimelineShell } from './TimelineShell';
import type { TimelineProps } from './types';

function Fallback({ height = 64 }: { height?: number }) {
  return (
    <View style={[styles.fallback, { height }]}>
      <ActivityIndicator color={colors.accent} />
    </View>
  );
}

export function Timeline(props: TimelineProps) {
  return (
    <TimelineShell model={props.model}>
      <WithSkiaWeb
        opts={{ locateFile: (file: string) => `/${file}` }}
        getComponent={() => import('./SkiaTimeline')}
        fallback={<Fallback height={props.height} />}
        componentProps={props}
      />
    </TimelineShell>
  );
}

const styles = StyleSheet.create({
  fallback: { alignItems: 'center', justifyContent: 'center' },
});
