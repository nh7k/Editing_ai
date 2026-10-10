import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { State } from 'react-native-gesture-handler';
import { fireGestureHandler, getByGestureTestId } from 'react-native-gesture-handler/jest-utils';

import { ApiError, api } from '../src/api/client';
import { COMMENT_PLACEHOLDER } from '../src/components/studio/StudioTimeline';
import { StudioEditor } from '../src/screens/StudioEditor';
import { emptyMemory, fxCatalog, project, screenProps, studioPlan, studioStyles, variationsJob } from './fixtures';

type Props = Parameters<typeof StudioEditor>[0];
const VIEW_W = 1000;

async function renderStudio() {
  const props = screenProps({ projectId: 'p1' });
  await render(<StudioEditor {...(props as unknown as Props)} />);
  await screen.findByTestId('studio-editor');
  await screen.findByTestId('segment-s0');
  // give the tracks a width so x → seconds works, and turn snapping off so the time is exactly where we press
  await fireEvent(screen.getByTestId('timeline-view'), 'layout', { nativeEvent: { layout: { width: VIEW_W, height: 200 } } });
  await fireEvent.press(screen.getByTestId('snap-toggle'));
}

async function longPressAt(x: number) {
  await act(async () => {
    fireGestureHandler(getByGestureTestId('timeline-long-press'), [
      { state: State.BEGAN, x },
      { state: State.ACTIVE, x },
      { state: State.END, x },
    ]);
  });
}

/** Seconds shown in the box ("📍 @ 4.5s" → 4.5). */
function boxSeconds(): number {
  const label = screen.getByTestId('timeline-comment-time');
  const text = [label.props.children].flat().join('');
  const m = /@ ([\d.]+)s/.exec(text);
  if (!m) throw new Error(`no time in "${text}"`);
  return Number(m[1]);
}

describe('Timeline comments', () => {
  let startEdit: jest.SpyInstance;
  let understand: jest.SpyInstance;

  beforeEach(() => {
    jest.spyOn(api, 'getProject').mockResolvedValue(project);
    jest.spyOn(api, 'getPlan').mockResolvedValue(studioPlan);
    jest.spyOn(api, 'getJob').mockResolvedValue(variationsJob);
    jest.spyOn(api, 'getWaveform').mockResolvedValue({ peaks: [0.1, 0.5], duration: 12 });
    jest.spyOn(api, 'listStyles').mockResolvedValue({ styles: studioStyles });
    jest.spyOn(api, 'getProjectMemory').mockResolvedValue(emptyMemory);
    jest.spyOn(api, 'getFxCatalog').mockResolvedValue(fxCatalog);
    understand = jest.spyOn(api, 'understand').mockResolvedValue(null as never);
    startEdit = jest.spyOn(api, 'startEdit').mockResolvedValue({ job_id: 'j9', status: 'queued' });
  });
  afterEach(() => jest.restoreAllMocks());

  it('a long-press on the timeline pauses and opens a comment box at that time', async () => {
    await renderStudio();
    await fireEvent.press(screen.getByTestId('transport-play'));
    expect(screen.getByTestId('transport-play').props.accessibilityLabel).toBe('Pause');
    expect(screen.queryByTestId('timeline-comment-box')).toBeNull();

    await longPressAt(VIEW_W / 2);

    expect(await screen.findByTestId('timeline-comment-box')).toBeTruthy();
    expect(screen.getByTestId('timeline-comment-input').props.placeholder).toBe(COMMENT_PLACEHOLDER);
    expect(boxSeconds()).toBeGreaterThan(0);
    // playback stopped at that moment
    expect(screen.getByTestId('transport-play').props.accessibilityLabel).toBe('Play');

    await fireEvent.press(screen.getByTestId('timeline-comment-cancel'));
    expect(screen.queryByTestId('timeline-comment-box')).toBeNull();
    expect(startEdit).not.toHaveBeenCalled();
  });

  it('sending a comment calls the edit API with `at`, shows it in the chat and pins it on the timeline', async () => {
    await renderStudio();
    await longPressAt(VIEW_W / 2);
    const sec = boxSeconds();

    // nothing to send yet
    await fireEvent.press(screen.getByTestId('timeline-comment-send'));
    expect(startEdit).not.toHaveBeenCalled();

    await fireEvent.changeText(screen.getByTestId('timeline-comment-input'), 'WOW likh do');
    await fireEvent.press(screen.getByTestId('timeline-comment-send'));

    await waitFor(() => expect(startEdit).toHaveBeenCalledTimes(1));
    const [pid, body] = startEdit.mock.calls[0];
    expect(pid).toBe('p1');
    expect(body.prompt).toBe('WOW likh do');
    expect(body.at).toBeCloseTo(sec, 1);
    // a comment is about one moment: the whole-video prompt coach is not asked
    expect(understand).not.toHaveBeenCalled();

    expect(screen.queryByTestId('timeline-comment-box')).toBeNull();
    expect(await screen.findByText(`📍 ${sec.toFixed(1)}s: WOW likh do`)).toBeTruthy();
    const pin = await screen.findByTestId('timeline-comment-marker-0');
    expect(pin.props.accessibilityLabel).toBe(`Comment @ ${sec.toFixed(1)}s: WOW likh do`);
  });

  it('a click while paused opens the box too; the toolbar pin uses the playhead time', async () => {
    await renderStudio();
    await screen.findByTestId('timeline-comment-open');
    await fireEvent.press(screen.getByTestId('timeline-comment-open'));
    expect(await screen.findByTestId('timeline-comment-box')).toBeTruthy();
    expect(boxSeconds()).toBe(0);
    await fireEvent.press(screen.getByTestId('timeline-comment-cancel'));

    await act(async () => {
      fireGestureHandler(getByGestureTestId('timeline-tap'), [
        { state: State.BEGAN, x: VIEW_W / 4 },
        { state: State.ACTIVE, x: VIEW_W / 4 },
        { state: State.END, x: VIEW_W / 4 },
      ]);
    });
    expect(await screen.findByTestId('timeline-comment-box')).toBeTruthy();
    expect(boxSeconds()).toBeGreaterThan(0);
  });

  it('a comment the agent cannot understand (422) shows its message in the chat and is not pinned', async () => {
    startEdit.mockRejectedValue(
      new ApiError('not_understood', 'Is moment pe "xyz" samajh nahi aaya. Aise likho: "zoom", "WOW likh do".', 422),
    );
    await renderStudio();
    await longPressAt(VIEW_W / 2);
    await fireEvent.changeText(screen.getByTestId('timeline-comment-input'), 'xyz');
    await fireEvent.press(screen.getByTestId('timeline-comment-send'));

    expect(await screen.findByTestId('agent-error')).toBeTruthy();
    expect(screen.getByText(/Is moment pe "xyz" samajh nahi aaya/)).toBeTruthy();
    expect(screen.getByText(/📍 [\d.]+s: xyz/)).toBeTruthy();
    expect(screen.queryByTestId('timeline-comment-marker-0')).toBeNull();
  });
});
