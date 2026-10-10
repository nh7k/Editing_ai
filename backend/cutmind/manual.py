"""Manual editing: deterministic operations on the last Edit Plan — no AI step.

Clicking a font, an animation, an effect or a timeline action in the studio sends one of these operations;
they are applied to the plan exactly as given, the plan is validated, and only what changed is re-rendered
(cuts/colour/effects unchanged → the cached picture is reused and only text + audio are redone, seconds not minutes).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from .fx_catalog import EFFECTS_BY_ID, LUT_LOOKS, TRANSITIONS_BY_ID
from .plan import EditPlan, Effect, TextItem, TextStyle, TimelineEntry, Transition
from .styles import STYLES, apply_style
from .text_styles import FONTS, TEXT_PRESETS, apply_look

Position = Literal["bottom", "center", "top", "top_right", "bottom_right"]


class TextFields(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=200)
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, gt=0)
    preset: str | None = None
    font: str | None = None
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    size: int | None = Field(None, ge=12, le=160)
    position: Position | None = None
    animation: str | None = None
    behind: bool | None = None  # draw the text behind the people in the shot


class AddText(TextFields):
    op: Literal["add_text"]
    text: str = Field(min_length=1, max_length=200)
    track: Literal["none", "person", "face"] = "none"


class UpdateText(TextFields):
    op: Literal["update_text"]
    index: int = Field(ge=0)


class RemoveText(BaseModel):
    op: Literal["remove_text"]
    index: int = Field(ge=0)


class AddEffect(BaseModel):
    op: Literal["add_effect"]
    type: str
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, gt=0)


class RemoveEffect(BaseModel):
    op: Literal["remove_effect"]
    type: str


class SetTransition(BaseModel):
    op: Literal["set_transition"]
    type: str | None = None   # None = hard cuts
    duration: float = Field(0.5, gt=0.05, le=2.0)


class SetLook(BaseModel):
    op: Literal["set_look"]
    preset: str               # warm | cool | cinematic | vintage | bw | vivid | sepia | <LUT look> | none


class SetStyle(BaseModel):
    op: Literal["set_style"]
    style: str | None = None


class DeleteSegment(BaseModel):
    op: Literal["delete_segment"]
    index: int = Field(ge=0)


class SetSpeed(BaseModel):
    op: Literal["set_speed"]
    index: int = Field(ge=0)
    speed: float = Field(gt=0.2, le=4.0)


class MoveSegment(BaseModel):
    op: Literal["move_segment"]
    index: int = Field(ge=0)
    to: int = Field(ge=0)


class RemoveCaptions(BaseModel):
    op: Literal["remove_captions"]


class StyleCaptions(TextFields):
    op: Literal["style_captions"]


class SetAudio(BaseModel):
    """Sound, by hand: swap or remove the song, levels, original sound on/off. Instant (no AI, no re-cut)."""
    op: Literal["set_audio"]
    music: str | None = Field(None, max_length=120)      # a project / library song name
    no_music: bool = False                                 # take the song out
    music_volume: float | None = Field(None, ge=0.0, le=1.0)
    voice_volume: float | None = Field(None, ge=0.0, le=3.0)  # the video's own sound (1 = as recorded)
    mute: bool | None = None                               # original sound off / on
    music_start: float | None = Field(None, ge=0.0, le=3600.0)


Op = Annotated[AddText | UpdateText | RemoveText | AddEffect | RemoveEffect | SetTransition | SetLook | SetStyle
               | DeleteSegment | SetSpeed | MoveSegment | RemoveCaptions | StyleCaptions | SetAudio, Field(discriminator="op")]


class ManualEdit(BaseModel):
    ops: list[Op] = Field(min_length=1, max_length=50)


class ManualError(ValueError):
    """The operation can't be applied (unknown effect, index out of range, …)."""


def _styled(style: TextStyle, f: TextFields) -> TextStyle:
    if f.preset is not None and f.preset not in TEXT_PRESETS:
        raise ManualError(f"unknown text preset '{f.preset}'")
    if f.font is not None and f.font not in FONTS:
        raise ManualError(f"unknown font '{f.font}'")
    st = apply_look(style, f.preset, f.color, f.animation)
    upd: dict[str, Any] = {}
    if f.font:
        upd["font"] = f.font
    if f.size:
        upd["size"] = f.size
    if f.position:
        upd["position"] = f.position
    return TextStyle.model_validate({**st.model_dump(), **upd})


def _segments_in(timeline: list[TimelineEntry], start: float | None, end: float | None) -> list[int]:
    if start is None and end is None:
        return [-1]
    a, b = start or 0.0, end if end is not None else 1e9
    return [e.index for e in timeline if a - 0.05 <= e.start + e.duration / 2 < b + 0.05]


def describe(op: BaseModel) -> str:
    d = op.model_dump(exclude_none=True)
    kind = d.pop("op")
    return kind.replace("_", " ") + (" " + ", ".join(f"{k}={v}" for k, v in d.items()) if d else "")


TIMING_OPS = (SetTransition, DeleteSegment, SetSpeed, MoveSegment)


def _fit_text(data: dict[str, Any]) -> None:
    """The timeline got shorter/longer: keep every text item inside the video."""
    total = EditPlan.model_validate({**data, "text": []}).total_duration()
    kept = []
    for t in data["text"]:
        if t["start"] >= total - 0.1:
            continue
        t["end"] = round(min(t["end"], total), 3)
        kept.append(t)
    data["text"] = kept


def apply_ops(plan: EditPlan, ops: list[Any], tracked_text: Any = None,
              retime_captions: Any = None, song_exists: Any = None) -> tuple[EditPlan, list[str]]:
    """Apply operations in order. `tracked_text(item, target)` fills the path for text that follows a person;
    `retime_captions(plan)` rebuilds captions from the transcript after the timeline changed."""
    data = plan.to_json()
    notes: list[str] = []
    timing_changed = False
    for op in ops:
        if isinstance(op, TIMING_OPS):
            timing_changed = True
        cur = EditPlan.model_validate({**data, "text": []})
        timeline = cur.timeline()
        total = cur.total_duration()
        if isinstance(op, AddText):
            base = TextStyle(position="top" if op.track != "none" else "center", size=64, box_color=None)
            style = _styled(base, op)
            item = TextItem(kind="text", text=op.text, start=op.start or 0.0,
                            end=min(op.end, total) if op.end else round(total, 3), style=style, behind=bool(op.behind))
            if op.track != "none":
                if tracked_text is None:
                    raise ManualError("person tracking is not available here")
                item = tracked_text(item, op.track)
            data["text"].append(item.model_dump())
        elif isinstance(op, UpdateText | RemoveText):
            if op.index >= len(data["text"]):
                raise ManualError(f"there is no text #{op.index}")
            if isinstance(op, RemoveText):
                data["text"].pop(op.index)
            else:
                item = TextItem.model_validate(data["text"][op.index])
                upd: dict[str, Any] = {"style": _styled(item.style, op)}
                for k in ("text", "start", "end", "behind"):
                    if getattr(op, k) is not None:
                        upd[k] = getattr(op, k)
                data["text"][op.index] = item.model_copy(update=upd).model_dump()
        elif isinstance(op, StyleCaptions):
            n = 0
            for i, t in enumerate(data["text"]):
                if t["kind"] == "caption":
                    item = TextItem.model_validate(t)
                    data["text"][i] = item.model_copy(update={"style": _styled(item.style, op)}).model_dump()
                    n += 1
            if not n:
                raise ManualError("this edit has no captions to style")
        elif isinstance(op, RemoveCaptions):
            data["text"] = [t for t in data["text"] if t["kind"] != "caption"]
        elif isinstance(op, SetAudio):
            a = data["audio"]
            if op.no_music:
                a["music"] = None
            elif op.music is not None:
                if song_exists is not None and not song_exists(op.music):
                    raise ManualError(f"no song called '{op.music}' — upload it in Sounds first")
                a["music"] = op.music
                a["music_volume"] = op.music_volume if op.music_volume is not None else max(a["music_volume"], 0.5)
            for k in ("music_volume", "voice_volume", "mute", "music_start"):
                if getattr(op, k) is not None:
                    a[k] = getattr(op, k)
        elif isinstance(op, AddEffect):
            if op.type not in EFFECTS_BY_ID or op.type in ("follow", "person_zoom", "spotlight"):
                raise ManualError(f"'{op.type}' can't be added by hand here (unknown, or needs person tracking — "
                                  "ask in the chat)")
            for target in _segments_in(timeline, op.start, op.end):
                data["effects"].append(Effect(type=op.type, target=target).model_dump())
        elif isinstance(op, RemoveEffect):
            data["effects"] = [e for e in data["effects"] if e["type"] != op.type]
        elif isinstance(op, SetTransition):
            fades = [t for t in data["transitions"] if t["after"] < 0]
            if op.type is None:
                data["transitions"] = fades
            else:
                if op.type not in TRANSITIONS_BY_ID:
                    raise ManualError(f"unknown transition '{op.type}'")
                durs = [e.duration for e in timeline]
                new = []
                for i in range(len(timeline) - 1):
                    limit = 0.5 * min(durs[i], durs[i + 1]) - 0.01
                    if limit >= 0.12:
                        new.append(Transition(type=op.type, after=i, duration=round(min(op.duration, limit), 3)).model_dump())
                data["transitions"] = fades + new
        elif isinstance(op, SetLook):
            if op.preset not in LUT_LOOKS and op.preset not in ("warm", "cool", "cinematic", "vintage", "bw", "vivid",
                                                                 "sepia", "none"):
                raise ManualError(f"unknown look '{op.preset}'")
            data["color"]["preset"] = op.preset
        elif isinstance(op, SetStyle):
            if op.style is not None and op.style not in STYLES:
                raise ManualError(f"unknown style '{op.style}'")
            if op.style is None:
                data["overlays"], data["style"] = [], None
            else:
                data = apply_style(EditPlan.model_validate(data), op.style, keep_color=True).to_json()
        elif isinstance(op, DeleteSegment | SetSpeed | MoveSegment):
            order = sorted(range(len(data["clips"])), key=lambda i: data["clips"][i]["order"])
            if op.index >= len(order):
                raise ManualError(f"there is no clip #{op.index} on the timeline")
            if isinstance(op, DeleteSegment):
                if len(order) == 1:
                    raise ManualError("can't delete the only clip")
                victim = order.pop(op.index)
                data["clips"] = [c for i, c in enumerate(data["clips"]) if i != victim]
                order = sorted(range(len(data["clips"])), key=lambda i: data["clips"][i]["order"])
                data["transitions"] = [t for t in data["transitions"] if t["after"] < 0]  # re-add with set_transition
                data["effects"] = [e for e in data["effects"] if e["target"] == -1]
            elif isinstance(op, SetSpeed):
                data["clips"][order[op.index]]["speed"] = op.speed
            else:
                item = order.pop(op.index)
                order.insert(min(op.to, len(order)), item)
                data["transitions"] = [t for t in data["transitions"] if t["after"] < 0]
            for rank, i in enumerate(order):
                data["clips"][i]["order"] = rank
        notes.append(describe(op))
        _fit_text(data)
    if timing_changed and retime_captions is not None and any(t["kind"] == "caption" for t in data["text"]):
        style = next(t["style"] for t in data["text"] if t["kind"] == "caption")
        fresh = retime_captions(EditPlan.model_validate({**data, "text": []}))
        data["text"] = [t for t in data["text"] if t["kind"] != "caption"] + [
            {**c.model_dump(), "style": style} for c in fresh]
        notes.append(f"captions re-timed to the new cut ({len(fresh)})")
    try:
        from .engines.stack import resolve

        resolved, stack_notes = resolve(EditPlan.model_validate(data))
        return resolved, notes + [n for n in stack_notes if not n.startswith("effects ordered")]
    except ValueError as exc:
        raise ManualError(f"that change makes an invalid edit: {str(exc)[:200]}") from exc
