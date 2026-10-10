"""Where a source point lands in the output frame, and the FFmpeg expressions for subject-following crops.

Shared by the Effects agent (to place tracked text) and the renderer (to build the crops), so both agree.
All subject points are normalised source coordinates (0..1); times are segment-local output seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_KEYS = 40  # keyframes per segment in an FFmpeg expression (2 per second is plenty after smoothing)


@dataclass(frozen=True)
class Frame:
    """How a W×H source is fitted into a w×h canvas."""

    W: int
    H: int
    w: int
    h: int
    mode: str = "crop"   # crop | blur_pad | follow
    zoom: float = 1.0

    @property
    def scale(self) -> float:
        if self.mode == "blur_pad":
            return min(self.w / self.W, self.h / self.H)
        return max(self.w / self.W, self.h / self.H) * self.zoom

    @property
    def scaled(self) -> tuple[int, int]:
        s = self.scale
        return int(round(self.W * s / 2)) * 2, int(round(self.H * s / 2)) * 2

    def crop_origin(self, cx: float, cy: float) -> tuple[float, float]:
        """Top-left of the crop window in scaled pixels (centre crop, or centred on the subject for follow)."""
        sw, sh = self.scaled
        if self.mode == "blur_pad":
            return -(self.w - sw) / 2, -(self.h - sh) / 2
        if self.mode == "follow":
            return (min(max(cx * sw - self.w / 2, 0), sw - self.w), min(max(cy * sh - self.h / 2, 0), sh - self.h))
        return (sw - self.w) / 2, (sh - self.h) / 2

    def to_output(self, cx: float, cy: float, follow_c: tuple[float, float] | None = None) -> tuple[float, float]:
        """Output pixel of source point (cx, cy). For follow crops, `follow_c` is the subject centre the crop follows."""
        sw, sh = self.scaled
        ox, oy = self.crop_origin(*(follow_c or (cx, cy)))
        return cx * sw - ox, cy * sh - oy


def follow_zoom(W: int, H: int, w: int, h: int) -> float:
    """A follow crop needs room to move: when the source already has the canvas shape, zoom in a little."""
    src, dst = W / H, w / h
    return 1.0 if abs(src - dst) / dst > 0.15 else 1.25


def resample(points: list[tuple[float, ...]], max_keys: int = MAX_KEYS) -> list[tuple[float, ...]]:
    if len(points) <= max_keys:
        return points
    step = (len(points) - 1) / (max_keys - 1)
    return [points[round(i * step)] for i in range(max_keys)]


def piecewise(keys: list[tuple[float, float]]) -> str:
    """FFmpeg expression in `t` that linearly interpolates (t, value) keys (held before the first / after the last)."""
    keys = [(round(t, 3), round(v, 2)) for t, v in keys]
    if not keys:
        return "0"
    if len(keys) == 1:
        return f"{keys[0][1]}"
    expr = f"{keys[-1][1]}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:], strict=False))):
        slope = (v1 - v0) / max(1e-3, t1 - t0)
        expr = f"if(lt(t\\,{t1})\\,{v0}+({slope:.4f})*(t-{t0})\\,{expr})"
    return f"if(lt(t\\,{keys[0][0]})\\,{keys[0][1]}\\,{expr})"
