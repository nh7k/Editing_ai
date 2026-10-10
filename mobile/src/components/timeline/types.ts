import type { TimelineModel } from '../../utils/timelineModel';

export interface TimelineProps {
  model: TimelineModel;
  height?: number;
  /** Called with the output time (seconds) when the user releases the playhead. */
  onSeek?: (seconds: number) => void;
}
