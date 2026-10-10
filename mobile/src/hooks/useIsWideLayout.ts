import { useWindowDimensions } from 'react-native';

/** Window width (px) from which the Editor route switches to the desktop studio layout. */
export const STUDIO_MIN_WIDTH = 1024;

export function useIsWideLayout(): boolean {
  const { width } = useWindowDimensions();
  return width >= STUDIO_MIN_WIDTH;
}
