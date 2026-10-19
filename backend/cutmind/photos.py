"""Photos as clips: a JPG / PNG / WEBP becomes a still video clip, so every edit, skill and export works on it unchanged
("random car edit with 2 photos"). The photo's own resolution is kept (up to 4K on the long side), the phone's EXIF
rotation is applied, and the still is encoded near-lossless — the camera moves (push-in) are plan effects, never baked
in, so they can be changed or undone.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

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
