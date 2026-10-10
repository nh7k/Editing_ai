"""Media the tools make themselves (never the user's originals): title / intro cards, sound effects.

Everything is synthesized with FFmpeg's own sources (color, gradients, anoisesrc, sine), so there is no asset
licence to track. Files are named by a hash of their parameters: the same card is made once and reused, and a
plan that names "gen_card_…" can always be rendered again (generated again if the file was cleaned up).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..ffmpeg_utils import run_ffmpeg

BACKGROUNDS = {
    "black": "color=c=black",
    "white": "color=c=white",
    "brand": "color=c=0x1E1B4B",
    "gradient": "gradients=c0=0x1E1B4B:c1=0x7C3AED:seed=7:speed=0.01",
    "warm": "gradients=c0=0x7C2D12:c1=0xF59E0B:seed=7:speed=0.01",
}


def _name(kind: str, **params: object) -> str:
    h = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]
    return f"gen_{kind}_{h}"


def card(gen_dir: Path, w: int, h: int, dur: float, background: str, fps: int = 30) -> tuple[str, Path]:
    """A plain background clip (with silent stereo audio) the title text is drawn on."""
    if background not in BACKGROUNDS:
        raise ValueError(f"unknown card background '{background}'")
    cid = _name("card", w=w, h=h, dur=round(dur, 3), bg=background, fps=fps)
    path = gen_dir / f"{cid}.mp4"
    if not path.exists():
        gen_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.mp4")
        run_ffmpeg(["-f", "lavfi", "-i", f"{BACKGROUNDS[background]}:s={w}x{h}:r={fps}:d={dur:.3f}",
                    "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{dur:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", str(tmp)])
        tmp.replace(path)
    return cid, path


def whoosh(gen_dir: Path, dur: float = 0.45) -> Path:
    """A whoosh: pink noise through a band-pass whose centre sweeps up, with a swell-and-fade envelope."""
    path = gen_dir / f"{_name('sfx_whoosh', dur=round(dur, 3), v=3)}.wav"
    if not path.exists():
        gen_dir.mkdir(parents=True, exist_ok=True)
        d = f"{dur:.3f}"
        raw = path.with_suffix(".raw.wav")
        run_ffmpeg(["-f", "lavfi", "-i", f"anoisesrc=c=pink:r=48000:a=0.6:d={d}",
                    "-af", (f"highpass=f=300,lowpass=f=6000,"
                            f"volume='sin(PI*t/{d})^2':eval=frame,"
                            "aphaser=type=t:speed=2,"
                            f"afade=t=out:st={dur * 0.7:.3f}:d={dur * 0.3:.3f},"
                            "aformat=sample_fmts=fltp:channel_layouts=stereo"),
                    "-c:a", "pcm_s16le", str(raw)])
        # the filtered noise comes out ~ -40 dB RMS (inaudible under a voice): normalise its peak to -3 dBFS
        log = run_ffmpeg(["-i", str(raw), "-af", "volumedetect", "-f", "null", "-"])
        import re

        m = re.search(r"max_volume:\s*(-?[\d.]+) dB", log)
        gain = -3.0 - float(m.group(1)) if m else 0.0
        run_ffmpeg(["-i", str(raw), "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(path)])
        raw.unlink(missing_ok=True)
    return path


def resolve_sources(plan_sources: set[str], gen_dir: Path) -> dict[str, Path]:
    """Generated clip ids used by a plan → their files (for rendering a saved plan)."""
    return {s: gen_dir / f"{s}.mp4" for s in plan_sources if s.startswith("gen_") and (gen_dir / f"{s}.mp4").exists()}
