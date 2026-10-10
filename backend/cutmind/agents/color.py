"""Color agent: grade (preset → numbers) and per-clip exposure matching for a consistent look."""

from __future__ import annotations

from statistics import median
from typing import Any, Literal

from pydantic import BaseModel

from ..plan import ColorPreset, ColorSettings
from .base import AgentContext, BaseAgent, Feedback

PRESETS: dict[str, dict[str, float]] = {
    "none": {},
    "warm": {"warmth": 0.55, "saturation": 1.15, "contrast": 1.05},
    "cool": {"warmth": -0.55, "saturation": 1.05, "contrast": 1.05},
    "cinematic": {"contrast": 1.15, "saturation": 0.9, "warmth": 0.1, "brightness": -0.03},
    "vintage": {"contrast": 0.9, "saturation": 0.7, "warmth": 0.3, "brightness": 0.03},
    "bw": {"saturation": 0.0, "contrast": 1.12},
    "vivid": {"saturation": 1.45, "contrast": 1.1},
    "sepia": {"contrast": 1.05},
}


Change = Literal["lower", "unchanged", "higher"]


class ColorDecision(BaseModel):
    """Small local models handle categories far better than free numbers, so the LLM picks directions
    and the code turns them into exact, always-valid values."""

    preset: ColorPreset = "none"
    brightness: Literal["darker", "unchanged", "brighter"] = "unchanged"
    contrast: Change = "unchanged"
    saturation: Change = "unchanged"
    warmth: Literal["cooler", "unchanged", "warmer"] = "unchanged"


STEP = {"brightness": {"darker": -0.06, "unchanged": 0.0, "brighter": 0.08},
        "contrast": {"lower": -0.1, "unchanged": 0.0, "higher": 0.12},
        "saturation": {"lower": -0.25, "unchanged": 0.0, "higher": 0.3},
        "warmth": {"cooler": -0.4, "unchanged": 0.0, "warmer": 0.4}}


def decision_values(d: ColorDecision) -> dict[str, Any]:
    """Preset defaults + the LLM's relative tweaks, clamped to the Edit Plan ranges."""
    base = {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "warmth": 0.0, **PRESETS[d.preset]}
    vals = {
        "preset": d.preset,
        "brightness": max(-0.3, min(0.3, base["brightness"] + STEP["brightness"][d.brightness])),
        "contrast": max(0.7, min(1.4, base["contrast"] + STEP["contrast"][d.contrast])),
        "saturation": max(0.0, min(2.0, base["saturation"] + STEP["saturation"][d.saturation])),
        "warmth": max(-1.0, min(1.0, base["warmth"] + STEP["warmth"][d.warmth])),
    }
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in vals.items()}


class ColorAgent(BaseAgent):
    name = "color"
    system_prompt = (
        "You are the Color agent of a video editor. Choose a grade that matches the user's requested look: preset "
        "(none|warm|cool|cinematic|vintage|bw|vivid) plus optional extra tweaks: brightness (darker|unchanged|brighter), "
        "contrast (lower|unchanged|higher), saturation (lower|unchanged|higher), warmth (cooler|unchanged|warmer). "
        "If the user did not ask for a look, use preset none and unchanged everywhere. Exposure differences between "
        "clips are fixed automatically. JSON only."
    )
    decision_model = ColorDecision

    def task_payload(self, ctx: AgentContext) -> dict[str, Any]:
        it = ctx.intent
        lumas = {c.filename: round(ctx.analysis.get(c.id).luma, 3) for c in ctx.clips} if ctx.analysis else {}
        return {"prompt": ctx.prompt, "parser_hint_preset": it and it.color_preset,
                "info_only_measured_clip_luma_not_a_setting": lumas}

    def exposure_matching(self, ctx: AgentContext) -> dict[str, float]:
        """Pull every clip's mean brightness halfway towards the median → consistent look."""
        if not ctx.analysis or len(ctx.clips) < 2:
            return {}
        lumas = {c.id: ctx.analysis.get(c.id).luma for c in ctx.clips}
        mid = median(lumas.values())
        out = {}
        for cid, luma in lumas.items():
            off = max(-0.15, min(0.15, (mid - luma) * 0.5))
            if abs(off) > 0.02:
                out[cid] = round(off, 3)
        return out

    def _finalize(self, ctx: AgentContext, values: dict[str, Any], feedback: list[Feedback] | None) -> dict[str, Any]:
        settings = ColorSettings(**values)
        settings.clip_brightness = self.exposure_matching(ctx)
        for fb in feedback or []:
            if fb.check == "color_applied":
                # the grade was too subtle to measure: push it further from neutral
                settings.warmth = max(-1.0, min(1.0, settings.warmth * 1.6))
                settings.saturation = max(0.0, min(3.0, 1 + (settings.saturation - 1) * 1.6))
                settings.contrast = max(0.0, min(2.0, 1 + (settings.contrast - 1) * 1.5))
                settings.brightness = max(-1.0, min(1.0, settings.brightness * 1.5))
        ctx.log(self.name, "info", f"grade: preset={settings.preset} b={settings.brightness:.2f} c={settings.contrast:.2f} "
                                   f"s={settings.saturation:.2f} warmth={settings.warmth:.2f}; "
                                   f"exposure matching on {len(settings.clip_brightness)} clip(s)")
        return settings.model_dump()

    def rules(self, ctx: AgentContext, feedback: list[Feedback] | None) -> dict[str, Any]:
        it = ctx.intent
        assert it is not None
        preset = it.color_preset or "none"
        # LUT looks (teal_orange, cyberpunk, …) carry their whole grade in the .cube file
        values: dict[str, Any] = {"preset": preset, **PRESETS.get(preset, {})}
        values["brightness"] = round(values.get("brightness", 0.0) + it.brightness, 3)
        values["gamma"] = it.gamma
        return self._finalize(ctx, values, feedback)

    def from_decision(self, ctx: AgentContext, decision: BaseModel, feedback: list[Feedback] | None) -> dict[str, Any]:
        return self._finalize(ctx, decision_values(ColorDecision.model_validate(decision)), feedback)
