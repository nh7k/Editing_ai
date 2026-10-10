"""CutMind colour looks as 3D LUTs (.cube), generated from simple colour maths — our own work, no third-party LUTs.

`ensure_luts()` writes `assets/luts/<look>.cube` (33³) once; the renderer applies them with FFmpeg `lut3d`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from .config import BACKEND_DIR

LUT_DIR = BACKEND_DIR / "assets" / "luts"
SIZE = 33
Arr = np.ndarray


def _luma(rgb: Arr) -> Arr:
    return (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2])[..., None]


def _sat(rgb: Arr, s: float) -> Arr:
    y = _luma(rgb)
    return y + (rgb - y) * s


def _scurve(x: Arr, k: float) -> Arr:
    """Contrast S-curve around 0.5 that keeps 0→0 and 1→1 (k>0 = more contrast in the mids)."""
    return 0.5 + (x - 0.5) * (1 + k) - k * 4 * (x - 0.5) ** 3


def _split_tone(rgb: Arr, shadow: tuple[float, float, float], highlight: tuple[float, float, float], amount: float) -> Arr:
    y = _luma(rgb)
    sh = np.clip(1 - 2 * y, 0, 1)
    hi = np.clip(2 * y - 1, 0, 1)
    return rgb + amount * (sh * np.array(shadow) + hi * np.array(highlight))


def _lift_gain(rgb: Arr, lift: float, gain: float) -> Arr:
    return lift + rgb * (gain - lift)


LOOKS: dict[str, Callable[[Arr], Arr]] = {
    "teal_orange": lambda c: _scurve(_split_tone(_sat(c, 1.1), (-0.06, 0.04, 0.10), (0.10, 0.03, -0.08), 1.0), 0.25),
    "golden_hour": lambda c: _lift_gain(_split_tone(_sat(c, 1.12), (0.03, 0.01, -0.03), (0.10, 0.05, -0.06), 1.0), 0.03, 1.0),
    "moody_blue": lambda c: _scurve(_split_tone(_sat(c, 0.7), (-0.02, 0.01, 0.08), (-0.02, 0.0, 0.04), 1.0) * 0.92, 0.2),
    "cyberpunk": lambda c: _scurve(_split_tone(_sat(c, 1.3), (0.10, -0.04, 0.14), (-0.08, 0.06, 0.12), 1.0), 0.2),
    "forest": lambda c: _scurve(_split_tone(c * np.array([0.97, 1.06, 0.95]), (0.04, 0.02, -0.02), (-0.02, 0.04, -0.02), 1.0), 0.15),
    "faded_film": lambda c: _lift_gain(_split_tone(_sat(c, 0.82), (0.0, 0.02, 0.04), (0.04, 0.02, -0.02), 1.0), 0.08, 0.93),
    "pastel": lambda c: _lift_gain(_sat(c, 0.68), 0.14, 1.0) * np.array([1.0, 0.99, 1.02]),
    "noir": lambda c: np.repeat(_scurve(np.clip(_luma(c) * 1.05 - 0.03, 0, 1), 0.6), 3, axis=-1),
    "warm_film": lambda c: _scurve(_split_tone(_sat(c, 0.95), (0.0, 0.03, 0.01), (0.08, 0.04, -0.04), 1.0), 0.18),
    "arctic": lambda c: _lift_gain(_split_tone(_sat(c, 0.8), (-0.02, 0.02, 0.08), (-0.03, 0.01, 0.06), 1.0), 0.02, 1.04),
}

# Tier 1 looks (also LUTs, so every look has a strength 0..1 and works on any part of the video)
TIER1_LOOKS: dict[str, Callable[[Arr], Arr]] = {
    "grayscale": lambda c: np.repeat(_luma(c), 3, axis=-1),
    "sepia": lambda c: c @ np.array([[0.393, 0.349, 0.272], [0.769, 0.686, 0.534], [0.189, 0.168, 0.131]]),
    "cinematic": lambda c: _scurve(_split_tone(_sat(c, 0.92), (-0.03, 0.01, 0.05), (0.06, 0.02, -0.04), 1.0), 0.3),
    "vintage": lambda c: _lift_gain(_split_tone(_sat(c, 0.65), (0.02, 0.03, 0.0), (0.06, 0.03, -0.05), 1.0), 0.1, 0.9),
    "warm": lambda c: c * np.array([1.08, 1.0, 0.86]) + np.array([0.02, 0.01, 0.0]),
    "cool": lambda c: c * np.array([0.9, 1.0, 1.1]) + np.array([0.0, 0.0, 0.02]),
}
ALL_LOOKS: dict[str, Callable[[Arr], Arr]] = {**LOOKS, **TIER1_LOOKS}


def _grid() -> Arr:
    v = np.linspace(0.0, 1.0, SIZE)
    b, g, r = np.meshgrid(v, v, v, indexing="ij")  # .cube order: red changes fastest
    return np.stack([r, g, b], axis=-1).reshape(-1, 3)


def write_cube(name: str, fn: Callable[[Arr], Arr], path: Path) -> Path:
    out = np.clip(fn(_grid()), 0.0, 1.0)
    lines = [f'TITLE "CutMind {name}"', f"LUT_3D_SIZE {SIZE}", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    lines += [f"{r:.5f} {g:.5f} {b:.5f}" for r, g, b in out]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def ensure_luts(directory: Path = LUT_DIR) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, fn in LOOKS.items():
        p = directory / f"{name}.cube"
        if not p.exists():
            write_cube(name, fn, p)
        paths[name] = p
    return paths


def ensure_look(name: str, strength: float = 1.0, directory: Path = LUT_DIR) -> str:
    """A look at a strength (0..1, mixed with the untouched colour) as a .cube; returns its FILE NAME (the
    renderer runs lut3d with cwd = LUT_DIR)."""
    if name not in ALL_LOOKS:
        raise KeyError(f"unknown look '{name}'")
    s = round(min(1.0, max(0.0, strength)), 2)
    fname = f"{name}.cube" if s >= 0.995 and name in LOOKS else f"{name}_s{int(round(s * 100)):03d}.cube"
    p = directory / fname
    if not p.exists():
        directory.mkdir(parents=True, exist_ok=True)
        fn = ALL_LOOKS[name]
        write_cube(f"{name} {s:.2f}", lambda c: c * (1 - s) + fn(c) * s, p)
    return fname


def apply_look(rgb01: Arr, name: str) -> Arr:
    """Exact look maths (used by tests to compare against what FFmpeg rendered)."""
    return np.clip(ALL_LOOKS[name](rgb01), 0, 1)
