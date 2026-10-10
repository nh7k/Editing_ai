"""Templates tab: ready-made edits (a professional brief the agents understand) and "my templates" saved from Copy an
Edit (a blueprint of a video the user liked, plus its soundtrack). Applying one runs a normal edit job."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .editorial import KNOWLEDGE_DIR

BUILTIN_FILE = KNOWLEDGE_DIR / "templates.yaml"
CATEGORY_ORDER = ["Sports", "Travel", "Vlog", "Cinematic", "Social", "Music", "Emotional", "Aesthetic", "Mine"]


class TemplateError(ValueError):
    pass


@lru_cache(maxsize=1)
def builtin() -> list[dict[str, Any]]:
    data = yaml.safe_load(BUILTIN_FILE.read_text(encoding="utf-8")) or {}
    out = []
    for t in data.get("templates", []):
        out.append({**t, "kind": "builtin", "preview_url": f"/templates/{t['id']}/preview"})
    return out


def mine_dir(data_dir: Path) -> Path:
    return data_dir / "templates"


def mine(data_dir: Path) -> list[dict[str, Any]]:
    out = []
    root = mine_dir(data_dir)
    if not root.exists():
        return out
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = d / "template.json"
        if meta.exists():
            try:
                t = json.loads(meta.read_text(encoding="utf-8"))
            except ValueError:
                continue
            out.append({**t, "kind": "mine", "category": "Mine", "preview_url": f"/templates/{t['id']}/preview"})
    return out


def all_templates(data_dir: Path) -> dict[str, Any]:
    items = [*mine(data_dir), *builtin()]
    cats = [c for c in CATEGORY_ORDER if any(t["category"] == c for t in items)]
    return {"templates": items, "categories": cats}


def get(data_dir: Path, tid: str) -> dict[str, Any] | None:
    return next((t for t in all_templates(data_dir)["templates"] if t["id"] == tid), None)


def save_mine(data_dir: Path, name: str, copy_dir: Path, music_dir: Path) -> dict[str, Any]:
    """Keep a Copy-an-Edit blueprint (+ its soundtrack and a picture) as a template for any project."""
    from .blueprint import load_blueprint

    bp = load_blueprint(copy_dir / "blueprint.json")
    if bp is None:
        raise TemplateError("Pehle ek video upload karke analyse karwao (Copy an Edit).")
    name = re.sub(r"\s+", " ", name).strip()[:60] or bp.name
    tid = "tpl_my_" + uuid.uuid4().hex[:10]
    d = mine_dir(data_dir) / tid
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(copy_dir / "blueprint.json", d / "blueprint.json")
    if bp.song and (music_dir / bp.song).exists():
        shutil.copy2(music_dir / bp.song, d / bp.song)
    thumbs = sorted((copy_dir / "thumbs").glob("*.jpg"), key=lambda p: int(p.stem)) if (copy_dir / "thumbs").exists() else []
    if thumbs:
        shutil.copy2(thumbs[min(len(thumbs) - 1, len(thumbs) // 3)], d / "preview.jpg")
    durs = [s.dur for s in bp.shots]
    t = {"id": tid, "name": name, "description": "; ".join(bp.summary()[1:4]),
         "tags": ["copied", f"{len(bp.shots)} shots"], "duration": round(bp.duration), "aspect": bp.aspect,
         "colors": ["#222222", "#888888"], "prompt": "", "source": bp.name,
         "shot_median": round(sorted(durs)[len(durs) // 2], 2) if durs else 0}
    (d / "template.json").write_text(json.dumps(t), encoding="utf-8")
    return {**t, "kind": "mine", "category": "Mine", "preview_url": f"/templates/{tid}/preview"}


def delete_mine(data_dir: Path, tid: str) -> bool:
    if not tid.startswith("tpl_my_") or not re.fullmatch(r"tpl_my_[0-9a-f]{10}", tid):
        return False
    d = mine_dir(data_dir) / tid
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def install_mine(data_dir: Path, tid: str, copy_dir: Path, music_dir: Path) -> None:
    """Applying a "mine" template: its blueprint + soundtrack become the project's Copy-an-Edit."""
    from .blueprint import load_blueprint

    d = mine_dir(data_dir) / tid
    bp = load_blueprint(d / "blueprint.json")
    if bp is None:
        raise TemplateError("This template is broken (its blueprint is missing).")
    copy_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(d / "blueprint.json", copy_dir / "blueprint.json")
    (copy_dir / "status.json").write_text(json.dumps({"status": "ready", "progress": 1.0}), encoding="utf-8")
    if bp.song and (d / bp.song).exists():
        music_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d / bp.song, music_dir / bp.song)


def preview(data_dir: Path, tid: str, cache: Path) -> Path | None:
    """A picture for the gallery card. Mine: a frame of the liked video. Built-in: a drawn card in its colours."""
    if tid.startswith("tpl_my_"):
        p = mine_dir(data_dir) / tid / "preview.jpg"
        return p if p.exists() else None
    t = next((x for x in builtin() if x["id"] == tid), None)
    if t is None:
        return None
    out = cache / f"{tid}.jpg"
    if out.exists() and out.stat().st_mtime >= BUILTIN_FILE.stat().st_mtime:
        return out
    cache.mkdir(parents=True, exist_ok=True)
    _draw_card(t, out)
    return out


def _draw_card(t: dict[str, Any], out: Path) -> None:
    """9:16 card: a diagonal gradient in the template's colours, a strip of 'shots' showing its pace, its name."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    w, h = 360, 640
    c1, c2 = (np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], np.float32) for c in t.get("colors", ["#333333", "#999999"])[:2])
    yy, xx = np.mgrid[0:h, 0:w]
    k = ((xx / w + yy / h) / 2)[..., None]
    img = Image.fromarray((c1 * (1 - k) + c2 * k).astype(np.uint8))
    dr = ImageDraw.Draw(img, "RGBA")
    # pace strip: fast templates = many thin blocks, slow ones = few wide blocks
    slow = any(x in " ".join(t.get("tags", [])) for x in ("calm", "slow", "cinematic", "vintage", "moody", "emotional"))
    x = 24
    rng = np.random.default_rng(abs(hash(t["id"])) % 2**32)
    while x < w - 24:
        bw = int(rng.integers(40, 90)) if slow else int(rng.integers(14, 34))
        dr.rounded_rectangle([x, 440, min(w - 24, x + bw - 4), 500], 6, fill=(255, 255, 255, 70 + int(rng.integers(0, 80))))
        x += bw
    def font(size: int):  # noqa: ANN202
        for f in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
        return ImageFont.load_default()
    words, lines = t["name"].split(), [""]
    for wd in words:
        if len(lines[-1]) + len(wd) > 11:
            lines.append(wd)
        else:
            lines[-1] = (lines[-1] + " " + wd).strip()
    y = 200
    for ln in lines:
        dr.text((26, y), ln.upper(), font=font(40), fill=(255, 255, 255, 245), stroke_width=2, stroke_fill=(0, 0, 0, 120))
        y += 48
    dr.text((26, 560), f"{t.get('category', '')}  ·  {t.get('aspect', '')}", font=font(20), fill=(255, 255, 255, 220))
    img.convert("RGB").save(out, quality=85)
