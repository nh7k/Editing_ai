"""Photos as clips: a JPG / PNG / WEBP becomes a still video clip, so every edit, skill and export works on it unchanged
("random car edit with 2 photos"). The photo's own resolution is kept (up to 4K on the long side), the phone's EXIF
rotation is applied, and the still is encoded near-lossless — the camera moves (push-in) are plan effects, never baked
in, so they can be changed or undone.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .ffmpeg_utils import run_ffmpeg

PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")
PHOTO_SECONDS = 5.0  # long enough for a push-in or several beat cuts; "har photo 3 sec" changes it in the edit
MAX_LONG_SIDE = 3840
FPS = 30


def is_photo(name: str | Path) -> bool:
    return Path(name).suffix.lower() in PHOTO_EXT


def photo_to_clip(src: Path, dest: Path, seconds: float = PHOTO_SECONDS) -> Path:
    """Write `dest` (.mp4): the photo, upright, even-sized, for `seconds` at 30 fps, no sound."""
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)  # a phone photo taken upright stays upright
        im = im.convert("RGB")
        w, h = im.size
        k = min(1.0, MAX_LONG_SIDE / max(w, h))
        w2, h2 = max(2, int(w * k) // 2 * 2), max(2, int(h * k) // 2 * 2)
        if (w2, h2) != (w, h):
            im = im.resize((w2, h2), Image.Resampling.LANCZOS)
        with tempfile.TemporaryDirectory() as tmp:
            still = Path(tmp) / "still.png"
            im.save(still)
            run_ffmpeg(["-loop", "1", "-framerate", str(FPS), "-i", str(still), "-t", f"{seconds:.3f}",
                        "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage", "-crf", "14",
                        "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", "-movflags", "+faststart", str(dest)])
    return dest


def is_photo_clip(path: Path) -> bool:
    """A clip made from a photo (the upload keeps the photo next to its still clip: src_x.jpg + src_x.mp4)."""
    p = Path(path)
    return p.suffix.lower() == ".mp4" and any(p.with_suffix(e).exists() for e in PHOTO_EXT)


def _detail_map(img: "Any") -> "Any":
    """Where the SUBJECT is — what an editor's close-up goes to (headlights, a grille, a wheel, a face): outlines at a
    coarse scale (fine texture such as ice cracks, grass or gravel averages out when the photo is shrunk first —
    measured: at full detail the close-ups landed on the cracked ice, not on the car) plus the brightest highlights
    (lights, chrome), with a mild centre weight."""
    import cv2
    import numpy as np

    g = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    w = 96
    small = cv2.resize(g, (w, max(2, int(w * g.shape[0] / g.shape[1]))), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 1.2)
    edges = cv2.Canny(small, 40, 120).astype(np.float32)
    dens = cv2.GaussianBlur(edges, (0, 0), sigmaX=w / 12)
    lum = small.astype(np.float32)
    hi = cv2.GaussianBlur((lum >= np.percentile(lum, 98)).astype(np.float32), (0, 0), sigmaX=w / 16)
    m = dens / (dens.max() + 1e-6) + 0.6 * hi / (hi.max() + 1e-6)
    yy, xx = np.mgrid[0:m.shape[0], 0:m.shape[1]]
    cy, cx = m.shape[0] / 2, m.shape[1] / 2
    return m * (1.0 - 0.45 * (((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / 2)


def _crop_at(w: int, h: int, cw: float, ch: float, x: float, y: float) -> tuple[int, int, int, int]:
    x0 = int(min(max(0.0, x - cw / 2), w - cw))
    y0 = int(min(max(0.0, y - ch / 2), h - ch))
    return x0, y0, int(x0 + cw), int(y0 + ch)


VIEW_SIZES = {"wide": 1.0, "medium": 0.72, "detail1": 0.5, "detail2": 0.5}


def _subject(dmap: "Any") -> tuple[int, int, int, int]:
    """The main subject in detail-map cells (x0, y0, x1, y1): the connected strong area with the most detail."""
    import cv2
    import numpy as np

    mask = (dmap >= dmap.max() * 0.45).astype(np.uint8)
    n, labels, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return 0, 0, dmap.shape[1], dmap.shape[0]
    best = max(range(1, n), key=lambda k: float(dmap[labels == k].sum()))
    x, y, bw, bh = (int(v) for v in stats[best][:4])
    return x, y, x + bw, y + bh


def _detected_subject(im: "Any") -> tuple[float, float, float, float] | None:
    """The photo's subject from the object detector (YOLOX-nano, 80 COCO classes): the biggest, surest object; one
    cut off by the frame on two sides (hands reaching in, a passer-by) counts much less. Pixels (x0, y0, x1, y1)."""
    import numpy as np

    from .tracking import detect_objects, models_available

    if not models_available()["person"]:
        return None
    try:
        found = detect_objects(np.asarray(im))
    except Exception:  # noqa: BLE001 — no detector: the edge map decides
        return None
    if not found:
        return None
    w, h = im.size

    def weight(d: tuple[float, float, float, float, float, int]) -> float:
        cx, cy, bw, bh, sc, _cls = d
        cut = sum((cx - bw / 2 < 0.01, cx + bw / 2 > 0.99, cy - bh / 2 < 0.01, cy + bh / 2 > 0.99))
        return bw * bh * sc * (0.2 if cut >= 2 else 1.0)

    cx, cy, bw, bh, _s, _c = max(found, key=weight)
    return (max(0.0, (cx - bw / 2) * w), max(0.0, (cy - bh / 2) * h), min(w, (cx + bw / 2) * w), min(h, (cy + bh / 2) * h))


def view_boxes(im: "Any", aspect: float) -> dict[str, tuple[int, int, int, int]]:
    """The crop of each shot (left, top, right, bottom) in an upright photo, for a canvas of `aspect` (w / h): the
    wide frame centred on the subject, a medium that holds the subject with some room, and two close-ups on the two
    most detailed parts INSIDE the subject (never the background texture)."""
    import numpy as np

    w, h = im.size
    dmap = _detail_map(im)
    sy, sx = h / dmap.shape[0], w / dmap.shape[1]
    ww, wh = (w, w / aspect) if w / h <= aspect else (h * aspect, h)  # the widest canvas-shaped window
    found = _detected_subject(im)
    if found is not None:
        sx0, sy0, sx1, sy1 = found
        x0, y0 = int(sx0 / sx), int(sy0 / sy)
        x1, y1 = max(x0 + 1, int(np.ceil(sx1 / sx))), max(y0 + 1, int(np.ceil(sy1 / sy)))
    else:
        x0, y0, x1, y1 = _subject(dmap)
        sx0, sy0, sx1, sy1 = x0 * sx, y0 * sy, x1 * sx, y1 * sy
    scx, scy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
    boxes = {"wide": _crop_at(w, h, ww, wh, scx, scy)}
    # medium: the subject with ~25 % room, canvas-shaped, never wider than the wide frame
    mw = min(ww, max((sx1 - sx0) * 1.25, (sy1 - sy0) * 1.25 * aspect, ww * 0.55))
    boxes["medium"] = _crop_at(w, h, mw, mw / aspect, scx, scy)
    inside = np.zeros_like(dmap)
    inside[y0:y1, x0:x1] = dmap[y0:y1, x0:x1]
    # a close-up: about half the subject's width, but never so small that it is mostly upscaled pixels
    dw = min(mw, max((sx1 - sx0) * 0.5, min(ww, 240.0)))
    py, px = np.unravel_index(int(np.argmax(inside)), inside.shape)
    boxes["detail1"] = _crop_at(w, h, dw, dw / aspect, (px + 0.5) * sx, (py + 0.5) * sy)
    yy, xx = np.mgrid[0:dmap.shape[0], 0:dmap.shape[1]]
    far = inside.copy()
    far[(np.abs((xx - px) * sx) < dw * 0.6) & (np.abs((yy - py) * sy) < dw / aspect * 0.6)] = 0
    if far.max() <= 0:  # a small subject: the other side of it
        qx, qy = (x0 + x1) - px, py
    else:
        qy, qx = np.unravel_index(int(np.argmax(far)), far.shape)
    boxes["detail2"] = _crop_at(w, h, dw, dw / aspect, (qx + 0.5) * sx, (qy + 0.5) * sy)
    return boxes


def photo_views(photo: Path, aspect: float, out_dir: Path, seconds: float = PHOTO_SECONDS) -> dict[str, Path]:
    """Shots an editor would take from one photo, framed for the canvas (aspect = width / height): `wide` (the whole
    frame that fits), `medium` and two close-ups `detail1` / `detail2` on the subject's most detailed parts
    (view_boxes). Each is a still clip; made once per photo + aspect."""
    import hashlib

    from PIL import Image, ImageOps

    st = photo.stat()
    key = hashlib.sha1(f"{photo.resolve()}|{st.st_size}|{st.st_mtime_ns}|{aspect:.4f}|v5".encode()).hexdigest()[:10]
    paths = {n: out_dir / f"gen_photoview_{key}_{n}.mp4" for n in VIEW_SIZES}
    if all(p.exists() for p in paths.values()):
        return paths
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(photo) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        boxes = view_boxes(im, aspect)
        wb = boxes["wide"]
        long_side = max(wb[2] - wb[0], wb[3] - wb[1])
        for n, box in boxes.items():
            view = im.crop(box)
            k = long_side / max(view.size)  # every view as large as the wide one (no detail is invented)
            view = view.resize((max(2, int(view.size[0] * k)), max(2, int(view.size[1] * k))), Image.Resampling.LANCZOS)
            tmp = out_dir / f"_view_{key}_{n}.png"
            view.save(tmp)
            try:
                photo_to_clip(tmp, paths[n], seconds)
            finally:
                tmp.unlink(missing_ok=True)
    return paths


def photo_original(clip: Path) -> Path | None:
    """The photo a still clip was made from (kept next to it at upload)."""
    return next((clip.with_suffix(e) for e in PHOTO_EXT if clip.with_suffix(e).exists()), None)
