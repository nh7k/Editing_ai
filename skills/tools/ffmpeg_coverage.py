"""Phase 1.1 of the catalog brief: every FFmpeg filter on this machine, classified as used (named in our code),
planned (a Tier 2/3 idea with a reason) or not applicable (plumbing, hardware, analysis-only, legacy). Writes the
filter section of docs/COVERAGE_MATRIX.md (the editor feature matrix is written by hand below it).

    backend/.venv/Scripts/python.exe skills/tools/ffmpeg_coverage.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from cutmind.ffmpeg_utils import ffmpeg_bin  # noqa: E402

NA = re.compile(r"^(?:a?null|a?nullsink|a?nullsrc|a?format|a?resample|a?setpts|a?settb|a?split|a?select|a?sendcmd|"
                r"abuffer\w*|buffer\w*|.*_(?:cuda|opencl|vaapi|qsv|vulkan|npp|cuvid|d3d11|d3d12|videotoolbox|amf)|"
                r"hw\w+|copy|fifo|afifo|setdar|setsar|setparams|setfield|showinfo|ashowinfo|showspectrum\w*|show\w+|"
                r"a?metadata|a?perms|a?realtime|a?interleave|a?segment|a?latency|graphmonitor|a?bench|"
                r"ebur128|astats|volumedetect|silencedetect|blackdetect|freezedetect|scdet|cropdetect|idet|"
                r"signalstats|ssim|psnr|vmaf\w*|identity|msad|corr|entropy|bitplanenoise|readeia608|readvitc|"
                r"sidedata|asidedata|a?drawgraph|qp|codecview|a?loop|trim|atrim|concat|ainterleave)$")
PLANNED = {  # filter: (tier-2/3 idea, why not yet)
    "chromakey": "green-screen key (needs a background plate UI)", "colorkey": "keying", "despill": "keying",
    "lumakey": "keying", "vidstabdetect": "GPL — never (deshake instead)", "vidstabtransform": "GPL — never",
    "minterpolate": "smooth slow motion (very slow on CPU)", "framerate": "frame blending slow motion",
    "tmix": "motion blur / echo (Tier 3 style)", "lenscorrection": "fix GoPro barrel distortion",
    "v360": "360° video reframing", "perspective": "GPL-only filter — keystone fix", "rubberband": "pitch shift (librubberband GPL)",
    "asetrate": "voice pitch effect", "afreqshift": "voice effect", "aphaser": "audio phaser effect", "flanger": "audio effect",
    "chorus": "audio effect", "dynaudnorm": "dialogue levelling", "speechnorm": "speech levelling", "compand": "compressor",
    "acompressor": "compressor (used inside loudness correction)", "superequalizer": "music EQ", "afir": "convolution reverb",
    "subtitles": "used (libass)", "ass": "used via subtitles", "drawtext": "simple text without libass",
    "zoompan": "Ken Burns on stills (we use keyframed crop instead)", "tpad": "used (freeze)", "loop": "loops",
    "palettegen": "used (GIF)", "paletteuse": "used (GIF)", "xstack": "multi-video grid (split screen 3+)",
    "hstack": "side by side", "vstack": "stacked", "lut1d": "1D curves", "colorbalance": "lift/gamma/gain wheels",
    "colorcorrect": "colour wheels", "selectivecolor": "HSL secondary", "huesaturation": "HSL", "vibrance": "vibrance",
    "exposure": "exposure stops", "colortemperature": "used", "unsharp": "used", "cas": "contrast-adaptive sharpen",
    "deband": "banding fix", "deflicker": "timelapse flicker fix", "removegrain": "denoise", "nlmeans": "video denoise (slow)",
    "atadenoise": "video denoise", "bm3d": "video denoise (very slow)", "afftdn": "used", "anlmdn": "audio denoise",
    "arnndn": "used (model licence BLOCKED)", "deesser": "used", "silenceremove": "alternative to our cut list",
    "showwaves": "waveform visual (music videos)", "showcqt": "music visualiser", "avectorscope": "visualiser",
}


def main() -> None:
    out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        m = re.match(r"^\s*[T.][S.][C.]?\s+(\S+)\s+(\S+->\S+)\s+(.*)$", line)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3).strip()))
    lines_of_code = [ln for p in (ROOT / "backend" / "cutmind").rglob("*.py")
                     for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                     if not ln.lstrip().startswith("#")]
    graph_line = re.compile(r"filter|graph|chain|\"-af\"|\"-vf\"|\"-i\"|lavfi|out\.append|lines\.append|\+=|\breturn \[")

    def is_used(name: str) -> bool:
        """Named where a filter goes: "name=…" inside a string, or the bare name between filter-chain separators
        on a line that builds a filter graph. A word in a Hinglish list ("aap", "sab") is not a use."""
        n = re.escape(name)
        for ln in lines_of_code:
            if re.search(rf"[\"',\];\[]{n}=", ln):
                return True
            if graph_line.search(ln) and re.search(rf"[\"',\]][\s]*{n}[\"',\[]", ln):
                return True
        return False
    used, planned, na, other = [], [], [], []
    for name, io, desc in rows:
        if name not in ("null",) and is_used(name):
            used.append((name, io, desc))
        elif name in PLANNED:
            planned.append((name, io, desc, PLANNED[name]))
        elif NA.match(name):
            na.append((name, io, desc))
        else:
            other.append((name, io, desc))
    lines = [
        "## A. FFmpeg filters on this machine (generated — `skills/tools/ffmpeg_coverage.py`)",
        "",
        f"FFmpeg 9.0.1 (gyan.dev essentials build), {len(rows)} filters, enumerated with `ffmpeg -filters` on 2026-10-09.",
        f"**Used** (named in `backend/cutmind`): {len(used)} · **planned** (a later tier, with a reason): {len(planned)} · "
        f"**not applicable** (plumbing / hardware / analysis-only): {len(na)} · **not reviewed yet**: {len(other)}.",
        "",
        "### Used", "", "| filter | type | what |", "|---|---|---|",
    ]
    lines += [f"| `{n}` | {io} | {d} |" for n, io, d in used]
    lines += ["", "### Planned", "", "| filter | type | idea / reason |", "|---|---|---|"]
    lines += [f"| `{n}` | {io} | {why} |" for n, io, d, why in planned]
    lines += ["", "### Not applicable", "", ", ".join(f"`{n}`" for n, _, _ in na), "",
              "### Not reviewed yet (honest: no decision made for these)", "", ", ".join(f"`{n}`" for n, _, _ in other), ""]
    doc = ROOT / "docs" / "COVERAGE_MATRIX.md"
    head = doc.read_text(encoding="utf-8").split("## A. FFmpeg filters")[0] if doc.exists() else (
        "# Coverage matrix\n\nPart of the catalog brief. Section A is generated; section B (editors' features → skill id → "
        "status) is written by hand and is NOT complete yet (see docs/CATALOG_REVIEW.md).\n\n")
    doc.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} filters: used {len(used)}, planned {len(planned)}, n/a {len(na)}, not reviewed {len(other)}")


if __name__ == "__main__":
    main()
