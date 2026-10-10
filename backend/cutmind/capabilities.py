"""CapabilityManager: what can THIS machine do? Detected at startup, served at GET /capabilities.

The app is CPU-first. A GPU is never required; features that would need one are reported as unavailable with
the reason and the CPU fallback that is used instead.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import Settings
from .ffmpeg_utils import ffmpeg_available
from .local_llm import available_ram_mb, local_llm_status


def total_ram_mb() -> int | None:
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="ascii") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        if os.name == "nt":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = _MemStatus()
            stat.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
                return int(stat.ullTotalPhys // (1024 * 1024))
    except Exception:  # noqa: BLE001
        return None
    return None


def detect_gpu() -> dict[str, Any]:
    """NVIDIA via nvidia-smi; ONNX Runtime GPU providers. Never raises."""
    out: dict[str, Any] = {"gpu": False, "cuda": False, "name": None, "vram_mb": None, "onnx_providers": []}
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            r = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                name, mem = [x.strip() for x in r.stdout.splitlines()[0].split(",")[:2]]
                out.update(gpu=True, cuda=True, name=name, vram_mb=int(float(mem)))
        except Exception:  # noqa: BLE001
            pass
    try:
        import onnxruntime as ort

        out["onnx_providers"] = ort.get_available_providers()
        if any(p in out["onnx_providers"] for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "ROCMExecutionProvider")):
            out["gpu"] = True
    except Exception:  # noqa: BLE001
        pass
    return out


def _whisper_ok() -> bool:
    try:
        from .agents.analyzer import import_faster_whisper

        import_faster_whisper()
        return True
    except Exception:  # noqa: BLE001
        return False


@dataclass
class CapabilityProfile:
    os: str
    cpu_threads: int
    ram_total_mb: int | None
    ram_free_mb: int | None
    disk_free_gb: float
    gpu: bool
    cuda: bool
    gpu_name: str | None
    vram_mb: int | None
    ffmpeg: bool
    transcription: bool
    llm: dict[str, Any]
    features: dict[str, str] = field(default_factory=dict)
    choices: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect(settings: Settings) -> CapabilityProfile:
    gpu = detect_gpu()
    ff = ffmpeg_available()
    stt = settings.enable_transcription and _whisper_ok()
    llm = local_llm_status(settings) if settings.planner_mode == "local" else {"model": None, "available": None,
                                                                              "note": "rules planner (PLANNER_MODE=mock)"}
    cpu = os.cpu_count() or 1
    from .renderer import render_workers

    gpu_msg = "GPU feature unavailable — using CPU/local fallback"
    features = {
        "video_editing": "available" if ff else "unavailable: FFmpeg not found",
        "transcription": "available (faster-whisper on CPU)" if stt else "unavailable: faster-whisper missing — edits work, no captions",
        "captions": "available" if stt else "unavailable (needs transcription)",
        "local_llm_planner": ("available" if llm.get("available") else "not downloaded — rules planner is used") if settings.planner_mode == "local"
        else "off (rules planner)",
        "slow_motion": "available (FFmpeg speed change)" + ("" if gpu["gpu"] else "; AI interpolation: " + gpu_msg),
        "upscaling": "available (FFmpeg lanczos)" + ("" if gpu["gpu"] else "; AI upscaling: " + gpu_msg),
        "video_generation": "not shipped" if gpu["gpu"] else f"disabled — {gpu_msg}",
        "image_generation": "not shipped" if gpu["gpu"] else f"disabled — {gpu_msg}",
    }
    choices = {"render_workers": render_workers(), "proxy_short_side": 720, "whisper_model": settings.whisper_model,
               "llm_repo": llm.get("model"), "planner_mode": settings.planner_mode}
    disk = shutil.disk_usage(settings.data_dir if settings.data_dir.exists() else ".")
    return CapabilityProfile(
        os=f"{platform.system()} {platform.release()}", cpu_threads=cpu, ram_total_mb=total_ram_mb(),
        ram_free_mb=available_ram_mb(), disk_free_gb=round(disk.free / 1e9, 1), gpu=gpu["gpu"], cuda=gpu["cuda"],
        gpu_name=gpu["name"], vram_mb=gpu["vram_mb"], ffmpeg=ff, transcription=stt, llm=llm, features=features,
        choices=choices)
