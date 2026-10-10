/* eslint-disable @typescript-eslint/no-require-imports */
import 'react-native-gesture-handler/jestSetup';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

// expo-video needs a native view + player; tests only need inert stand-ins.
jest.mock('expo-video', () => {
  const { View } = require('react-native');
  return {
    useVideoPlayer: () => ({ play: jest.fn(), pause: jest.fn(), seekBy: jest.fn(), currentTime: 0, loop: false }),
    VideoView: (props: Record<string, unknown>) => require('react').createElement(View, { ...props, testID: 'video-view' }),
  };
});

// The Skia timeline is exercised through its pure layout model (timelineModel tests);
// the canvas itself needs CanvasKit / native Skia, so it is replaced with a plain view.
jest.mock('./src/components/timeline/Timeline', () => {
  const { View, Text } = require('react-native');
  const React = require('react');
  return {
    Timeline: ({ model }: { model: { segments: { key: string; label: string }[] } }) =>
      React.createElement(
        View,
        { testID: 'timeline' },
        model.segments.map((s) => React.createElement(Text, { key: s.key }, s.label)),
      ),
  };
});

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);

// Native-only save/share modules: inert mocks (the web variants are not loaded under jest-expo's iOS preset).
jest.mock('expo-media-library', () => ({
  requestPermissionsAsync: jest.fn(async () => ({ granted: true })),
  Asset: { create: jest.fn(async () => ({})) },
}));
jest.mock('expo-sharing', () => ({
  isAvailableAsync: jest.fn(async () => true),
  shareAsync: jest.fn(async () => undefined),
}));

// Studio Skia drawings (glow border, gradient swatches, waveforms) need CanvasKit / native Skia;
// in tests the hook reports "not loaded" so the plain-view fallbacks render.
jest.mock('./src/components/studio/skia/useStudioSkia', () => ({ useStudioSkia: () => null }));
