"""CutMind FX catalog — every effect, motion, transition, colour look and text animation in one registry.

Everything here is built from FFmpeg's own filters (LGPL/GPL FFmpeg is called as an external program) or is our
own work (the LUTs below are generated mathematically by `cutmind.luts`). Each entry carries English + Hinglish
keywords so the prompt parser can find it, and a recipe the renderer turns into an FFmpeg filter chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

Category = Literal["motion", "video_effect", "transition", "color", "text_animation"]


@dataclass(frozen=True)
class FxContext:
    w: int
    h: int
    duration: float   # output duration of the segment (s)
    fps: int
    strength: float = 1.0
    times: tuple[float, ...] = ()  # beat times inside this segment (s), when the effect follows the music
    params: dict = field(default_factory=dict)  # Tier 1 parametric effects (grade / crop / censor …)


@dataclass(frozen=True)
class FX:
    id: str
    name: str
    category: Category
    description: str
    keywords: tuple[str, ...] = ()                       # regexes (lower-case prompt)
    build: Callable[[FxContext], list[str]] | None = None  # filter chain for motion / video effects
    xfade: str | None = None                              # FFmpeg xfade transition name
    # transitions only: extra filters over the transition window (start, end) — the whip's motion blur, the glitch
    post: Callable[[float, float], list[str]] | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


def _f(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------------------------------------
# Motion (camera-like moves)
# ---------------------------------------------------------------------------------------------------------
def _zoom(direction: int) -> Callable[[FxContext], list[str]]:
    def build(c: FxContext) -> list[str]:
        z = 0.12 * c.strength
        d = max(c.duration, 0.1)
        # zoom in: 1 → 1+z ; zoom out: 1+z → 1 — about the centre (zoompan; a per-frame scale + crop drifted
        # towards a corner: measured 5 % of the frame over a 3 s zoom)
        from .camera_move import replay_filters

        path = [[0.0, 1.0, 0, 0, 0], [d, 1 + z, 0, 0, 0]] if direction > 0 else [[0.0, 1 + z, 0, 0, 0], [d, 1.0, 0, 0, 0]]
        return replay_filters(path, c.w, c.h, d, fps=c.fps)
    return build


def _pan(dx: int, dy: int) -> Callable[[FxContext], list[str]]:
    def build(c: FxContext) -> list[str]:
        m = 0.12 * c.strength  # how far we travel (as a share of the frame)
        d = max(c.duration, 0.1)
        sw, sh = int(c.w * (1 + m)) // 2 * 2, int(c.h * (1 + m)) // 2 * 2
        ex, ey = sw - c.w, sh - c.h
        x = f"{ex}*t/{_f(d)}" if dx > 0 else (f"{ex}*(1-t/{_f(d)})" if dx < 0 else f"{ex // 2}")
        y = f"{ey}*t/{_f(d)}" if dy > 0 else (f"{ey}*(1-t/{_f(d)})" if dy < 0 else f"{ey // 2}")
        return [f"scale={sw}:{sh}", f"crop={c.w}:{c.h}:x='{x}':y='{y}'"]
    return build


def _shake(c: FxContext) -> list[str]:
    a = max(2, int(round(min(c.w, c.h) * 0.012 * c.strength)))
    return [f"crop={c.w - 2 * a}:{c.h - 2 * a}:x='{a}+{a}*sin(t*23)':y='{a}+{a}*cos(t*17)'", f"scale={c.w}:{c.h}"]


def _beat_shake(c: FxContext) -> list[str]:
    """Short camera-shake bursts at given times (the drop): ±a px, decaying over ~0.35 s."""
    if not c.times:
        return _shake(c)
    a = max(3, int(round(min(c.w, c.h) * 0.025 * c.strength)))
    env = "+".join(f"if(between(t,{_f(b)},{_f(b + 0.4)}),exp(-(t-{_f(b)})/0.12),0)" for b in c.times[:20])
    return [f"crop={c.w - 2 * a}:{c.h - 2 * a}:x='{a}+{a}*min(1,{env})*sin(t*61)':y='{a}+{a}*min(1,{env})*cos(t*47)'",
            f"scale={c.w}:{c.h}"]


def _swing(c: FxContext) -> list[str]:
    ang = 0.035 * c.strength
    return [f"scale=w={int(c.w * 1.08) // 2 * 2}:h={int(c.h * 1.08) // 2 * 2}",
            f"rotate=a='{_f(ang)}*sin(2*PI*t/2.2)':ow={c.w}:oh={c.h}:c=black"]


PULSE_DECAY = 0.18  # s: how long each beat "punch" takes to settle


PUNCH_ATTACK, PUNCH_TAU = 0.04, 0.13  # s: a 1-frame snap to the peak, then a fast exponential settle


def _pulse(c: FxContext) -> list[str]:
    if c.times:
        # a beat PUNCH: snaps to the peak in ~1 frame (the time given is already a frame before the beat), then
        # settles fast — a slow 0.36 s triangle of 7 % was invisible on real footage (2 of 23 beats measured as
        # hits, tools/beatcheck.py). params["amps"]: one size per hit (bigger on the drop / hard kicks)
        raw = c.params.get("amps") or ""
        amps = [float(x) for x in str(raw).split(",") if x.strip()] if raw else []
        z = 0.11 * c.strength
        parts = []
        for k, b in enumerate(c.times[:120]):
            a = float(amps[k]) if k < len(amps) else 1.0
            parts.append(f"{_f(a)}*if(between(t,{_f(b - PUNCH_ATTACK)},{_f(b + 0.6)}),"
                         f"if(lt(t,{_f(b)}),(t-{_f(b - PUNCH_ATTACK)})/{_f(PUNCH_ATTACK)},exp(-(t-{_f(b)})/{_f(PUNCH_TAU)})),0)")
        f = f"(1+{_f(z)}*min(1.6,{'+'.join(parts)}))"
    else:
        z = 0.05 * c.strength
        f = f"(1+{_f(z)}*(0.5+0.5*sin(2*PI*t*2)))"  # no beat grid: 2 pulses per second
    return [f"scale=w='trunc({c.w}*{f}/2)*2':h='trunc({c.h}*{f}/2)*2':eval=frame", f"crop={c.w}:{c.h}"]


def _tilt(c: FxContext) -> list[str]:
    """A still tilt ("thoda ghumao", dutch angle): rotate by params["angle"] degrees and zoom just enough that no
    black corner shows (a frame rotated by θ is covered when scaled by cos θ + sin θ · long/short side)."""
    import math

    ang = max(-45.0, min(45.0, float(c.params.get("angle", 5.0 * c.strength))))
    a = math.radians(abs(ang))
    s = math.cos(a) + math.sin(a) * max(c.w / c.h, c.h / c.w)
    sw, sh = int(c.w * s + 2) // 2 * 2, int(c.h * s + 2) // 2 * 2
    return [f"scale=w={sw}:h={sh}", f"rotate=a={_f(math.radians(ang))}:ow={c.w}:oh={c.h}:c=black"]


def _slow_rotate(c: FxContext) -> list[str]:
    return [f"scale=w={int(c.w * 1.15) // 2 * 2}:h={int(c.h * 1.15) // 2 * 2}",
            f"rotate=a='{_f(0.02 * c.strength)}*t':ow={c.w}:oh={c.h}:c=black"]


# ---------------------------------------------------------------------------------------------------------
# Video effects (CapCut-style looks), all single-input FFmpeg filter chains
# ---------------------------------------------------------------------------------------------------------
def _c(*filters: str) -> Callable[[FxContext], list[str]]:
    return lambda c: list(filters)


def _grade(c: FxContext) -> list[str]:
    """Tier 1 colour on any part of the video: eq (brightness / contrast / saturation / gamma), colour
    temperature (warmth), then a look LUT at a strength (luts.ensure_look; lut3d runs with cwd = LUT_DIR)."""
    p = c.params
    out: list[str] = []
    b, ct = float(p.get("brightness", 0.0)), float(p.get("contrast", 1.0))
    sa, ga = float(p.get("saturation", 1.0)), float(p.get("gamma", 1.0))
    if abs(b) > 1e-3 or abs(ct - 1) > 1e-3 or abs(sa - 1) > 1e-3 or abs(ga - 1) > 1e-3:
        out.append(f"eq=brightness={b:.3f}:contrast={ct:.3f}:saturation={sa:.3f}:gamma={ga:.3f}")
    wm = float(p.get("warmth", 0.0))
    if abs(wm) > 1e-3:
        out.append(f"colortemperature=temperature={int(6500 - wm * 3000)}:mix=1")
    look = p.get("look")
    if look:
        from .luts import ensure_look

        out.append(f"lut3d=file={ensure_look(str(look), float(p.get('look_strength', 1.0)))}")
    return out


def _crop(c: FxContext) -> list[str]:
    """Tier 1 crop: params x, y, w, h as shares of the frame, scaled back up to the canvas."""
    x, y = float(c.params.get("x", 0.0)), float(c.params.get("y", 0.0))
    w, h = float(c.params.get("w", 1.0)), float(c.params.get("h", 1.0))
    return [f"crop=iw*{_f(w)}:ih*{_f(h)}:iw*{_f(x)}:ih*{_f(y)}", f"scale={c.w}:{c.h}", "setsar=1"]


def _glitch(c: FxContext) -> list[str]:
    s = int(round(8 * c.strength))
    # RGB split that jitters, plus noise bursts every ~0.7 s
    return [f"rgbashift=rh=-{s}:bh={s}:rv=2:bv=-2", "noise=alls=22:allf=t",
            "eq=brightness='0.06*gt(mod(t,0.7),0.62)':eval=frame"]


def _vhs(c: FxContext) -> list[str]:
    return ["chromashift=cbh=6:crh=-6", "curves=preset=vintage", "eq=saturation=1.25:contrast=1.05",
            "noise=alls=20:allf=t+u", "drawgrid=w=iw:h=4:t=1:c=black@0.22"]


def _old_film(c: FxContext) -> list[str]:
    return ["curves=preset=vintage", "noise=alls=30:allf=t", "eq=brightness='0.04*sin(t*37)':saturation=0.7:eval=frame",
            "vignette=angle=0.6"]


def _mirror(c: FxContext) -> list[str]:
    if c.params.get("axis") == "v":  # top half mirrored onto the bottom
        y = "if(lt(Y,H/2),Y,H-1-Y)"
        return [f"geq=lum='lum(X,{y})':cb='cb(X,{y})':cr='cr(X,{y})'"]
    return ["geq=lum='lum(if(lt(X,W/2),X,W-1-X),Y)':cb='cb(if(lt(X,W/2),X,W-1-X),Y)':cr='cr(if(lt(X,W/2),X,W-1-X),Y)'"]


def _kaleido(c: FxContext) -> list[str]:
    x = "if(lt(X,W/2),X,W-1-X)"
    y = "if(lt(Y,H/2),Y,H-1-Y)"
    return [f"geq=lum='lum({x},{y})':cb='cb({x},{y})':cr='cr({x},{y})'"]


def _flash(c: FxContext) -> list[str]:
    if c.times:  # Tier 1: a white flash at each given time (beats, cuts, moments), 0.25 s each
        bumps = "+".join(f"max(0,1-abs(t-{_f(b)})/0.12)" for b in c.times[:40])
        return [f"eq=brightness='min(0.9,{_f(0.9 * c.strength)}*({bumps}))':eval=frame"]
    return ["fade=t=in:st=0:d=0.3:color=white"]


def _strobe(c: FxContext) -> list[str]:
    return ["eq=brightness='0.25*gt(mod(t,0.25),0.2)':eval=frame"]


def _letterbox(c: FxContext) -> list[str]:
    # params["ratio"] (Tier 1): bars that leave a ratio:1 picture (2.39 = scope), else 10 % bars
    ratio = float(c.params.get("ratio", 0) or 0)
    bar = int(max(0.0, (c.h - c.w / ratio) / 2)) if ratio else int(c.h * 0.1)
    return [f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill", f"drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill"]


def _duotone(c1: str, c2: str) -> Callable[[FxContext], list[str]]:
    # luma → gradient between two colours (shadows c1, highlights c2)
    def comp(hexc: str, i: int) -> int:
        return int(hexc[1 + 2 * i: 3 + 2 * i], 16)

    def build(c: FxContext) -> list[str]:
        r = f"{comp(c1, 0)}+({comp(c2, 0)}-{comp(c1, 0)})*val/255"
        g = f"{comp(c1, 1)}+({comp(c2, 1)}-{comp(c1, 1)})*val/255"
        b = f"{comp(c1, 2)}+({comp(c2, 2)}-{comp(c1, 2)})*val/255"
        return ["format=rgb24", "hue=s=0", f"lutrgb=r='{r}':g='{g}':b='{b}'"]
    return build


_REGISTRY: list[FX] = [
    # --- motion ---
    FX("zoom", "Zoom In", "motion", "slow push-in", (r"zoom.?in", r"zoom effect", r"ken burns", r"punch.?in", r"\bzooms?\b(?! transition| out)"),
       _zoom(+1)),
    FX("zoom_out", "Zoom Out", "motion", "slow pull-out", (r"zoom.?out", r"pull.?out"), _zoom(-1)),
    FX("pan_left", "Pan Left", "motion", "camera slides to the left", (r"pan(ning)? left",), _pan(-1, 0)),
    FX("pan_right", "Pan Right", "motion", "camera slides to the right", (r"pan(ning)? right", r"\bpan\b(?! left| up| down)"),
       _pan(+1, 0)),
    FX("pan_up", "Pan Up", "motion", "tilt up", (r"pan up", r"tilt up"), _pan(0, -1)),
    FX("pan_down", "Pan Down", "motion", "tilt down", (r"pan down", r"tilt down"), _pan(0, +1)),
    FX("shake", "Camera Shake", "motion", "handheld shake", (r"shake", r"handheld", r"jhatk"), _shake),
    FX("swing", "Swing", "motion", "gentle left-right tilt", (r"swing", r"sway", r"jhool"), _swing),
    FX("beat_shake", "Beat Shake", "motion", "short shake bursts on chosen beats (the drop)", (), _beat_shake),
    FX("pulse", "Beat Pulse", "motion", "zoom punch on every music beat", (
        r"pulse", r"beat (zoom|punch|bounce|shake|drop)", r"bounce zoom", r"(zoom|punch|jhatka|shake|bounce) (on|with|pe|par) (the |har )?beats?",
        r"\bbeats? (ke |ki )?(pe|par|on|saath|sath|hisaab se) (\w+ ){0,2}(zoom|punch|jhatka|shake|bounce|effects?|animations?|motion)",
        r"\bbass\b", r"\bba(s|se)\s+(ki tarah|jaisa|jaise|wala|wali|effect|boost|drop|heavy)", r"dhamak", r"\bthump",
        r"(sound|music|gaana|video) (bhi )?beat (kare|pe)", r"beat ke saath (hil|naach|jump)"), _pulse),
    FX("tilt", "Tilt", "motion", "a still tilted frame (dutch angle)", (r"\btilt", r"dutch angle"), _tilt),
    FX("rotate_slow", "Slow Spin", "motion", "slowly rotating frame", (r"\bspin(ning)?\b(?! (text|title|in\b))", r"slow(ly)? rotat"), _slow_rotate),
    # --- video effects ---
    FX("vignette", "Vignette", "video_effect", "darker edges", (r"vignette", r"dark (edges|corners)"),
       lambda c: [f"vignette=angle={min(0.9, 0.45 * c.strength):.3f}"]),
    FX("sharpen", "Sharpen", "video_effect", "crisper detail", (r"sharpen", r"sharper", r"\bcrisp"),
       lambda c: [f"unsharp=5:5:{min(2.5, 0.9 * c.strength):.2f}:5:5:0"]),
    FX("blur", "Blur", "video_effect", "soft focus", (r"\bblur(red|ry)?\b(?!.{0,6}(background|bg))", r"soft focus", r"dhundh"),
       lambda c: [f"boxblur={max(1, int(round(4 * c.strength)))}:1"]),
    FX("glitch", "Glitch", "video_effect", "digital RGB glitch with noise bursts", (r"glitch", r"distort"), _glitch),
    FX("rgb_split", "RGB Split", "video_effect", "red/blue channels pulled apart", (r"rgb split", r"chromatic", r"aberration"),
       lambda c: [f"rgbashift=rh=-{int(8 * c.strength)}:bh={int(8 * c.strength)}"]),
    FX("vhs", "VHS", "video_effect", "retro tape: colour bleed, noise, scanlines", (r"\bvhs\b", r"\btape\b", r"camcorder", r"90s"), _vhs),
    FX("film_grain", "Film Grain", "video_effect", "analogue grain", (r"grain", r"\bgrainy"),
       lambda c: [f"noise=alls={int(16 * c.strength)}:allf=t"]),
    FX("old_film", "Old Film", "video_effect", "faded, flickering old movie", (r"old film", r"old movie", r"purani film", r"flicker"), _old_film),
    FX("scanlines", "Scanlines", "video_effect", "CRT lines", (r"scan.?lines", r"\bcrt\b"), _c("drawgrid=w=iw:h=3:t=1:c=black@0.3")),
    FX("flash", "Flash", "video_effect", "white flash at the start of each shot", (r"\bflash", r"white flash", r"chamak"), _flash),
    FX("strobe", "Strobe", "video_effect", "rhythmic brightness flicker", (r"strobe", r"party lights?"), _strobe),
    FX("mirror", "Mirror", "video_effect", "left half mirrored", (r"mirror effect", r"mirrored", r"symmetr"), _mirror),
    FX("kaleidoscope", "Kaleidoscope", "video_effect", "four-way mirror", (r"kaleido",), _kaleido),
    FX("pixelate", "Pixelate", "video_effect", "big blocky pixels", (r"pixel(ate|ated|ize)(?!d? transition)", r"8.?bit", r"censor"),
       lambda c: [f"pixelize=w={int(12 * c.strength)}:h={int(12 * c.strength)}"]),
    FX("posterize", "Posterize", "video_effect", "flat comic colours", (r"posteri[sz]e", r"comic", r"cartoon"),
       _c("lutrgb=r='floor(val/48)*48':g='floor(val/48)*48':b='floor(val/48)*48'")),
    FX("negative", "Negative", "video_effect", "inverted colours", (r"negative(?! (b ?& ?w|black))", r"invert(?!(ed)? (b ?& ?w|black))"),
       _c("negate")),
    FX("color_pop", "Colour Pop", "video_effect", "everything grey except red tones", (r"colou?r pop", r"color splash", r"only red"),
       lambda c: [f"colorhold=color={c.params.get('color', 'red')}:similarity={0.3 * c.strength:.3f}:blend=0.1"]),
    FX("ghost_trail", "Ghost Trail", "video_effect", "motion leaves glowing trails", (r"ghost", r"\btrails?\b", r"afterimage"),
       lambda c: [f"lagfun=decay={min(0.98, 0.9 + 0.04 * c.strength):.3f}"]),
    FX("echo", "Echo", "video_effect", "frames blended together (motion echo)", (r"\becho\b", r"motion blur"),
       _c("tmix=frames=5:weights='1 1 1 1 1'")),
    FX("fisheye", "Fisheye", "video_effect", "bulging lens", (r"fish.?eye", r"bulge", r"wide lens"),
       lambda c: [f"lenscorrection=k1={-0.25 * c.strength:.3f}:k2=-0.05"]),
    FX("dreamy", "Dreamy Glow", "video_effect", "soft glowing highlights", (r"dream", r"glowy", r"soft glow", r"ethereal"),
       _c("unsharp=13:13:-1.2:13:13:0", "eq=brightness=0.04:saturation=0.9:gamma=1.1")),
    FX("neon_edges", "Neon Edges", "video_effect", "glowing outlines", (r"neon (edges|outline)", r"outline", r"edge glow"),
       _c("edgedetect=mode=colormix:high=0.12:low=0.04", "eq=saturation=1.8:brightness=0.05")),
    FX("sketch", "Sketch", "video_effect", "pencil drawing", (r"sketch", r"drawing", r"pencil"),
       _c("edgedetect=low=0.08:high=0.25", "negate")),
    FX("thermal", "Thermal", "video_effect", "heat-camera colours", (r"thermal", r"heat (map|camera)", r"infrared"),
       _c("hue=s=0", "pseudocolor=p=turbo")),
    FX("night_vision", "Night Vision", "video_effect", "green night-vision", (r"night vision",),
       _c("hue=s=0", "colorchannelmixer=.2:.2:.2:0:.5:1.1:.5:0:.2:.2:.2", "noise=alls=25:allf=t", "vignette")),
    FX("grade", "Colour grade", "video_effect", "brightness / contrast / saturation / warmth / look on a part",
       (), _grade),
    FX("stabilize", "Stabilise", "video_effect", "steadier handheld footage (deshake)", (r"stabili[sz]e",),
       lambda c: [f"deshake=rx={min(64, int(16 * c.strength)) // 16 * 16 or 16}:ry={min(64, int(16 * c.strength)) // 16 * 16 or 16}:edge=mirror",
                  f"crop=iw*{_f(1 - 0.04 * c.strength)}:ih*{_f(1 - 0.04 * c.strength)}", f"scale={c.w}:{c.h}"]),
    FX("crop", "Crop", "video_effect", "a part of the picture, enlarged", (r"\bcrop\b",), _crop),
    FX("letterbox", "Cinema Bars", "video_effect", "black bars top and bottom", (r"letterbox", r"cinema(tic)? bars", r"black bars"),
       _letterbox),
    FX("duotone_blue_pink", "Duotone Blue/Pink", "video_effect", "two-colour poster look", (r"duotone", r"two.?tone"),
       _duotone("#1E1B4B", "#F472B6")),
    FX("duotone_teal_gold", "Duotone Teal/Gold", "video_effect", "teal shadows, gold highlights", (r"teal (and|&) gold",),
       _duotone("#064E3B", "#FBBF24")),
]

# --- transitions: our 4 classic names + every FFmpeg xfade transition -------------------------------------
_XFADE = ("fade wipeleft wiperight wipeup wipedown slideleft slideright slideup slidedown circlecrop rectcrop distance "
          "fadeblack fadewhite radial smoothleft smoothright smoothup smoothdown circleopen circleclose vertopen "
          "vertclose horzopen horzclose dissolve pixelize diagtl diagtr diagbl diagbr hlslice hrslice vuslice vdslice "
          "hblur fadegrays wipetl wipetr wipebl wipebr squeezeh squeezev zoomin fadefast fadeslow hlwind hrwind vuwind "
          "vdwind coverleft coverright coverup coverdown revealleft revealright revealup revealdown").split()
_TRANSITION_WORDS = {
    "slideleft": (r"slide (to the )?left", r"\bslides?\b"), "slideup": (r"slide up",), "circleopen": (r"circle", r"iris"),
    "pixelize": (r"pixel\w* transition",), "radial": (r"radial", r"clock wipe"), "hblur": (r"blur transition",),
    "fadewhite": (r"white (fade|flash) transition", r"dip to white"), "squeezeh": (r"squeeze",),
    "hlwind": (r"wind",), "coverleft": (r"cover transition",), "revealleft": (r"reveal",), "diagtl": (r"diagonal",),
    "dissolve": (r"pixel dissolve",), "vertopen": (r"door", r"split open"), "smoothleft": (r"smooth (slide|transition)",),
    "fadegrays": (r"grey fade", r"gray fade"),
}
_CLASSIC = [
    FX("fade", "Fade through black", "transition", "dip to black between shots", (), xfade="fadeblack"),
    FX("crossfade", "Crossfade", "transition", "soft blend between shots", (), xfade="fade"),
    FX("zoom", "Zoom transition", "transition", "zoom into the next shot", (), xfade="zoomin"),
    FX("wipe", "Wipe", "transition", "wipe to the left", (), xfade="wipeleft"),
]
def _whip_blur(a: float, b: float) -> list[str]:
    """A whip pan is a slide that smears sideways: strong horizontal blur over the transition only."""
    return [f"gblur=sigma=22:sigmaV=0.6:steps=2:enable='between(t,{_f(a)},{_f(b)})'"]


def _glitch_hit(a: float, b: float) -> list[str]:
    """Digital break-up over the transition: RGB channels torn apart + noise, only inside the window."""
    return [f"rgbashift=rh=-14:bh=14:gv=6:enable='between(t,{_f(a)},{_f(b)})'",
            f"noise=alls=40:allf=t:enable='between(t,{_f(a)},{_f(b)})'"]


_CLASSIC += [
    FX("whip", "Whip pan (left)", "transition", "fast slide with motion blur", (r"whip",), xfade="slideleft", post=_whip_blur),
    FX("whip_right", "Whip pan (right)", "transition", "fast slide right with motion blur", (), xfade="slideright",
       post=_whip_blur),
    FX("glitch_cut", "Glitch transition", "transition", "pixels + RGB tear between shots", (r"glitch (cut|transition)",),
       xfade="pixelize", post=_glitch_hit),
]
_REGISTRY_T = _CLASSIC + [FX(n, n, "transition", f"FFmpeg xfade '{n}'", _TRANSITION_WORDS.get(n, ()), xfade=n)
                          for n in _XFADE if n not in ("fade", "zoomin", "wipeleft", "fadeblack")]

# --- colour looks generated by cutmind.luts (our own .cube files) ----------------------------------------
LUT_LOOKS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "teal_orange": ("Teal & Orange", "blockbuster teal shadows, orange skin", (r"teal.?(and|&|n).?orange", r"blockbuster", r"hollywood")),
    "golden_hour": ("Golden Hour", "soft golden sunset light", (r"golden hour", r"sunset look", r"sunehr")),
    "moody_blue": ("Moody Blue", "dark desaturated blues", (r"moody", r"\bsad\b", r"rainy")),
    "cyberpunk": ("Cyberpunk", "magenta & cyan neon city", (r"cyber.?punk", r"neon city", r"futuristic")),
    "forest": ("Forest Green", "rich greens, earthy shadows", (r"forest", r"\bnature\b", r"greenery", r"hariyali")),
    "faded_film": ("Faded Film", "lifted blacks, soft matte film", (r"faded", r"\bmatte\b", r"analog")),
    "pastel": ("Pastel", "light, airy pastel colours", (r"pastel", r"airy", r"soft colou?rs")),
    "noir": ("Noir", "high-contrast black & white with crushed blacks", (r"\bnoir\b", r"high.?contrast b(lack)? ?(and|&)? ?w")),
    "warm_film": ("Warm Film", "Kodak-like warm film stock", (r"warm film", r"kodak", r"vintage warm")),
    "arctic": ("Arctic", "icy cold whites and blues", (r"arctic", r"\bicy\b", r"winter look", r"thand")),
}

# --- caption / title animations (ASS override tags; see renderer.build_ass) ----------------------------------
TEXT_ANIMATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "fade": ("fade in/out", (r"fade(d)? (captions|text|subtitles)",)),
    "pop": ("scale pop", (r"\bpop\b", r"pop.?up", r"popping")),
    "slide_up": ("slide up from below", (r"slide.?up (text|captions)", r"rising text", r"text slide")),
    "typewriter": ("letters appear one by one", (r"typewriter", r"typing (effect|text)", r"type.?on")),
    "bounce": ("bouncy scale", (r"bounc(e|y) (text|captions)", r"bouncy")),
    "karaoke": ("word-by-word highlight", (r"karaoke", r"word (by|per) word", r"highlight (each|every) word", r"hormozi")),
    "zoom_in": ("grows in from nothing", (r"zoom.?in (text|title|captions?)", r"(text|title) zoom.?in", r"grow(ing)? text")),
    "zoom_out": ("shrinks in from big", (r"zoom.?out (text|title)", r"(text|title) zoom.?out")),
    "spin_in": ("spins in", (r"spin(ning)? (text|title)", r"(text|title) spin", r"ghoom(ta|ti)? (text|title)")),
    "flip_in": ("3D flip in", (r"flip (text|title)", r"(text|title) flip")),
    "blur_in": ("blur to sharp", (r"blur.?in", r"blurry (text|title) to sharp", r"focus.?in text")),
    "drop_in": ("drops from above", (r"drop(ping)? (text|title)", r"(text|title) drops?", r"falling text")),
    "fly_left": ("flies in from the left", (r"(fly|flies|flying|slides?|sliding) in from (the )?left", r"left se (aaye|aata)")),
    "fly_right": ("flies in from the right", (r"(fly|flies|flying|slides?|sliding) in from (the )?right", r"right se (aaye|aata)")),
    "swing": ("swings like a sign", (r"swing(ing)? (text|title)", r"(text|title) swing")),
    "shake": ("shaky text", (r"shak(e|y|ing) (text|title|captions?)", r"(text|title) shake", r"hilta (text|hua)")),
    "heartbeat": ("beats like a heart", (r"heart.?beat", r"pulsing (text|title)", r"dhadk")),
    "flicker": ("flickers on", (r"flicker(ing)? (text|title)", r"(text|title) flicker", r"blink(ing)? text")),
    "glow_pulse": ("pulsing glow", (r"glow(ing)? pulse", r"pulsing glow")),
    "color_cycle": ("colour changing", (r"colou?r (changing|cycle|cycling) (text|title)", r"rainbow (text|title)",
                                        r"rang badal")),
    "wave": ("letters wave", (r"wav(e|y|ing) (text|letters|title)", r"letters? wave")),
    "cascade": ("letters fade in one by one", (r"cascade", r"letter by letter", r"one letter at a time")),
    "stretch": ("stretches into place", (r"stretch(ing|y)? (text|title)", r"elastic (text|title)")),
}

# Effects that follow a tracked person / face (cutmind/tracking.py). The renderer builds them from Effect.points.
SUBJECT_EFFECTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "follow": ("Follow Cam", "the frame follows the person (auto reframe)", (
        r"\btrack(ing)? (the |that |this |main )?(person|man|woman|guy|girl|subject|face|him|her|insaan|bande|banda)",
        r"follow (the |that |this )?(person|subject|him|her|face|guy|girl)", r"auto.?reframe", r"follow cam",
        r"(person|banda|bande|ladka|ladki|insaan|aadmi|face|chehra)\w*.{0,25}(track|follow|peeche|center|centre|beech)",
        r"keep (him|her|them|the (person|subject|face)) (in|at) (the )?(cent(er|re)|frame|middle)")),
    "person_zoom": ("Zoom on Person", "tight framing on the person, following them", (
        r"zoom (in )?on (the |that |this )?(person|face|subject|him|her|speaker)",
        r"(person|face|chehra|banda|ladka|ladki)\w*.{0,20}(pe|par|par)? ?zoom", r"close.?up (on|of) (the )?(person|face)")),
    "spotlight": ("Spotlight", "darkens everything except the person", (
        r"spotlight", r"highlight (the )?(person|subject|him|her)", r"(baaki|baki) (sab )?(dark|andhera|kaala)",
        r"focus (on )?(the )?(person|subject|him|her|face)", r"main focus")),
}

_REGISTRY += [FX(k, name, "motion", desc, kw, None) for k, (name, desc, kw) in SUBJECT_EFFECTS.items()]
# motion engine: authored keyframes with easing (engines/motion.py), built by the renderer from points
_REGISTRY.append(FX("keyframes", "Keyframed Move", "motion", "keyframes (zoom / slide / tilt) with an easing curve: "
                    "ease in-out, back (pop), bounce, elastic, spring", (), None))
# Copy an Edit: the liked video's measured camera move (cutmind/camera_move.py), built by the renderer from points
_REGISTRY.append(FX("camera_move", "Copied Camera Move", "motion", "the camera move of the video you liked "
                    "(push-in, pan, tilt, roll)", (), None))


def _punch(c: FxContext) -> list[str]:
    """Emphasis punch-in on given times: 1 → 1.07 in 0.12 s, eased back over 0.6 s (hides cuts, marks key words)."""
    if not c.times:
        return []
    z = 0.07 * c.strength
    bumps = "+".join(f"if(between(t,{_f(b)},{_f(b + 0.72)}),if(lt(t,{_f(b + 0.12)}),(t-{_f(b)})/0.12,1-(t-{_f(b + 0.12)})/0.6),0)"
                     for b in c.times[:20])
    f = f"(1+{_f(z)}*min(1,{bumps}))"
    return [f"scale=w='trunc({c.w}*{f}/2)*2':h='trunc({c.h}*{f}/2)*2':eval=frame", f"crop={c.w}:{c.h}"]


def _punch_static(c: FxContext) -> list[str]:
    """8% tighter framing for the whole segment (alternating it hides jump cuts)."""
    s = 1.0 + 0.08 * c.strength
    return [f"scale={int(c.w * s) // 2 * 2}:{int(c.h * s) // 2 * 2}", f"crop={c.w}:{c.h}"]


_REGISTRY.append(FX("silhouette", "Silhouette", "video_effect", "high-contrast black & white, near silhouette",
                    (r"silhouette", r"high.?contrast (b ?& ?w|black (and|&) white)"),
                    lambda c: ["hue=s=0", "eq=contrast=3.2:brightness=0.06"]))

# editorial effects: placed by the agents on chosen moments, not asked for by name
_REGISTRY += [FX("punch", "Emphasis Punch", "motion", "quick push-in on an important word", (), _punch),
              FX("punch_static", "Jump-cut Cover", "motion", "slightly tighter framing to hide a jump cut", (), _punch_static)]
# black & white as an EFFECT (so it can be timed: "pehle 3 sec black and white phir colour") — the whole-video
# black & white look stays the "bw" colour preset
_REGISTRY.append(FX("mono", "Black & White", "video_effect", "black and white for part of the video", (
    r"black (and|&|n) white (effect|screen|flash|se colou?r)", r"\bb ?& ?w effect", r"mono(chrome)? effect",
    r"(black (and|&|n) white|b ?& ?w)\b.{0,40}colou?r (reveal|aaye|wapas)"), lambda c: ["hue=s=0"]))


IMPACT_SECONDS = 0.25  # how long a zoom-blur hit lasts at the start of a shot


def _impact(c: FxContext) -> list[str]:
    """Fan-edit "hit" on the cut: the shot lands 22% zoomed in and settles in 0.25 s, with a motion blur and a
    red/blue split for the first frames (zoom blur + chromatic aberration)."""
    z, d = 0.22 * c.strength, IMPACT_SECONDS
    f = f"(1+{_f(z)}*max(0,1-t/{_f(d)}))"
    s = max(4, int(round(min(c.w, c.h) * 0.02 * c.strength)))
    return [f"scale=w='trunc({c.w}*{f}/2)*2':h='trunc({c.h}*{f}/2)*2':eval=frame", f"crop={c.w}:{c.h}",
            "gblur=sigma=9:enable='lt(t,0.1)'", f"rgbashift=rh=-{s}:bh={s}:rv=2:bv=-2:enable='lt(t,{_f(d * 0.8)})'"]


def _drift(c: FxContext) -> list[str]:
    """Slow, gentle push-in (6 % over the shot) for calm parts of a song."""
    return _zoom(+1)(FxContext(c.w, c.h, c.duration, c.fps, 0.5 * c.strength, c.times))


def _film_bw(c: FxContext) -> list[str]:
    """Old-movie black & white: grey, a bit more contrast, film grain, gentle brightness flicker, dark corners."""
    return ["hue=s=0", "eq=contrast=1.18:brightness='-0.02+0.035*sin(t*31)*sin(t*7)':eval=frame",
            f"noise=alls={int(22 * c.strength)}:allf=t", "vignette=angle=0.7"]


_REGISTRY += [
    FX("film_bw", "Old Movie B&W", "video_effect", "black & white like an old film: grain, flicker, dark corners", (
        r"old (movie|film) (style )?(black (and|&|n) white|b ?& ?w)", r"(black (and|&|n) white|b ?& ?w).{0,25}"
        r"(old|purani|purane|puraani) (movie|film|picture|zamane)", r"(old|purani|purane) (movie|film) (jaisa|jaise|wala|look)"),
       _film_bw),
    FX("drift", "Slow Drift", "motion", "gentle push-in on calm shots (song-driven edits)", (), _drift),
    FX("impact", "Impact Hit", "video_effect", "zoom blur + RGB split hit at the start of a shot (fan edits)",
       (r"zoom.?blur", r"impact (hits?|effect)", r"shock.?wave", r"\bhits? on (the )?cuts?"), _impact),
    # the colour pass of fan edits also uses a negative black & white shot
    FX("invert_mono", "Inverted B&W", "video_effect", "negative black & white (colour pass)",
       (r"invert(ed)? (b ?& ?w|black (and|&) white)", r"negative (b ?& ?w|black (and|&) white)"),
       _c("hue=s=0", "negate", "eq=contrast=1.35")),
]

# the shots of a colour pass (fan edits): any of these counts as a black & white shot
BW_PASS = ("mono", "silhouette", "invert_mono", "film_bw")

# Effects and transitions live in separate tables: some ids exist in both ("zoom" is a motion AND a transition).
EFFECTS_BY_ID: dict[str, FX] = {f.id: f for f in _REGISTRY}
TRANSITIONS_BY_ID: dict[str, FX] = {f.id: f for f in _REGISTRY_T}
ALL_FX: tuple[FX, ...] = (*_REGISTRY, *_REGISTRY_T)
EFFECT_IDS = tuple(f.id for f in _REGISTRY) + ("speed_ramp", "blur_background")
TRANSITION_IDS = tuple(f.id for f in _REGISTRY_T)


def xfade_name(transition_id: str) -> str:
    fx = TRANSITIONS_BY_ID.get(transition_id)
    if fx is None or fx.xfade is None:
        raise KeyError(f"unknown transition '{transition_id}'")
    return fx.xfade


def effect_filters(effect_id: str, ctx: FxContext) -> list[str]:
    fx = EFFECTS_BY_ID.get(effect_id)
    if fx is None or fx.build is None:
        return []  # speed_ramp / blur_background are handled by the renderer itself
    return fx.build(ctx)


def catalog() -> dict[str, list[dict[str, str]]]:
    """Public, UI-friendly listing."""
    out: dict[str, list[dict[str, str]]] = {"motion": [], "video_effect": [], "transition": [], "color": [], "text_animation": []}
    for f in [*_REGISTRY, *_REGISTRY_T]:
        out[f.category].append({"id": f.id, "name": f.name, "description": f.description})
    for k, (name, desc, _kw) in LUT_LOOKS.items():
        out["color"].append({"id": k, "name": name, "description": desc})
    for k, (desc, _kw) in TEXT_ANIMATIONS.items():
        out["text_animation"].append({"id": k, "name": k.replace("_", " ").title(), "description": desc})
    return out
