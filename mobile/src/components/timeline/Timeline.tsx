// Native: Skia is available synchronously.
import SkiaTimeline from './SkiaTimeline';
import { TimelineShell } from './TimelineShell';
import type { TimelineProps } from './types';

export function Timeline(props: TimelineProps) {
  return (
    <TimelineShell model={props.model}>
      <SkiaTimeline {...props} />
    </TimelineShell>
  );
}
