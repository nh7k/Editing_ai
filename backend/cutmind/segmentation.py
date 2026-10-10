"""Person cut-out masks on CPU, for text that goes BEHIND a person (the "COLD" look of fan edits).

Model: PP-HumanSeg (OpenCV Zoo, Apache-2.0, 6 MB ONNX, 192x192 input) run with ONNX Runtime. A portrait model sees
a far-away player as a few pixels, so people are first found with YOLOX-nano (tracking.detect_people) and each
person is segmented inside their own (enlarged) box. Nothing outside a person box can end up in the mask.

Only frames inside the windows of "behind" text are processed (about 2 per 1/15 s); masks are smoothed over time so
the cut-out edge doesn't flicker.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import numpy as np

from .ffmpeg_utils import ffmpeg_bin, probe
from .tracking import MODEL_DIR, YOLOX, detect_people

SEG_MODEL = MODEL_DIR / "human_segmentation_pphumanseg_2023mar.onnx"
SIZE = 192
MIN_PERSON_H = 0.10  # people smaller than 10 % of the frame height are ignored (too few pixels to cut out)
SEG_VERSION = 2   # bump when the person choice changes (cached masks are keyed on it)
MASK_FPS = 15.0      # how often the model runs inside a window; frames in between reuse the last mask

_lock = threading.Lock()
_session = None


def available() -> bool:
    return SEG_MODEL.exists() and YOLOX.exists()


def _seg():  # noqa: ANN202
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            _session = ort.InferenceSession(str(SEG_MODEL), opts, providers=["CPUExecutionProvider"])
        return _session


def _person_prob(crop_rgb: np.ndarray) -> np.ndarray:
    """P(person) for every pixel of an RGB crop (float32, crop size)."""
    import cv2

    h, w = crop_rgb.shape[:2]
    x = cv2.resize(crop_rgb, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
    x = ((x / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    s = _seg()
    logits = s.run(None, {s.get_inputs()[0].name: x})[0][0]  # (2, 192, 192)
    e = np.exp(logits - logits.max(axis=0, keepdims=True))
    prob = (e[1] / e.sum(axis=0)).astype(np.float32)
    return cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)


def torso_rgb(frame_rgb: np.ndarray, box: tuple[float, float, float, float, float]) -> np.ndarray:
    """Mean colour of the upper body (shirt / jersey) inside a person box."""
    h, w = frame_rgb.shape[:2]
    cx, cy, bw, bh, _s = box
    x0, x1 = int(max(0, (cx - bw * 0.22) * w)), int(min(w, (cx + bw * 0.22) * w))
    y0, y1 = int(max(0, (cy - bh * 0.30) * h)), int(min(h, (cy + bh * 0.02) * h))
    patch = frame_rgb[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    return patch.mean(axis=0) if len(patch) else np.zeros(3, np.float32)


def color_distance(rgb: np.ndarray, hex_color: str) -> float:
    """0 = same colour family. Hue decides for colourful targets, brightness for white / black / grey."""
    import colorsys

    t = np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], np.float32) / 255.0
    th, ts, tv = colorsys.rgb_to_hsv(*t)
    ch, cs, cv = colorsys.rgb_to_hsv(*(np.clip(rgb, 0, 255) / 255.0))
    if ts < 0.2:  # white / black / grey shirt
        return abs(cv - tv) + 0.8 * cs
    if cs < 0.22 or cv < 0.15:
        return 1.0  # a white / grey / black shirt with a colour tint from the grade is not "blue"
    dh = min(abs(ch - th), 1 - abs(ch - th)) * 2  # 0..1
    return dh + 0.6 * max(0.0, 0.35 - cs) + 0.3 * max(0.0, 0.25 - cv)


def pick_person(frame_rgb: np.ndarray, people: list[tuple[float, float, float, float, float]], color: str | None,
                prev: tuple[float, float, float, float, float] | None) -> tuple[float, float, float, float, float] | None:
    """The one person to focus on: the closest clothes colour (if given), staying with the same person over time."""
    cands = [p for p in people if p[3] >= MIN_PERSON_H * 0.6]
    if not cands:
        return None

    def cost(p: tuple[float, float, float, float, float]) -> float:
        c = color_distance(torso_rgb(frame_rgb, p), color) if color else -(p[2] * p[3]) * (1.2 - abs(p[0] - 0.5))
        if prev is not None:
            c += 1.5 * ((p[0] - prev[0]) ** 2 + (p[1] - prev[1]) ** 2) ** 0.5
        return c

    best = min(cands, key=cost)
    if color and color_distance(torso_rgb(frame_rgb, best), color) > 0.35:
        return None  # nobody in that colour in this frame
    return best


def person_mask(frame_rgb: np.ndarray, color: str | None = None, only_one: bool = False,
                prev: list | None = None) -> np.ndarray:
    """0..1 float mask of the people in a frame (0 where nobody is). `only_one`: just the chosen person (clothes
    `color`, else the biggest / most central); `prev` (a one-item list) carries the choice between frames."""
    h, w = frame_rgb.shape[:2]
    mask = np.zeros((h, w), np.float32)
    people = detect_people(frame_rgb, conf=0.4)
    if only_one:
        chosen = pick_person(frame_rgb, people, color, prev[0] if prev else None)
        if prev is not None:
            prev[:] = [chosen if chosen is not None else (prev[0] if prev else None)]
        people = [chosen] if chosen is not None else []
    for cx, cy, bw, bh, _score in people:
        if bh < MIN_PERSON_H and not only_one:
            continue
        # enlarge the box a little: arms, hair and feet often stick out of a detector box
        x0, x1 = int(max(0, (cx - bw * 0.65) * w)), int(min(w, (cx + bw * 0.65) * w))
        y0, y1 = int(max(0, (cy - bh * 0.58) * h)), int(min(h, (cy + bh * 0.58) * h))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        p = _person_prob(frame_rgb[y0:y1, x0:x1])
        mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], np.clip((p - 0.35) / 0.3, 0.0, 1.0))
    return mask


def mask_video(video: Path, windows: list[tuple[float, float]], out: Path, color: str | None = None,
               only_one: bool = False) -> Path:
    """Grey mask video (same size / fps / length as `video`): white = person, black = not; only inside `windows`.
    `only_one`: the one person to focus on (clothes `color`, else the main person)."""
    import cv2

    info = probe(video)
    w, h, fps = info.width, info.height, info.fps or 30.0
    n = int(round(info.duration * fps))
    every = max(1, int(round(fps / MASK_FPS)))
    dec = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}",
                            "-r", f"{fps:.6f}", "-i", "-", "-c:v", "ffv1", "-pix_fmt", "gray", str(out)],
                           stdin=subprocess.PIPE)
    assert dec.stdout is not None and enc.stdin is not None
    frame_bytes = w * h * 3
    zero = np.zeros((h, w), np.uint8).tobytes()
    last: np.ndarray | None = None
    chosen: list = [None]
    try:
        for i in range(n):
            buf = dec.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            t = i / fps
            if not any(a - 0.1 <= t <= b + 0.1 for a, b in windows):
                last = None
                enc.stdin.write(zero)
                continue
            if last is None or i % every == 0:
                m = person_mask(np.frombuffer(buf, np.uint8).reshape(h, w, 3), color, only_one, chosen)
                last = m if last is None else 0.6 * m + 0.4 * last  # temporal smoothing against flicker
            enc.stdin.write((cv2.GaussianBlur(last, (5, 5), 0) * 255).astype(np.uint8).tobytes())
        else:
            i = n
        for _ in range(max(0, n - i)):  # keep the frame count identical to the video
            enc.stdin.write(zero)
    finally:
        enc.stdin.close()
        dec.stdout.close()
        dec.wait()
        enc.wait()
    if enc.returncode != 0:
        raise RuntimeError("person mask encode failed")
    return out
