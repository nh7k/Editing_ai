import { VideoView, type VideoPlayer } from 'expo-video';
import { StyleSheet, View } from 'react-native';

import { colors, radius } from '../theme';
import { AppText } from './AppText';

export interface VideoPreviewProps {
  player: VideoPlayer;
  hasOutput: boolean;
}

/** Shows the rendered output, or a placeholder until the first render exists. */
export function VideoPreview({ player, hasOutput }: VideoPreviewProps) {
  return (
    <View style={styles.frame}>
      {hasOutput ? (
        <VideoView player={player} style={styles.video} nativeControls contentFit="contain" testID="video-view" />
      ) : (
        <View style={styles.placeholder} testID="video-placeholder">
          <AppText size="xxl" color={colors.accent}>
            ▶
          </AppText>
          <AppText weight="semibold">No render yet</AppText>
          <AppText size="sm" muted center>
            Describe your edit below and the agents will cut a preview.
          </AppText>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    width: '100%',
    aspectRatio: 16 / 9,
    maxHeight: 420,
    backgroundColor: '#000000',
    borderRadius: radius.lg,
    overflow: 'hidden',
  },
  video: { width: '100%', height: '100%' },
  placeholder: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 6, padding: 16 },
});
