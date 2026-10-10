"""Download the planner LLM (GGUF) from Hugging Face and verify its SHA-256.

    python scripts/download_models.py                 # the default model from models.json
    python scripts/download_models.py qwen3-4b phi-4-mini
    python scripts/download_models.py --all
    python scripts/download_models.py --verify        # check files already on disk

Files go to backend/models/ (or $CUTMIND_MODELS_DIR). No login is needed for these public, permissively licensed
repos. A file whose checksum does not match is deleted, never used.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "models.json"


def models_dir() -> Path:
    return Path(os.environ.get("CUTMIND_MODELS_DIR") or ROOT / "models")


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(name: str) -> bool:
    m = manifest()["models"][name]
    f = models_dir() / m["file"]
    return f.exists() and f.stat().st_size == m["size"] and sha256(f) == m["sha256"]


def download(name: str) -> Path:
    m = manifest()["models"][name]
    out = models_dir() / m["file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size == m["size"] and sha256(out) == m["sha256"]:
        print(f"{name}: already here, checksum OK")
        return out
    url = f"https://huggingface.co/{m['repo']}/resolve/main/{m['file']}"
    part = out.with_suffix(out.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    print(f"{name}: downloading {m['size'] / 1e9:.2f} GB from {m['repo']} ({m['license']})" + (" (resuming)" if have else ""))
    with urllib.request.urlopen(req, timeout=60) as r, part.open("ab" if have else "wb") as fh:
        done = have
        while chunk := r.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            if done % (100 << 20) < (1 << 20):
                print(f"  {done / 1e9:.2f} / {m['size'] / 1e9:.2f} GB", flush=True)
    digest = sha256(part)
    if digest != m["sha256"]:
        part.unlink(missing_ok=True)
        raise SystemExit(f"{name}: CHECKSUM MISMATCH ({digest}) — file deleted")
    part.replace(out)
    print(f"{name}: OK {out}")
    return out


def main(argv: list[str]) -> None:
    names = list(manifest()["models"]) if "--all" in argv else [a for a in argv if not a.startswith("--")]
    names = names or [manifest()["default"]]
    if "--verify" in argv:
        for n in names:
            print(n, "OK" if verify(n) else "missing / bad checksum")
        return
    for n in names:
        download(n)


if __name__ == "__main__":
    main(sys.argv[1:])
