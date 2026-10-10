"""Copy a camera move: measure how the picture moves in each shot of a liked video (push-in, pull-out, pan, tilt,
roll, shake) and play the same move on the user's footage.

Measuring (CPU, OpenCV): corner features tracked frame to frame (Lucas-Kanade), a similarity transform fitted to them
with RANSAC (scale, rotation, shift), accumulated into a path per shot. Only textured pixels count, and the top and
bottom bands (captions, phone UI) are ignored — the idea and the classification thresholds follow ReelMimic's
analyze.py (MIT, github.com/edenfunf/reelmimic), which labels shots the same way but does not replay the move.

Replaying (FFmpeg): rotate → zoom (scale, per frame) → crop window that slides, all as piecewise-linear expressions in
`t`. The picture is enlarged just enough that the slide / rotation never shows an edge.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .ffmpeg_utils import ffmpeg_bin

FPS = 10.0
TW = 320          # tracking width (height follows the aspect)
EDGE = 0.12       # ignored band at the top and bottom (captions, phone UI)
MAX_SCALE = 1.45  # the most we enlarge the user's shot to make room for a move
MAX_ZOOM = 1.6    # the most a replayed push-in / pull-out zooms (more looks soft on 720p footage)


def gray_frames(video: Path, height: int, width: int) -> np.ndarray:
    th = max(2, int(round(TW * height / max(1, width) / 2)) * 2)
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(video), "-vf",
           f"fps={FPS},scale={TW}:{th}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=900).stdout
    n = len(raw) // (TW * th)
    return np.frombuffer(raw[: n * TW * th], np.uint8).reshape(n, th, TW)


def _step(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> tuple[float, float, float, float]:
    """(scale, angle, dx, dy) of the picture from frame a to b; dx/dy as shares of the frame, at the centre."""
    import cv2

    pts = cv2.goodFeaturesToTrack(a, maxCorners=220, qualityLevel=0.01, minDistance=7, mask=mask)
    if pts is None or len(pts) < 12:
        return 1.0, 0.0, 0.0, 0.0
    nxt, st, _err = cv2.calcOpticalFlowPyrLK(a, b, pts, None, winSize=(21, 21), maxLevel=3)
    ok = st.reshape(-1) == 1
    if ok.sum() < 10:
        return 1.0, 0.0, 0.0, 0.0
    m, inl = cv2.estimateAffinePartial2D(pts[ok], nxt[ok], method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if m is None or inl is None or inl.sum() < 8:
        return 1.0, 0.0, 0.0, 0.0
    s = math.hypot(m[0, 0], m[1, 0])
    ang = math.atan2(m[1, 0], m[0, 0])
    h, w = a.shape
    cx, cy = w / 2, h / 2
    nx, ny = m[0, 0] * cx + m[0, 1] * cy + m[0, 2], m[1, 0] * cx + m[1, 1] * cy + m[1, 2]
    if not (0.8 < s < 1.25) or abs(ang) > 0.2:
        return 1.0, 0.0, 0.0, 0.0  # a cut / flash inside the shot, not a camera move
    return s, ang, (nx - cx) / w, (ny - cy) / h


def shot_path(gray: np.ndarray, start: float, end: float) -> dict[str, Any] | None:
    """The move of one shot: path [[t, zoom, dx, dy, angle], ...] (t from the shot start, zoom 1 = as it began),
    its kind, pace and shake. None for shots too short to measure."""
    import cv2

    i0, i1 = int(round(start * FPS)), min(len(gray), int(round(end * FPS)))
    if i1 - i0 < 3:
        return None
    h, w = gray.shape[1:]
    mask = np.zeros((h, w), np.uint8)
    mask[int(h * EDGE): int(h * (1 - EDGE)), :] = 255
    z, a, x, y = 1.0, 0.0, 0.0, 0.0
    path = [[0.0, 1.0, 0.0, 0.0, 0.0]]
    steps = []
    for k in range(i0, i1 - 1):
        f0, f1 = gray[k], gray[k + 1]
        if cv2.Laplacian(f0, cv2.CV_32F).var() < 15:
            st = (1.0, 0.0, 0.0, 0.0)  # flat frame (black, fade): nothing to track
        else:
            st = _step(f0, f1, mask)
        steps.append(st)
        s, ang, dx, dy = st
        z *= s
        a += ang
        x += dx
        y += dy
        path.append([round((k + 1 - i0) / FPS, 3), round(z, 4), round(x, 4), round(y, 4), round(a, 4)])
    dxs = np.array([s[2] for s in steps])
    dys = np.array([s[3] for s in steps])
    # shake: the jitter left after a short moving average of the per-frame shift
    shake = 0.0
    if len(dxs) >= 5:
        ker = np.ones(5) / 5
        jx = dxs - np.convolve(dxs, ker, "same")
        jy = dys - np.convolve(dys, ker, "same")
        shake = float(np.sqrt((jx[2:-2] ** 2 + jy[2:-2] ** 2).mean())) if len(jx) > 4 else 0.0
    dur = max(1e-3, path[-1][0])
    lz, net_x, net_y, net_a = math.log(z), x, y, a
    moves = {"push_in": lz, "pull_out": -lz, "move_right": -net_x, "move_left": net_x,
             "move_down": -net_y, "move_up": net_y, "roll": abs(net_a) * 2}
    # thresholds per shot (as ReelMimic): ~4 % zoom, ~6 % slide, ~2° roll
    need = {"push_in": 0.04, "pull_out": 0.04, "move_right": 0.06, "move_left": 0.06, "move_down": 0.06,
            "move_up": 0.06, "roll": 0.07}
    kind = max(moves, key=lambda k: moves[k] / need[k])
    if moves[kind] < need[kind]:
        kind = "static"
    speed = (abs(lz) + math.hypot(net_x, net_y) + abs(net_a)) / dur
    pace = "still" if kind == "static" else "slow" if speed < 0.06 else "medium" if speed < 0.18 else "fast"
    if shake > 0.004:
        kind = "shake" if kind == "static" else kind + "+shake"
    return {"kind": kind, "pace": pace, "shake": round(shake, 4), "path": path}


# ---- replaying on the user's footage -----------------------------------------------------------------------
def _expr(keys: list[tuple[float, float]], var: str = "t", digits: int = 4) -> str:
    keys = [(round(t, 3), round(v, digits)) for t, v in keys]
    if len(keys) == 1:
        return f"{keys[0][1]}"
    out = f"{keys[-1][1]}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:], strict=False))):
        slope = (v1 - v0) / max(1e-3, t1 - t0)
        out = f"if(lt({var}\\,{t1})\\,{v0}+({slope:.5f})*({var}-{t0})\\,{out})"
    return f"if(lt({var}\\,{keys[0][0]})\\,{keys[0][1]}\\,{out})"


def _smooth_keys(path: list[list[float]], max_keys: int = 24) -> list[list[float]]:
    """Fewer keyframes (FFmpeg expressions get long), each a small average so tracking noise is not replayed."""
    if len(path) <= max_keys:
        return path
    arr = np.array(path, dtype=float)
    idx = np.linspace(0, len(arr) - 1, max_keys).round().astype(int)
    out = []
    for i in idx:
        lo, hi = max(0, i - 1), min(len(arr), i + 2)
        row = arr[lo:hi].mean(axis=0)
        row[0] = arr[i, 0]
        out.append(row.tolist())
    out[0], out[-1] = arr[0].tolist(), arr[-1].tolist()
    return out


def replay_filters(points: list[list[float]], w: int, h: int, duration: float, strength: float = 1.0,
                   fps: int = 30, easing: str | None = None) -> list[str]:
    """FFmpeg filters (for a w×h segment) that move the picture the way `points` describes. `easing` (motion
    engine): authored keyframes, eased between keys (not smoothed); None = a measured path, linear between keys."""
    if not points or len(points) < 2:
        return []
    keys = [list(p) for p in points] if easing else _smooth_keys(points)
    if easing:
        from .engines.motion import expr as eased

        def ex(k: list[tuple[float, float]], var: str = "t") -> str:
            return eased(k, var, easing)
    else:
        ex = _expr  # (a nested def named _expr made _expr local to this function: every plain zoom crashed)
    src_dur = max(1e-3, keys[-1][0])
    k = duration / src_dur  # the user's shot may be a little longer / shorter than the liked one
    zs = [p[1] ** strength for p in keys]
    zmin = min(zs)
    zrel = [z / zmin for z in zs]
    if max(zrel) > MAX_ZOOM:  # a whip-pan / crash zoom measured huge: the same shape, at most 1.6x (sharp enough)
        p = math.log(MAX_ZOOM) / math.log(max(zrel))
        zrel = [z ** p for z in zrel]
    xs = [p[2] * strength for p in keys]
    ys = [p[3] * strength for p in keys]
    an = [p[4] * strength for p in keys]
    # room for the slide and the rotation at the moment they need it most (at the smallest zoom)
    roll = max(abs(v) for v in an)
    margin = 1 + 2 * max(max(abs(v) for v in xs), max(abs(v) for v in ys)) + 1.3 * roll * max(w / h, h / w)
    if margin > MAX_SCALE:  # too big a move for the frame: replay it a bit smaller
        f = (MAX_SCALE - 1) / (margin - 1)
        xs, ys, an = [v * f for v in xs], [v * f for v in ys], [v * f for v in an]
        margin = MAX_SCALE
    ts = [p[0] * k for p in keys]
    zexpr = ex([(t, margin * z) for t, z in zip(ts, zrel, strict=False)], "it")
    xexpr = ex(list(zip(ts, xs, strict=False)), "it")
    yexpr = ex(list(zip(ts, ys, strict=False)), "it")
    out = []
    if roll > 0.003:
        out.append(f"rotate=a='{ex(list(zip(ts, an, strict=False)))}':ow=iw:oh=ih:c=black")
    # zoompan works on a fixed-size picture (crop after a per-frame scale keeps its first frame's size and drifts
    # to a corner); 2x first so the window can move by half pixels (no jitter)
    out.append(f"scale={2 * w}:{2 * h}")
    # the picture moved right by dx (share of the frame) → the window slides left by the same amount
    out.append(f"zoompan=z='{zexpr}':x='clip(iw/2-iw/zoom/2-({xexpr})*iw/zoom\\,0\\,iw-iw/zoom)'"
               f":y='clip(ih/2-ih/zoom/2-({yexpr})*ih/zoom\\,0\\,ih-ih/zoom)':d=1:s={w}x{h}:fps={fps}")
    return out
