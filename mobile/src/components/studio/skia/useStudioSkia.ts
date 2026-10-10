// Native: Skia is available synchronously.
import * as parts from './StudioSkiaParts';

export type StudioSkiaParts = typeof parts;

/** Skia drawing components, or null while they are not available (web: CanvasKit still loading). */
export function useStudioSkia(): StudioSkiaParts | null {
  return parts;
}
