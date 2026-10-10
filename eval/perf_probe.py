"""Performance probe: one real edit of a 1 / 5 / 20 minute 1080p clip (whole workflow: analyze, plan, ONE FFmpeg
encode, review). Measures wall time per stage, peak memory of this Python process and of the FFmpeg processes.

    backend/.venv/Scripts/python.exe eval/perf_probe.py 1 5 20      # minutes; writes eval/results/perf.json

The source is generated (testsrc2 1080p30 + a tone), so speech-to-text has nothing to transcribe: a talking-head
clip of the same length takes longer (Vosk ~0.3-0.5x real time on this laptop, see TEST_REPORT). No new packages:
memory comes from Windows' own GetProcessMemoryInfo / tasklist. The generated clips are deleted afterwards.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_PROVIDER", "rules")
os.environ.setdefault("PLANNER_MODE", "mock")


from cutmind.agents.director import NullTracker  # noqa: E402

from cutmind.ffmpeg_utils import decode_check, ffmpeg_bin, probe  # noqa: E402

PROMPT = "vertical banao blur sides ke saath, warm karo, zoom in 2 se 6 sec, music lagao, fade in fade out, progress bar"


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def own_peak_mb() -> float:
    if platform.system() != "Windows":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    c = _PMC()
    c.cb = ctypes.sizeof(c)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE  # the default int return truncates the 64-bit pseudo-handle
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
    return c.PeakWorkingSetSize / 2**20


class FfmpegWatch(threading.Thread):
    """Polls the memory of running ffmpeg.exe processes once a second (sum of all; the peak is kept)."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak_mb, self._stop = 0.0, threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/FO", "CSV", "/NH"],
                                     capture_output=True, text=True, timeout=5).stdout
                kb = sum(int(line.split('","')[-1].strip('"\r K').replace(",", "").replace("\xa0", "") or 0)
                         for line in out.splitlines() if line.startswith('"ffmpeg'))
                self.peak_mb = max(self.peak_mb, kb / 1024)
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(1.0)

    def stop(self) -> None:
        self._stop.set()


class Timer(NullTracker):
    """Collects the workflow's own node_completed events (real ms per node; render / review can run twice)."""

    def __init__(self) -> None:
        self.ms: dict[str, int] = {}

    def event(self, kind: str, **data: object) -> None:
        if kind == "node_completed":
            n = str(data["node"])
            self.ms[n] = self.ms.get(n, 0) + int(data["ms"])  # type: ignore[call-overload]


def make_clip(minutes: float, d: Path) -> Path:
    f = d / f"src_{minutes:g}min.mp4"
    s = int(minutes * 60)
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=30:d={s}",
                    "-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=48000:duration={s}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(f)], check=True)
    return f


def one(minutes: float, d: Path) -> dict:
    t0 = time.monotonic()
    src = make_clip(minutes, d)
    gen = time.monotonic() - t0
    # the Tier 1 path: prompt → tool calls → one render (no AI step); Director path: see TEST_REPORT checkpoint 2
    from cutmind.renderer import render
    from cutmind.tools import engine
    from cutmind.tools.engine import ToolCtx
    from cutmind.tools.parse import parse

    watch = FfmpegWatch()
    watch.start()
    t1 = time.monotonic()
    calls = parse(PROMPT)["calls"]
    plan0 = engine.first_plan(["A"], {"A": probe(src).duration}, "16:9", 1080)
    ctx = ToolCtx(sources={"A": src}, gen_dir=d / "gen", clip_ids=["A"],
                  music_dirs=[ROOT / "backend" / "assets" / "music"])
    plan, _applied = engine.run(plan0, calls, ctx)
    t_plan = time.monotonic() - t1
    out = render(plan, ctx.sources, d / "work", d / f"out_{minutes:g}.mp4", [ROOT / "backend" / "assets" / "music"])
    wall = time.monotonic() - t1
    watch.stop()
    ok, _ = decode_check(out)
    info = probe(out)
    stages = {"parse+plan": round(t_plan, 1), "render": round(wall - t_plan, 1), "calls": [c["id"] for c in calls]}
    return {"minutes": minutes, "source": "1920x1080 30fps testsrc2 + tone", "generate_s": round(gen, 1),
            "edit_wall_s": round(wall, 1), "x_realtime": round(wall / (minutes * 60), 3),
            "output_s": round(info.duration, 1), "output": f"{info.width}x{info.height}", "plays": ok,
            "python_peak_mb": round(own_peak_mb()), "ffmpeg_peak_mb": round(watch.peak_mb),
            "stages": stages}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    mins = [float(a) for a in sys.argv[1:]] or [1, 5, 20]
    out = ROOT / "eval" / "results" / "perf.json"
    old = json.loads(out.read_text(encoding="utf-8")).get("runs", []) if out.exists() else []
    rows = [r for r in old if r["minutes"] not in mins]  # run one length per process: the memory peak is per process
    for m in mins:
        with tempfile.TemporaryDirectory(prefix="cutmind_perf_") as td:  # deleted afterwards (small disk)
            r = one(m, Path(td))
        print(json.dumps(r))
        rows.append(r)
        out.write_text(json.dumps({"cpu": platform.processor(), "cores": os.cpu_count(), "prompt": PROMPT,
                                   "runs": sorted(rows, key=lambda r: r["minutes"])}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
