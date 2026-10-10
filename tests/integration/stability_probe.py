"""Stability probe: N consecutive edit prompts on ONE project, measuring every output (duration, resolution,
bitrate, streams, decode validity, what the plan kept). Used for the "every edit makes the video shorter / worse"
report (TEST_REPORT.md) — run against a live backend:

    python tests/integration/stability_probe.py http://127.0.0.1:8000 8      # the 8-step sequence
    python tests/integration/stability_probe.py http://127.0.0.1:8000 30     # the 30-step stress run

It makes its own 3 clips with FFmpeg (lavfi: test patterns + a tone, 12 / 9 / 7 s, with audio) in a new project.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from cutmind.ffmpeg_utils import decode_check, ffmpeg_bin, probe  # noqa: E402

STEPS8 = ["add captions", "warm color", "add music", "make it a 9:16 reel", "add fade transitions",
          "remove silence", "change caption style to bold yellow", "add zoom"]
EXTRA = ["thoda slow karo", "ab black and white kar do", "color wapas lao", "text bada karo", "gaane ki awaaz kam karo",
         "thoda bright karo", "end me slow motion", "start me Goa Trip likh do", "thoda fast karo", "vignette lagao",
         "transition hata do", "zoom hata do", "captions hata do", "captions laga do", "music thoda kam karo",
         "last me The End likh do", "warm color karo", "thoda dark karo", "pichla wala dobara bana do", "film grain daalo",
         "film grain hata do", "thoda smooth karo"]


def make_clips(d: Path) -> list[Path]:
    out = []
    for i, (dur, src) in enumerate([(12, "testsrc2"), (9, "smptehdbars"), (7, "testsrc")]):
        f = d / f"clip{i + 1}.mp4"
        subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=s=1280x720:r=30:d={dur}",
                        "-f", "lavfi", "-i", f"sine=frequency={330 + 110 * i}:sample_rate=48000:duration={dur}",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(f)], check=True)
        out.append(f)
    return out


def call(api: str, method: str, path: str, body: dict | None = None, files: list[Path] | None = None) -> tuple[int, dict]:
    if files:
        boundary = "----probe"
        parts = b""
        for f in files:
            parts += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{f.name}\"\r\n"
                      "Content-Type: video/mp4\r\n\r\n").encode() + f.read_bytes() + b"\r\n"
        data, ctype = parts + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"
    else:
        data, ctype = (json.dumps(body).encode() if body is not None else None), "application/json"
    req = urllib.request.Request(api + path, method=method, data=data, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    api, n = sys.argv[1].rstrip("/"), int(sys.argv[2])
    steps = (STEPS8 + EXTRA)[:n] if n > 8 else STEPS8[:n]
    work = Path(tempfile.mkdtemp())
    clips = make_clips(work)
    _, proj = call(api, "POST", "/projects", {"name": f"stability probe {n}"})
    pid = proj["id"]
    code, up = call(api, "POST", f"/projects/{pid}/clips", files=clips)
    assert code == 201, up
    print(f"project {pid}, raw footage {sum(probe(c).duration for c in clips):.1f}s in 3 clips")
    print(f"{'#':>2} {'prompt':38s} {'status':8s} {'dur':>6s} {'res':>9s} {'kbps':>6s} {'a':>2s} {'decode':6s} "
          f"{'shots':>5s} {'match':>6s} note")
    rows = []
    for i, prompt in enumerate(steps, 1):
        t0 = time.time()
        code, r = call(api, "POST", f"/projects/{pid}/edit", {"prompt": prompt})
        if code != 202:
            print(f"{i:2d} {prompt:38s} REJECTED {r.get('error', {}).get('message', '')[:60]}")
            rows.append({"step": i, "prompt": prompt, "status": "rejected"})
            continue
        jid = r["job_id"]
        while True:
            _, j = call(api, "GET", f"/jobs/{jid}")
            if j["status"] in ("done", "failed"):
                break
            time.sleep(1)
        out = ROOT / "data" / "projects" / pid / "output" / f"{jid}.mp4"
        row = {"step": i, "prompt": prompt, "status": j["status"], "secs": round(time.time() - t0, 1)}
        if j["status"] == "done" and out.exists():
            info = probe(out)
            ok, _err = decode_check(out)
            _, plan = call(api, "GET", f"/projects/{pid}/plan")
            plan = plan.get("plan", plan)
            row.update(dur=round(info.duration, 2), res=f"{info.width}x{info.height}",
                       kbps=round(info.size_bytes * 8 / max(info.duration, 0.01) / 1000),
                       audio=info.has_audio, decode=ok, shots=len(plan["clips"]), match=j.get("match_percent"),
                       sources=sorted({c["source"][-4:] for c in plan["clips"]}))
        rows.append(row)
        print(f"{i:2d} {prompt[:38]:38s} {row['status']:8s} {row.get('dur', 0):6.2f} {row.get('res', '-'):>9s} "
              f"{row.get('kbps', 0):6d} {'y' if row.get('audio') else 'n':>2s} {str(row.get('decode')):6s} "
              f"{row.get('shots', 0):5d} {row.get('match') or 0:6.1f} {j.get('error') or ''}")
    report = work / "stability.json"
    report.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("rows:", report)


if __name__ == "__main__":
    main()
