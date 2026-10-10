"""Motion engine: keyframes with easing, compiled to FFmpeg expressions (and described for Media3).

Each easing exists twice from ONE definition — a Python function (tests, previews, Media3 per-frame matrices) and an
FFmpeg expression in a progress variable p ∈ [0, 1]. tests/unit/test_motion_engine.py checks that both give the
same numbers.

Keyframes: [(t, value), …] per property; between two keys the value moves with the chosen easing.
"""

from __future__ import annotations

import math
from collections.abc import Callable

PI = math.pi


def _bounce(p: float) -> float:
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


# name → (python f(p), FFmpeg expression of P). P is substituted with the progress expression.
EASINGS: dict[str, tuple[Callable[[float], float], str]] = {
    "linear": (lambda p: p, "(P)"),
    "ease_in": (lambda p: p ** 3, "pow(P,3)"),
    "ease_out": (lambda p: 1 - (1 - p) ** 3, "(1-pow(1-(P),3))"),
    "ease_in_out": (lambda p: 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2,
                    "if(lt(P,0.5),4*pow(P,3),1-pow(-2*(P)+2,3)/2)"),
    # overshoots a little and settles ("pop")
    "back": (lambda p: 1 + 2.70158 * (p - 1) ** 3 + 1.70158 * (p - 1) ** 2,
             "(1+2.70158*pow((P)-1,3)+1.70158*pow((P)-1,2))"),
    "elastic": (lambda p: 0.0 if p <= 0 else 1.0 if p >= 1 else 2 ** (-10 * p) * math.sin((p * 10 - 0.75) * 2 * PI / 3) + 1,
                "if(lte(P,0),0,if(gte(P,1),1,pow(2,-10*(P))*sin(((P)*10-0.75)*2*PI/3)+1))"),
    # a damped spring: fast, overshoots, rings out
    "spring": (lambda p: 1 - math.exp(-6 * p) * math.cos(4 * PI * p),
               "(1-exp(-6*(P))*cos(4*PI*(P)))"),
    "bounce": (_bounce,
               "if(lt(P,1/2.75),7.5625*pow(P,2),if(lt(P,2/2.75),7.5625*pow((P)-1.5/2.75,2)+0.75,"
               "if(lt(P,2.5/2.75),7.5625*pow((P)-2.25/2.75,2)+0.9375,7.5625*pow((P)-2.625/2.75,2)+0.984375)))"),
}


def ease(name: str, p: float) -> float:
    return EASINGS.get(name, EASINGS["linear"])[0](min(1.0, max(0.0, p)))


def value_at(keys: list[tuple[float, float]], t: float, easing: str = "ease_in_out") -> float:
    """Python reference: the keyframed value at time t."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:], strict=False):
        if t < t1:
            return v0 + (v1 - v0) * ease(easing, (t - t0) / max(1e-6, t1 - t0))
    return keys[-1][1]


def expr(keys: list[tuple[float, float]], var: str = "t", easing: str = "ease_in_out", digits: int = 4) -> str:
    """The same value as an FFmpeg expression of `var` (commas escaped for a filter graph)."""
    keys = [(round(t, 3), round(v, digits)) for t, v in keys]
    if len(keys) == 1:
        return f"{keys[0][1]}"
    form = EASINGS.get(easing, EASINGS["linear"])[1]
    out = f"{keys[-1][1]}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:], strict=False))):
        p = f"(({var}-{t0})/{max(1e-3, t1 - t0)})"
        # substitute the progress P — but not the P of PI (that broke spring / elastic: caught by the render test)
        seg = f"{v0}+({v1 - v0:.5f})*{form.replace('PI', '\x00').replace('P', p).replace('\x00', 'PI')}"
        out = f"if(lt({var},{t1}),{seg},{out})"
    return f"if(lt({var},{keys[0][0]}),{keys[0][1]},{out})".replace(",", "\\,")


# motion presets → keyframes [t, zoom, dx, dy, angle] over a window of `d` seconds (dx, dy: share of the frame)
def preset(name: str, d: float) -> tuple[list[list[float]], str]:
    d = max(0.3, d)
    if name == "pop_in":          # starts small, overshoots, settles
        return [[0, 0.8, 0, 0, 0], [min(0.5, d), 1.0, 0, 0, 0], [d, 1.0, 0, 0, 0]], "back"
    if name == "zoom_bounce":     # punches in and bounces back
        return [[0, 1.0, 0, 0, 0], [min(0.6, d), 1.25, 0, 0, 0], [d, 1.25, 0, 0, 0]], "bounce"
    if name == "spring_zoom":
        return [[0, 1.0, 0, 0, 0], [min(0.8, d), 1.2, 0, 0, 0], [d, 1.2, 0, 0, 0]], "spring"
    if name == "slide_in_left":   # enters from the left
        return [[0, 1.15, -0.06, 0, 0], [min(0.6, d), 1.15, 0, 0, 0], [d, 1.15, 0, 0, 0]], "ease_out"
    if name == "tilt_in":
        return [[0, 1.15, 0, 0, -4], [min(0.7, d), 1.15, 0, 0, 0], [d, 1.15, 0, 0, 0]], "elastic"
    if name == "ken_burns":       # slow push with a drift, eased at both ends
        return [[0, 1.0, -0.02, -0.01, 0], [d, 1.18, 0.02, 0.01, 0]], "ease_in_out"
    raise KeyError(name)


PRESETS = ("pop_in", "zoom_bounce", "spring_zoom", "slide_in_left", "tilt_in", "ken_burns")

MEDIA3 = ("Media3: a GlMatrixTransformation whose getMatrix(presentationTimeUs) evaluates the same keyframes with "
          "the Python easing above (scale, translate, rotate) — NOT TESTED (no Android device in this session)")
