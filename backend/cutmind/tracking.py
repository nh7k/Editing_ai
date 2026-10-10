"""Subject tracking on CPU: find a person (or a face) in every sampled frame and follow the same one.

Detectors (both run on CPU, no GPU needed; models live in backend/assets/models):
* person — YOLOX-nano (Apache-2.0, 3.6 MB ONNX) via ONNX Runtime. Chosen over Ultralytics YOLOv8/11 because those
  are AGPL-3.0 (a problem for a closed-source product).
* face   — YuNet (MIT, OpenCV Zoo) via cv2.FaceDetectorYN.

The picture is sampled at SAMPLE_FPS on the light proxy; the subject is the biggest / most central detection in
the first frame where something is found, then the detection closest to the previous position in each frame.
Gaps are interpolated and the path is smoothed so a follow-crop doesn't shake. Results are cached per clip.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from .ffmpeg_utils import ffmpeg_bin, probe

MODEL_DIR = Path(__file__).resolve().parent.parent / "assets" / "models"
YOLOX = MODEL_DIR / "yolox_nano.onnx"
YUNET = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 5.0
TRACK_VERSION = 1
Target = Literal["person", "face"]


@dataclass
class Track:
    """Path of one subject in a clip. Points: (t seconds in the source, cx, cy, w, h) normalised 0..1."""

    target: str
    points: list[tuple[float, float, float, float, float]] = field(default_factory=list)
    found: float = 0.0          # share of sampled frames where the subject was really detected
    detector: str = ""

    def at(self, t: float) -> tuple[float, float, float, float] | None:
        if not self.points:
            return None
        ts = [p[0] for p in self.points]
        i = int(np.searchsorted(ts, t))
        if i <= 0:
            return self.points[0][1:]
        if i >= len(self.points):
            return self.points[-1][1:]
        a, b = self.points[i - 1], self.points[i]
        f = (t - a[0]) / max(1e-6, b[0] - a[0])
        return tuple(a[k] + (b[k] - a[k]) * f for k in range(1, 5))  # type: ignore[return-value]


# ---- detectors -----------------------------------------------------------------------------------------------
_lock = threading.Lock()
_sessions: dict[str, object] = {}


def models_available() -> dict[str, bool]:
    return {"person": YOLOX.exists(), "face": YUNET.exists()}


def _yolox():  # noqa: ANN202
    with _lock:
        if "yolox" not in _sessions:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            _sessions["yolox"] = ort.InferenceSession(str(YOLOX), opts, providers=["CPUExecutionProvider"])
        return _sessions["yolox"]


def _yolox_grid(size: int = 416) -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for s in (8, 16, 32):
        n = size // s
        yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)


_GRID, _STRIDES = _yolox_grid()


def detect_people(frame_rgb: np.ndarray, conf: float = 0.35) -> list[tuple[float, float, float, float, float]]:
    """YOLOX-nano person boxes as (cx, cy, w, h, score), normalised to the frame."""
    import cv2

    h, w = frame_rgb.shape[:2]
    r = min(416 / h, 416 / w)
    img = np.full((416, 416, 3), 114, dtype=np.uint8)
    rs = cv2.resize(frame_rgb[:, :, ::-1], (int(w * r), int(h * r)), interpolation=cv2.INTER_LINEAR)  # BGR
    img[: rs.shape[0], : rs.shape[1]] = rs
    blob = img.transpose(2, 0, 1)[None].astype(np.float32)
    out = _yolox().run(None, {"images": blob})[0][0]  # type: ignore[attr-defined]
    xy = (out[:, :2] + _GRID) * _STRIDES
    wh = np.exp(out[:, 2:4]) * _STRIDES
    score = out[:, 4] * out[:, 5]  # objectness * P(person); COCO class 0 = person
    keep = score > conf
    if not keep.any():
        return []
    xy, wh, score = xy[keep] / r, wh[keep] / r, score[keep]
    boxes = [[float(x - bw / 2), float(y - bh / 2), float(bw), float(bh)] for (x, y), (bw, bh) in zip(xy, wh, strict=True)]
    idx = cv2.dnn.NMSBoxes(boxes, score.tolist(), conf, 0.45)
    out_boxes = []
    for i in np.array(idx).flatten():
        x, y, bw, bh = boxes[int(i)]
        out_boxes.append(((x + bw / 2) / w, (y + bh / 2) / h, bw / w, bh / h, float(score[int(i)])))
    return out_boxes


def detect_faces(frame_rgb: np.ndarray, conf: float = 0.6) -> list[tuple[float, float, float, float, float]]:
    import cv2

    h, w = frame_rgb.shape[:2]
    with _lock:
        det = _sessions.get(f"yunet{w}x{h}")
        if det is None:
            det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), conf)
            _sessions[f"yunet{w}x{h}"] = det
    _ok, faces = det.detect(frame_rgb[:, :, ::-1].copy())  # type: ignore[attr-defined]
    if faces is None:
        return []
    return [((f[0] + f[2] / 2) / w, (f[1] + f[3] / 2) / h, f[2] / w, f[3] / h, float(f[-1])) for f in faces]


# ---- tracking --------------------------------------------------------------------------------------------------
def _frames(path: Path, fps: float, width: int) -> tuple[list[float], list[np.ndarray]]:
    info = probe(path)
    w = width
    h = int(round(info.height * w / max(1, info.width) / 2)) * 2
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=600).stdout
    n = len(raw) // (w * h * 3)
    frames = [np.frombuffer(raw[i * w * h * 3:(i + 1) * w * h * 3], dtype=np.uint8).reshape(h, w, 3) for i in range(n)]
    return [round(i / fps, 3) for i in range(n)], frames


def _pick_first(dets: list[tuple[float, float, float, float, float]]) -> tuple[float, float, float, float, float]:
    # biggest, and nearer the centre wins
    return max(dets, key=lambda d: d[2] * d[3] * (1.2 - abs(d[0] - 0.5)) * d[4])


def follow(times: list[float], per_frame: list[list[tuple[float, float, float, float, float]]], target: str,
           detector: str) -> Track:
    """Associate detections over time (nearest to the previous position), fill gaps, smooth."""
    raw: list[tuple[float, float, float, float, float] | None] = []
    prev = None
    for dets in per_frame:
        if not dets:
            raw.append(None)
            continue
        if prev is None:
            cur = _pick_first(dets)
        else:
            cur = min(dets, key=lambda d: (d[0] - prev[0]) ** 2 + (d[1] - prev[1]) ** 2 + 0.5 * (d[2] - prev[2]) ** 2)
            if (cur[0] - prev[0]) ** 2 + (cur[1] - prev[1]) ** 2 > 0.35 ** 2:  # jumped to someone else: hold
                raw.append(None)
                continue
        raw.append(cur)
        prev = cur
    hits = [i for i, d in enumerate(raw) if d is not None]
    if not hits:
        return Track(target, [], 0.0, detector)
    arr = np.zeros((len(raw), 4), dtype=np.float64)
    known = np.array(hits)
    for k in range(4):
        vals = np.array([raw[i][k] for i in hits])  # type: ignore[index]
        arr[:, k] = np.interp(np.arange(len(raw)), known, vals)
    # smooth: centred moving average over ~1 s (5 samples)
    win = 5
    pad = np.pad(arr, ((win // 2, win // 2), (0, 0)), mode="edge")
    kernel = np.ones(win) / win
    sm = np.stack([np.convolve(pad[:, k], kernel, mode="valid") for k in range(4)], axis=1)
    pts = [(times[i], *(round(float(x), 4) for x in sm[i])) for i in range(len(raw))]
    return Track(target, pts, round(len(hits) / len(raw), 3), detector)  # type: ignore[arg-type]


def track_clip(path: Path, target: Target = "person", cache_dir: Path | None = None) -> Track:
    """Track the main person/face in a clip (cached)."""
    cache = None
    if cache_dir is not None:
        st = path.stat()
        key = hashlib.sha1(f"{TRACK_VERSION}|{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{target}".encode()).hexdigest()[:16]
        cache = cache_dir / f"track_{key}.json"
        if cache.exists():
            d = json.loads(cache.read_text(encoding="utf-8"))
            return Track(d["target"], [tuple(p) for p in d["points"]], d["found"], d["detector"])  # type: ignore[misc]
    if not models_available()[target]:
        raise FileNotFoundError(f"{target} detector model missing in {MODEL_DIR}")
    times, frames = _frames(path, SAMPLE_FPS, 640)
    det = detect_people if target == "person" else detect_faces
    tr = follow(times, [det(f) for f in frames], target, "yolox_nano" if target == "person" else "yunet")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(asdict(tr)), encoding="utf-8")
    return tr
