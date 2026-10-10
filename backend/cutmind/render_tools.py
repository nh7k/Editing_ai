"""Renderer parts for the Tier 1 tools: the graphics track and the audio tools. Called by renderer.finish().

Other media (B-roll clips, shapes, sound pieces) are read INSIDE the filter graph with movie= / amovie= sources,
not as extra "-i" inputs: FFmpeg 9 stalled for good (frame 168 of 540, then nothing) when an extra input ended
long before the main one — measured with a 1.6 s B-roll over an 18 s edit. Sources are only read.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .plan import EditPlan, Graphic


def ff_path(p: Path) -> str:
    """A file path as a filtergraph option value (movie= / amovie=): forward slashes, escaped drive colon."""
    return "'" + p.resolve().as_posix().replace(":", "\\:").replace("'", "\\'") + "'"


def piece(src: Path, start: float, length: float, work: Path, kind: str) -> Path:
    """A short part of a source as its own file (kind "a" = WAV sound, "v" = picture only): read in the graph
    without seeking — a seek inside amovie gave timestamps that jumped 3 s and broke the whole sound track."""
    from .ffmpeg_utils import run_ffmpeg

    key = hashlib.sha1(f"{src.resolve()}|{src.stat().st_mtime_ns}|{start:.3f}|{length:.3f}|{kind}".encode()).hexdigest()[:12]
    out = work / f"piece_{key}.{'wav' if kind == 'a' else 'mp4'}"
    if not out.exists():
        work.mkdir(parents=True, exist_ok=True)
        if kind == "a":
            run_ffmpeg(["-ss", f"{start:.3f}", "-i", str(src.resolve()), "-t", f"{length:.3f}", "-vn", "-ac", "2",
                        "-ar", "48000", "-c:a", "pcm_s16le", str(out)])
        else:
            run_ffmpeg(["-ss", f"{start:.3f}", "-i", str(src.resolve()), "-t", f"{length:.3f}", "-an",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p", str(out)])
    return out


def _between(a: float, b: float) -> str:
    return f"between(t\\,{a:.3f}\\,{b:.3f})"


def _box(g: Graphic, W: int, H: int) -> tuple[int, int, int, int]:
    bw = max(2, int(round(g.w * W / 2)) * 2)
    bh = max(2, int(round(g.h * H / 2)) * 2)
    return int(round(g.x * W)), int(round(g.y * H)), bw, bh


def shape_png(kind: str, color: str, size: tuple[int, int], angle: float, work: Path) -> Path:
    """A highlight ring or arrow drawn with Pillow (own artwork, no asset licence)."""
    from PIL import Image, ImageDraw

    key = hashlib.sha1(f"{kind}{color}{size}{angle}".encode()).hexdigest()[:10]
    out = work / f"shape_{kind}_{key}.png"
    if out.exists():
        return out
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    t = max(3, int(min(w, h) * 0.06))
    if kind == "ring":
        d.ellipse([t, t, w - t, h - t], outline=(*rgb, 255), width=t)
    else:  # arrow pointing right, rotated by `angle`
        cy = h // 2
        d.rectangle([int(w * 0.08), cy - t, int(w * 0.62), cy + t], fill=(*rgb, 255))
        d.polygon([(int(w * 0.55), int(h * 0.22)), (int(w * 0.95), cy), (int(w * 0.55), int(h * 0.78))],
                  fill=(*rgb, 255))
        if angle:
            img = img.rotate(-angle, resample=Image.BICUBIC, expand=False)
    img.save(out)
    return out


def graphics_graph(plan: EditPlan, sources: dict[str, Path], base: str, W: int, H: int, total: float,
                   work: Path, project_files: Path | None = None) -> tuple[list[str], list[list[str]], str]:
    """(filter lines, extra inputs [args per input, in order], new base label)."""
    lines: list[str] = []
    inputs: list[list[str]] = []
    fps = plan.canvas.fps
    order = {"layer": 0, "blur": 1, "pixelate": 1, "light_leak": 2, "box": 3, "ring": 3, "arrow": 3, "image": 3,
             "progress": 4}
    for k, g in sorted(enumerate(plan.graphics), key=lambda kg: order[kg[1].kind]):
        x, y, bw, bh = _box(g, W, H)
        en = _between(g.start, g.end)
        lab = f"gx{k}"
        if g.kind == "layer":
            src = sources.get(g.source or "")
            if src is None:
                continue
            fit = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh}" if g.fit == "crop" else
                   f"scale={bw}:{bh}:force_original_aspect_ratio=decrease,pad={bw}:{bh}:(ow-iw)/2:(oh-ih)/2:black")
            border = ""
            if g.border > 0:
                b = max(2, int(round(g.border * min(W, H) / 2)) * 2)
                border = f",pad={bw + 2 * b}:{bh + 2 * b}:{b}:{b}:color={g.color}"
                x, y = x - b, y - b
            alpha = f",format=yuva420p,colorchannelmixer=aa={g.opacity:.3f}" if g.opacity < 1 else ""
            fade = f",fade=t=in:st=0:d=0.25:alpha=1" if g.animate == "fade" else ""
            part = piece(src, g.src_in, g.end - g.start + 0.1, work, "v")
            lines.append(f"movie={ff_path(part)},setpts=PTS-STARTPTS,fps={fps},{fit},setsar=1{border}{alpha}{fade},"
                         f"setpts=PTS-STARTPTS+{g.start:.3f}/TB[{lab}s]")
            lines.append(f"[{base}][{lab}s]overlay=x={x}:y={y}:enable='{en}':eof_action=pass:format=auto[{lab}]")
        elif g.kind in ("blur", "pixelate"):
            bw, bh = min(bw, W - max(0, x)), min(bh, H - max(0, y))
            x, y = max(0, x), max(0, y)
            if g.kind == "blur":
                # gblur blurs every plane (boxblur with luma options left the colour edges sharp)
                eff = f"gblur=sigma={max(4.0, min(bw, bh) * 0.08 * g.strength):.1f}:steps=3"
            else:
                blocks = max(2, int(min(bw, bh) / (12 / g.strength)))
                # in RGB: scaling yuv420p down to a few pixels lost the colour (yellow came out white)
                eff = (f"format=rgb24,scale={max(2, bw // blocks)}:{max(2, bh // blocks)}:flags=area,"
                       f"scale={bw}:{bh}:flags=neighbor,format=yuv420p")
            lines.append(f"[{base}]split=2[{lab}a][{lab}b]")
            lines.append(f"[{lab}b]crop={bw}:{bh}:{x}:{y},{eff}[{lab}c]")
            lines.append(f"[{lab}a][{lab}c]overlay=x={x}:y={y}:enable='{en}'[{lab}]")
        elif g.kind == "light_leak":
            d = g.end - g.start
            c0 = "0x" + g.color[1:]  # the leak's colour, a pale warm highlight and black (only the light shows)
            lines.append(f"gradients=s={W}x{H}:r={fps}:d={total + 0.2:.3f}:c0={c0}:c1=0xFFD166:c2=0x000000:"
                         f"nb_colors=3:type=radial:x0=0:y0=0:x1={int(W * 0.75)}:y1={int(H * 0.9)}:speed={0.02 * g.strength:.3f},format=gbrp[{lab}s]")
            lines.append(f"[{lab}s]fps={fps}[{lab}f]")
            lines.append(f"[{base}]format=gbrp[{lab}b]")
            # screen blend in RGB (in YUV "screen" shifts the chroma and can make it cooler), over the window only;
            # before / after the leak the picture is untouched
            lines.append(f"[{lab}b][{lab}f]blend=all_mode=screen:all_opacity={min(1.0, 0.55 * g.opacity * g.strength):.3f}:"
                         f"enable='{en}':shortest=0:repeatlast=0,format=yuv420p[{lab}]")
        elif g.kind == "box":
            t = max(3, int(min(W, H) * 0.008 * g.strength))
            lines.append(f"[{base}]drawbox=x={x}:y={y}:w={bw}:h={bh}:color={g.color}@{g.opacity:.2f}:t={t}:"
                         f"enable='{en}'[{lab}]")
        elif g.kind in ("ring", "arrow", "image"):
            if g.kind == "image":
                f = (project_files / g.source) if project_files and g.source else Path(g.source or "")
                if not f.is_file():
                    continue
            else:
                f = shape_png(g.kind, g.color, (bw, bh), g.angle, work)
            alpha = f",colorchannelmixer=aa={g.opacity:.3f}" if g.opacity < 1 else ""
            anim = ",fade=t=in:st=0:d=0.2:alpha=1" if g.animate in ("fade", "pop") else ""
            lines.append(f"movie={ff_path(f)},loop=loop=-1:size=1,fps={fps},trim=duration={g.end - g.start:.3f},"
                         f"scale={bw}:{bh}:force_original_aspect_ratio=decrease,format=rgba{alpha}{anim},"
                         f"setpts=PTS-STARTPTS+{g.start:.3f}/TB[{lab}s]")
            lines.append(f"[{base}][{lab}s]overlay=x={x}+({bw}-overlay_w)/2:y={y}+({bh}-overlay_h)/2:enable='{en}':"
                         f"eof_action=pass:format=auto[{lab}]")
        elif g.kind == "progress":
            bar_h = max(4, int(H * 0.012 * g.strength))
            yb = 0 if g.y < 0.5 else H - bar_h
            d = max(0.1, g.end - g.start)
            lines.append(f"color=c={g.color}:s={W}x{bar_h}:r={fps}:d={total + 0.1:.3f}[{lab}c]")
            # the bar slides in from the left: x = -W at the start, 0 at the end
            lines.append(f"[{base}][{lab}c]overlay=x='-{W}+{W}*min(1\\,max(0\\,(t-{g.start:.3f})/{d:.3f}))':y={yb}:"
                         f"enable='{en}':shortest=1[{lab}]")
        else:
            continue
        base = lab
    return lines, inputs, base


def audio_tool_filters(plan: EditPlan) -> list[str]:
    """Per-voice filters of the Tier 1 audio tools (in the order an engineer would chain them)."""
    a = plan.audio
    f: list[str] = []
    if a.denoise != "none":
        # spectral noise reduction, then a gate between phrases: afftdn alone took pink noise down only ~4 dB;
        # with the gate (threshold measured from the clip's own noise floor) the gaps went -40.6 → -68.9 dB
        f.append("afftdn=nr=12:nf=-40" if a.denoise == "light" else "afftdn=nr=24:nf=-35:tn=1")
        if a.gate_threshold > 0:
            rng = 0.25 if a.denoise == "light" else 0.06
            f.append(f"agate=threshold={a.gate_threshold:.4f}:ratio=8:range={rng}:attack=5:release=120")
    if a.voice_eq == "clarity":
        # rumble cut, less mud, presence lift, then tame harsh s-sounds
        f += ["highpass=f=90", "equalizer=f=280:t=q:w=1.1:g=-3", "equalizer=f=3200:t=q:w=1.0:g=4",
              "deesser=i=0.35"]
    for r in a.volume_ranges:
        f.append(f"volume=enable='{_between(r.start, r.end)}':volume={10 ** (r.gain_db / 20):.5f}")
    if a.reverb > 0:
        amt = a.reverb
        f.append(f"aecho=0.8:0.85:45|85|130|190:{0.4 * amt:.3f}|{0.3 * amt:.3f}|{0.22 * amt:.3f}|{0.15 * amt:.3f}")
    return f


def audio_edit_graph(plan: EditPlan, sources: dict[str, Path], voice: str,
                     work: Path | None = None) -> tuple[list[str], list[list[str]], str]:
    """J / L cuts: the main sound is muted over the overlap window and the other shot's real sound (read from its
    source, sped like its shot) is laid in. Returns (lines, inputs [{AUX n}], new voice label)."""
    if not plan.audio_edits:
        return [], [], voice
    tl = plan.timeline()
    lines: list[str] = []
    inputs: list[list[str]] = []
    mutes: list[str] = []
    pieces: list[str] = []
    for k, e in enumerate(plan.audio_edits):
        if e.after + 1 >= len(tl):
            continue
        a, b = tl[e.after], tl[e.after + 1]
        cut = b.start
        if e.kind == "j":
            seg, src_from = b.segment, b.segment.in_ - e.seconds * b.segment.speed
            at = cut - e.seconds
        else:
            seg, src_from = a.segment, a.segment.out
            at = cut
        src = sources.get(seg.source)
        if src is None or src_from < 0:
            continue
        tempo = []
        sp = seg.speed
        while sp > 2.0 + 1e-9:
            tempo.append("atempo=2.0")
            sp /= 2.0
        while sp < 0.5 - 1e-9:
            tempo.append("atempo=0.5")
            sp /= 0.5
        if abs(sp - 1.0) > 1e-6:
            tempo.append(f"atempo={sp:.4f}")
        d = e.seconds
        # timestamps first: after a seek they start at the seek point and atrim counts from 0
        chain = ",".join(["asetpts=PTS-STARTPTS", f"atrim=duration={e.seconds * seg.speed + 0.05:.3f}", *tempo,
                          "aresample=48000",
                          "aformat=sample_fmts=fltp:channel_layouts=stereo", f"atrim=0:{d:.3f}",
                          f"afade=t=in:st=0:d=0.02", f"afade=t=out:st={max(0.0, d - 0.02):.3f}:d=0.02",
                          f"volume={seg.volume:.3f}", f"adelay={int(round(at * 1000))}:all=1"])
        part = piece(src, src_from, e.seconds * seg.speed + 0.05, work or Path("."), "a")
        lines.append(f"amovie={ff_path(part)},{chain}[je{k}]")
        pieces.append(f"[je{k}]")
        mutes.append(f"volume=enable='{_between(at, at + d)}':volume=0")
    if not pieces:
        return [], [], voice
    lines.append(f"[{voice}]" + ",".join(mutes) + "[jmain]")
    lines.append(f"[jmain]{''.join(pieces)}amix=inputs={len(pieces) + 1}:duration=first:normalize=0[jout]")
    return lines, inputs, "jout"


def sfx_graph(plan: EditPlan, gen_dir: Path, total: float) -> tuple[list[str], list[list[str]], str | None]:
    """Whoosh / pop sound effects at their times, mixed into one track (or None)."""
    from .tools.generated import whoosh

    items = [s for s in plan.audio.sfx if s.at < total]
    if not items:
        return [], [], None
    f = whoosh(gen_dir)
    lines: list[str] = []
    inputs: list[list[str]] = []
    lines.append(f"amovie={ff_path(f)},aformat=sample_fmts=fltp:channel_layouts=stereo,asplit={len(items)}"
                 + "".join(f"[sx{k}]" for k in range(len(items))))
    outs = []
    for k, s in enumerate(items):
        # the whoosh is centred on its time (it swells into the cut)
        start = max(0.0, s.at - 0.2)
        lines.append(f"[sx{k}]volume={s.volume:.3f},adelay={int(round(start * 1000))}:all=1[sy{k}]")
        outs.append(f"[sy{k}]")
    # apad=whole_dur, not "apad,atrim": after adelay, atrim silenced the whole effect (measured -91 dB)
    lines.append(f"{''.join(outs)}amix=inputs={len(outs)}:duration=longest:normalize=0,"
                 f"apad=whole_dur={total:.3f}[sfxmix]")
    return lines, inputs, "sfxmix"


def db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-9))
