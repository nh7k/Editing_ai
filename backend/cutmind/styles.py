"""Named "pro" looks: colour grade + animated gradient graphic tracks + caption/title styling.

Used for one-click styling and for the 3-variation mode ("Created 3 versions, ranked best first").
Colours are our own blue / violet / cyan palette.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Style:
    id: str
    name: str
    description: str
    colors: tuple[str, ...]                  # palette shown in the app
    grade: dict[str, float]                   # ColorSettings overrides (applied when no colour was asked for)
    overlays: tuple[dict[str, Any], ...]      # Overlay templates (start/end filled in per edit)
    caption_box: str                          # caption box colour
    title_color: str = "#FFFFFF"
    transition: str | None = None             # used when the prompt didn't ask for one
    effects: tuple[str, ...] = field(default_factory=tuple)
    caption_animation: str = "none"          # used when the prompt didn't pick one


STYLES: dict[str, Style] = {
    "midnight_drift": Style(
        id="midnight_drift", name="Midnight Drift",
        description="dark blue gradient wash with a slow vertical drift, quiet cinematic feel",
        colors=("#020617", "#0B1E5B", "#1E3A8A", "#38BDF8"),
        grade={"contrast": 1.08, "saturation": 0.92, "warmth": -0.15, "brightness": -0.02},
        overlays=(
            {"kind": "wash", "label": "Midnight Blue Drift", "colors": ["#0B1E5B", "#1E3A8A", "#020617"],
             "motion": "drift", "speed": 0.012, "opacity": 0.30, "thickness": 10},
            {"kind": "glow_frame", "label": "Soft Sky Edge", "colors": ["#1E3A8A", "#38BDF8"],
             "motion": "rotate", "speed": 0.01, "opacity": 0.55, "thickness": 6},
        ),
        caption_box="#1E3A8A", transition="crossfade", caption_animation="fade",
    ),
    "violet_authority": Style(
        id="violet_authority", name="Violet Authority",
        description="bold blue-violet gradient styling, strong framed hook, smooth motion",
        colors=("#1E1B4B", "#4C1D95", "#7C5CFF", "#2563EB"),
        grade={"contrast": 1.12, "saturation": 1.05, "warmth": -0.05},
        overlays=(
            {"kind": "wash", "label": "Blue Violet Wash", "colors": ["#1E1B4B", "#6D28D9", "#2563EB"],
             "motion": "rotate", "speed": 0.015, "opacity": 0.24, "thickness": 10},
            {"kind": "bar", "label": "Violet Lower Bar", "colors": ["#7C5CFF", "#2563EB"],
             "motion": "rotate", "speed": 0.03, "opacity": 0.85, "thickness": 8},
            {"kind": "glow_frame", "label": "Violet Glow Frame", "colors": ["#7C5CFF", "#2563EB", "#7C5CFF"],
             "motion": "rotate", "speed": 0.02, "opacity": 0.9, "thickness": 8},
        ),
        caption_box="#6D28D9", transition="crossfade", effects=("zoom",), caption_animation="slide_up",
    ),
    "cyan_kinetic": Style(
        id="cyan_kinetic", name="Cyan Kinetic",
        description="cyan-indigo glowing accents, faster energy, presentation-ready",
        colors=("#22D3EE", "#6366F1", "#0EA5E9", "#0F172A"),
        grade={"contrast": 1.1, "saturation": 1.12, "warmth": -0.2},
        overlays=(
            {"kind": "glow_frame", "label": "Cyan Indigo Motion Accent", "colors": ["#22D3EE", "#6366F1", "#22D3EE"],
             "motion": "rotate", "speed": 0.03, "opacity": 0.95, "thickness": 10},
            {"kind": "wash", "label": "Indigo Haze", "colors": ["#0F172A", "#6366F1", "#0EA5E9"],
             "motion": "rotate", "speed": 0.025, "opacity": 0.16, "thickness": 10},
        ),
        caption_box="#0891B2", transition="wipe", effects=("zoom",), caption_animation="pop",
    ),
}

DEFAULT_ORDER = ("cyan_kinetic", "violet_authority", "midnight_drift")


def style_overlays(style: Style, total: float) -> list[dict[str, Any]]:
    """Overlay dicts spanning the whole edit."""
    return [{**o, "start": 0.0, "end": round(total, 3)} for o in style.overlays]


def public_styles() -> list[dict[str, Any]]:
    return [{"id": s.id, "name": s.name, "description": s.description, "colors": list(s.colors)} for s in STYLES.values()]


def apply_style(plan: Any, style_id: str, keep_color: bool = False) -> Any:
    """Return a copy of `plan` (EditPlan) with the look applied. Timing is never changed, so captions,
    cuts and duration stay exactly as reviewed."""
    from .plan import EditPlan  # local import: plan.py must not depend on styles.py

    style = STYLES[style_id]
    data = plan.to_json()
    if not keep_color:  # an explicitly requested grade (e.g. "black and white") wins over the style
        data["color"] = {**data["color"], **style.grade, "preset": data["color"].get("preset", "none")}
    data["overlays"] = style_overlays(style, plan.total_duration())
    for t in data["text"]:
        if t["kind"] == "caption":
            t["style"]["box_color"] = style.caption_box
            if t["style"].get("animation", "none") == "none":
                t["style"]["animation"] = style.caption_animation
        elif t["kind"] == "title":
            t["style"]["color"] = style.title_color
    have = {e["type"] for e in data["effects"]}
    data["effects"] += [{"type": e, "target": -1, "strength": 0.8} for e in style.effects if e not in have]
    data["style"] = style_id
    return EditPlan.model_validate(data)
