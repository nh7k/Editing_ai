"""Copy an Edit: watch a finished edit shot by shot and rebuild the SAME edit from the user's raw footage.

Different from reference.py (which measures a STYLE — typical shot length, colour — and lets the agents decide): a
blueprint is the edit itself, in order:

* every shot: where it starts, how long it is (the cut list, PySceneDetect + frame differences)
* per shot: black & white or colour, brightness, how much moves in it (→ which of your shots goes there),
  camera zoom in / out (optical flow), a white flash at its start
* on-screen text: what it says, when, where and how big (RapidOCR, Apache-2.0, CPU — optional)
* the soundtrack: stored as a project song and played from the same point, so the cuts land on the same beats
* aspect ratio, length, overall colour

The cutter fills the shot list with the user's footage (the busiest footage in the busiest shots); the effects agent
puts B&W, flashes, zooms and the text at the same moments. Everything is measured on CPU; nothing leaves the machine.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .ffmpeg_utils import ffmpeg_bin, probe, run_ffmpeg

BLUEPRINT_VERSION = 1
FPS = 10.0               # analysis frames per second
W, H = 96, 54            # analysis frame size (aspect is irrelevant for these measurements)
MIN_SHOT = 0.25          # shorter "shots" are flashes / detector noise: merged into the neighbour


@dataclass
class Shot:
    start: float
    dur: float
    bw: bool = False
    flash: bool = False          # a white flash at the start of this shot
    zoom: str | None = None      # "in" / "out": the picture grows / shrinks during the shot
    camera: dict[str, Any] | None = None  # the measured camera move (cutmind/camera_move.py): kind, pace, shake, path
    motion: float = 0.0          # 0..1 rank of how much changes in the shot (1 = the busiest shot of the edit)
    bright: float = 0.0          # mean luma 0..1
    sat: float = 0.0
    warm: float = 0.0


@dataclass
class TextCue:
    start: float
    end: float
    text: str
    position: str = "center"     # top / center / bottom
    size: float = 0.05           # text height / frame height


@dataclass
class Blueprint:
    name: str = ""
    duration: float = 0.0
    aspect: str = "9:16"
    shots: list[Shot] = field(default_factory=list)
    texts: list[TextCue] = field(default_factory=list)
    song: str | None = None
    tempo: float = 0.0
    color: str | None = None     # overall look: warm / cool / vivid / bw / None
    ocr: bool = False            # was on-screen text read (RapidOCR installed)?
    version: int = BLUEPRINT_VERSION

    def summary(self) -> list[str]:
        durs = [s.dur for s in self.shots] or [0.0]
        out = [f"{self.duration:.0f}s {self.aspect}",
               f"{len(self.shots)} shots, {min(durs):.1f}–{max(durs):.1f} s (median {float(np.median(durs)):.1f} s)"]
        if self.song:
            out.append(f"its soundtrack is used from the same point{f' ({self.tempo:.0f} bpm)' if self.tempo else ''}")
        bw = sum(1 for s in self.shots if s.bw)
        if bw:
            out.append(f"{bw} black & white shot(s)")
        fl = sum(1 for s in self.shots if s.flash)
        if fl:
            out.append(f"{fl} white flash(es)")
        moves = [s.camera["kind"] for s in self.shots if s.camera and s.camera.get("kind") != "static"]
        if moves:
            names = {"push_in": "push-in", "pull_out": "pull-out", "move_left": "pan left", "move_right": "pan right",
                     "move_up": "tilt up", "move_down": "tilt down", "roll": "roll", "shake": "shake"}
            kinds = sorted({names.get(k.split("+")[0], k) for k in moves})
            out.append(f"{len(moves)} camera move(s): {', '.join(kinds)}")
        else:
            zm = sum(1 for s in self.shots if s.zoom)
            if zm:
                out.append(f"{zm} zoom move(s)")
        if self.texts:
            out.append(f"{len(self.texts)} text(s) on screen: " + ", ".join(f'"{t.text}"' for t in self.texts[:3])
                       + ("…" if len(self.texts) > 3 else ""))
        elif not self.ocr:
            out.append("on-screen text not read (RapidOCR not installed)")
        if self.color:
            out.append(f"{self.color} colour")
        return out

    def slots(self) -> list[tuple[float, float]]:
        return [(s.start, s.start + s.dur) for s in self.shots]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- measuring --------------------------------------------------------------------------------------------
def _frames(video: Path) -> np.ndarray:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(video), "-vf",
           f"fps={FPS},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=900).stdout
    n = len(raw) // (W * H * 3)
    return np.frombuffer(raw[: n * W * H * 3], np.uint8).reshape(n, H, W, 3).astype(np.float32)


def _cuts(video: Path, f: np.ndarray, duration: float) -> list[float]:
    """Shot changes: PySceneDetect, plus big jumps of the colour histogram it can miss in dark / fast edits."""
    from .agents.analyzer import detect_scenes

    cuts = [c for c in detect_scenes(video) if 0.1 < c < duration - 0.1]
    if len(f) > 2:
        hist = np.stack([np.histogram(fr.mean(axis=2), bins=16, range=(0, 255))[0] for fr in f]).astype(np.float32)
        hist /= np.maximum(hist.sum(axis=1, keepdims=True), 1)
        d = np.abs(np.diff(hist, axis=0)).sum(axis=1)          # 0..2
        thr = max(0.6, float(np.median(d)) * 6)
        for i in np.where(d > thr)[0]:
            t = (i + 1) / FPS
            if 0.1 < t < duration - 0.1 and all(abs(t - c) > 0.3 for c in cuts):
                cuts.append(round(t, 3))
    return sorted(cuts)


def _zoom(gray: np.ndarray) -> float:
    """Mean scale change per second over consecutive frames (optical flow, radial part). >0 = zooming in."""
    import cv2

    if len(gray) < 3:
        return 0.0
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    rx, ry = xs - W / 2, ys - H / 2
    rr = (rx * rx + ry * ry).sum()
    rates = []
    for a, b in zip(gray[:-1], gray[1:], strict=False):
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 2, 9, 2, 5, 1.1, 0)
        rates.append(float((flow[..., 0] * rx + flow[..., 1] * ry).sum() / rr))
    return float(np.median(rates)) * FPS


def _shot_stats(f: np.ndarray, edges: list[float]) -> list[Shot]:
    shots: list[Shot] = []
    mx, mn = f.max(axis=3), f.min(axis=3)
    sat = ((mx - mn) / np.maximum(mx, 1)).mean(axis=(1, 2))
    luma = f.mean(axis=3)
    ymean = luma.mean(axis=(1, 2))
    gray = luma.astype(np.uint8)
    for a, b in zip(edges[:-1], edges[1:], strict=False):
        i0, i1 = int(round(a * FPS)), max(int(round(a * FPS)) + 1, int(round(b * FPS)))
        seg = slice(i0, min(i1, len(f)))
        if seg.start >= len(f):
            shots.append(Shot(round(a, 3), round(b - a, 3)))
            continue
        s_sat = float(sat[seg].mean())
        colour = f[seg][sat[seg] >= 0.07]
        warm = float((colour[..., 0] - colour[..., 2]).mean() / 255) if len(colour) else 0.0
        motion = float(np.abs(np.diff(luma[seg], axis=0)).mean()) if i1 - i0 > 1 else 0.0
        # a flash: the first frames of the shot (or the last of the one before) jump to near-white
        k = list(range(max(0, i0 - 1), min(len(f), i0 + 2)))
        flash = any(ymean[j] > 200 and ymean[j] - float(np.median(ymean[seg])) > 45 for j in k)
        z = _zoom(gray[seg]) if i1 - i0 >= 4 else 0.0
        shots.append(Shot(start=round(a, 3), dur=round(b - a, 3), bw=s_sat < 0.07, flash=bool(flash),
                          zoom="in" if z > 0.035 else "out" if z < -0.035 else None,
                          motion=motion, bright=round(float(ymean[seg].mean()) / 255, 3), sat=round(s_sat, 3),
                          warm=round(warm, 3)))
    # motion as a rank: the busiest shot of THIS edit is 1.0 (absolute numbers differ between videos)
    order = sorted(range(len(shots)), key=lambda i: shots[i].motion)
    for r, i in enumerate(order):
        shots[i].motion = round(r / max(1, len(shots) - 1), 3)
    return shots


_HANDLE = re.compile(r"^[@B]?[A-Z0-9_.]{3,}$")  # "@DARIA.CUTS" watermarks (OCR reads "@" as "B" sometimes)


def _small(frame: np.ndarray, width: int = 480) -> np.ndarray:
    import cv2

    h, w = frame.shape[:2]
    return frame if w <= width else cv2.resize(frame, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)


def _same_text(a: str, b: str) -> bool:
    """Two OCR readings of one caption (spaces lost, an emoji read as a letter, one line missing)."""
    from difflib import SequenceMatcher

    ka, kb = re.sub(r"\W", "", a.lower()), re.sub(r"\W", "", b.lower())
    if not ka or not kb:
        return False
    short = min(len(ka), len(kb))
    return SequenceMatcher(None, ka, kb).ratio() >= 0.7 or (short >= 10 and ka[:short - 1] == kb[:short - 1])


def _stays(a: np.ndarray, b: np.ndarray) -> bool:
    """Do the LETTERS of a text box stay the same a moment later? Letters = pixels far from the box's middle tone
    (white or black text); the background between them may move — a caption sits over a moving picture."""
    if a.size == 0:
        return False
    la, lb = a.mean(axis=2), b.mean(axis=2)
    ink = np.abs(la - np.median(la)) > 60
    if ink.sum() < 12:
        return False
    return float(np.abs(la[ink] - lb[ink]).mean()) < 30


def _read_text(video: Path, duration: float, progress: Any = None) -> tuple[list[TextCue], bool]:
    """Captions / titles put ON the video (not text that is part of the filmed picture, not tiny watermarks), with
    their timing. ([], False) when RapidOCR is not installed.

    An overlay stays at the same place on the frame while the picture under it changes; text filmed on a screen or a
    sign moves and changes with the picture. So each text box is compared with the same spot a moment later."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return [], False
    from .ffmpeg_utils import extract_frame

    ocr = RapidOCR()
    step = max(1.0, duration / 40)
    looks: list[list[tuple[str, str, float, float, bool]]] = []  # per look: (text, position, height, cy, verified)
    times: list[float] = []
    t = 0.3
    n_looks = int((duration - 0.35) / step) + 1
    while t < duration - 0.05:
        try:
            a = _small(extract_frame(video, t)).astype(np.float32)
            b = _small(extract_frame(video, min(duration - 0.05, t + 0.4))).astype(np.float32)
        except Exception:  # noqa: BLE001
            t += step
            continue
        hgt_px = a.shape[0]
        res, _ = ocr(np.ascontiguousarray(a.astype(np.uint8)[:, :, ::-1]), use_cls=False)
        moved = float(np.abs(a - b).mean())
        found = []
        for box, text, conf in res or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            x0, x1, y0, y1 = (max(0, int(min(xs))), int(max(xs)) + 1, max(0, int(min(ys))), int(max(ys)) + 1)
            hgt = (y1 - y0) / hgt_px
            text = re.sub(r"[^\w?!.,'\" ]+$", "", text.strip())
            if float(conf) < 0.75 or hgt < 0.02 or len(text) < 2 or _HANDLE.match(text.replace(" ", "")):
                continue  # small UI text in the picture, watermarks, noise
            if abs((x0 + x1) / 2 / a.shape[1] - 0.5) > 0.12:
                continue  # an edit's captions are centred; text off to a side is part of the picture (a screen)
            stays = _stays(a[y0:y1, x0:x1], b[y0:y1, x0:x1])
            if moved > 3.0 and not stays:
                continue  # its letters changed with the picture: filmed text, not a caption
            text = " ".join(w for w in text.split() if len(w) > 1 or w.lower() in ("a", "i", "u") or w.isdigit())
            if len(text) < 2:
                continue  # an emoji read as a letter
            cy = (y0 + y1) / 2 / hgt_px
            pos = "top" if cy < 0.36 else "bottom" if cy > 0.66 else "center"
            # verified = it stayed put while the picture under it moved (only then is one sighting enough)
            found.append((text, pos, round(hgt, 3), cy, moved > 3.0))
        # lines of one caption (one under the other, same place) are one text
        found.sort(key=lambda f: f[3])
        joined: list[tuple[str, str, float, float, bool]] = []
        for f in found:
            if joined and joined[-1][1] == f[1] and f[3] - joined[-1][3] < 2.6 * max(f[2], joined[-1][2]):
                p = joined[-1]
                joined[-1] = (p[0] + " " + f[0], p[1], max(p[2], f[2]), f[3], p[4] and f[4])
            else:
                joined.append(f)
        looks.append(joined)
        times.append(t)
        if progress:
            progress(len(times) / max(1, n_looks))
        t += step
    cues: list[TextCue] = []
    seen: dict[int, list[int]] = {}  # id(cue) -> [sightings, verified sightings]
    for t, found in zip(times, looks, strict=False):
        for text, pos, hgt, _cy, ok in found:
            prev = next((c for c in reversed(cues) if c.position == pos and t - c.end <= 2 * step + 0.05
                         and _same_text(c.text, text)), None)
            if prev:
                seen[id(prev)][0] += 1
                seen[id(prev)][1] += int(ok)
                prev.end = round(min(duration, t + step / 2), 2)
                if len(text.replace(" ", "")) > len(prev.text.replace(" ", "")) or (  # the fuller reading wins
                        len(text) > len(prev.text) and text.replace(" ", "") == prev.text.replace(" ", "")):
                    prev.text = text[:80]
            else:
                cues.append(TextCue(start=round(max(0.0, t - step / 2), 2), end=round(min(duration, t + step / 2), 2),
                                    text=text[:80], position=pos, size=hgt))
                seen[id(cues[-1])] = [1, int(ok)]
    # seen once on a still picture: could be filmed text (a screen, a sign) — not trusted
    cues = [c for c in cues if seen[id(c)][1] >= 1 or seen[id(c)][0] >= 2]
    # text that sits in the picture the whole video long (a logo, a sign) is not an edit's caption
    cues = [c for c in cues if c.end - c.start < 0.9 * duration or len(cues) == 1]
    return cues, True


def analyze_blueprint(video: Path, work: Path, progress: Any = None) -> Blueprint:
    info = probe(video)
    bp = Blueprint(name=video.name, duration=round(info.duration, 2))
    ratio = info.width / max(1, info.height)
    bp.aspect = "9:16" if ratio < 0.8 else "1:1" if ratio < 1.25 else "16:9"
    f = _frames(video)
    edges = [0.0, *_cuts(video, f, info.duration), info.duration]
    # merge slivers (flash frames, detector noise) into the shot before
    merged = [edges[0]]
    for e in edges[1:-1]:
        if e - merged[-1] >= MIN_SHOT:
            merged.append(e)
    if edges[-1] - merged[-1] < MIN_SHOT and len(merged) > 1:
        merged.pop()
    merged.append(edges[-1])
    bp.shots = _shot_stats(f, merged)
    try:  # the camera move of every shot (push-in, pan, tilt, roll, shake) — replayed on the user's footage
        from .camera_move import gray_frames, shot_path

        g = gray_frames(video, info.height, info.width)
        for s in bp.shots:
            s.camera = shot_path(g, s.start, s.start + s.dur)
            kind = (s.camera or {}).get("kind", "")
            if s.camera is not None:  # the tracked move is more reliable than the flow estimate above
                s.zoom = "in" if kind.startswith("push_in") else "out" if kind.startswith("pull_out") else None
    except Exception:  # noqa: BLE001 — without it the copy still has cuts, colour, text and sound
        pass
    colour = [s for s in bp.shots if not s.bw]
    if bp.shots and sum(s.dur for s in bp.shots if s.bw) > 0.85 * bp.duration:
        bp.color = "bw"
    elif colour:
        sat = float(np.mean([s.sat for s in colour]))
        warm = float(np.mean([s.warm for s in colour]))
        bp.color = "vivid" if sat > 0.42 else "warm" if warm > 0.07 else "cool" if warm < -0.05 else None
    bp.texts, bp.ocr = _read_text(video, info.duration, progress)
    if info.has_audio:
        try:
            from .agents.analyzer import beat_grid
            from .ffmpeg_utils import extract_audio_wav

            work.mkdir(parents=True, exist_ok=True)
            tempo, _ = beat_grid(extract_audio_wav(video, work / "copy.wav", sr=22050))
            bp.tempo = round(tempo or 0.0, 1)
        except Exception:  # noqa: BLE001
            pass
    return bp


def save_thumbs(video: Path, bp: Blueprint, out_dir: Path) -> None:
    """One picture per shot (the Copy-an-Edit screen shows the shot list)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(bp.shots):
        try:
            run_ffmpeg(["-ss", f"{s.start + s.dur / 2:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=160:-2",
                        "-q:v", "6", str(out_dir / f"{i}.jpg")])
        except Exception:  # noqa: BLE001
            pass


def save_blueprint(bp: Blueprint, path: Path) -> None:
    path.write_text(json.dumps(bp.to_dict()), encoding="utf-8")


def load_blueprint(path: Path) -> Blueprint | None:
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("version") != BLUEPRINT_VERSION:
            return None
        d["shots"] = [Shot(**s) for s in d.get("shots", [])]
        d["texts"] = [TextCue(**t) for t in d.get("texts", [])]
        return Blueprint(**d)
    except (ValueError, TypeError):
        return None


class ShotRhythm:
    """The blueprint seen as a 'song' for the cutter's slot filler: its energy is how busy each shot is."""

    def __init__(self, bp: Blueprint) -> None:
        self.bp = bp
        durs = [s.dur for s in bp.shots] or [1.0]
        self.period = float(np.median(durs))
        self.drop = None
        self.energy = [s.motion for s in bp.shots] or [0.5]

    def mean_energy(self, a: float, b: float) -> float:
        hit = [s.motion for s in self.bp.shots if s.start < b - 1e-3 and s.start + s.dur > a + 1e-3]
        return float(np.mean(hit)) if hit else 0.5
