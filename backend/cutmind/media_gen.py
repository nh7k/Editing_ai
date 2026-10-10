"""Generate copyright-free test clips and royalty-free music beds using only FFmpeg (+ local OS TTS).

Run:  python -m cutmind.media_gen <out_dir>      (clips)
      python -m cutmind.media_gen --music <dir>  (music beds for backend/assets/music)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .ffmpeg_utils import run_ffmpeg

SPEECH_SSML = (
    '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
    "Welcome to our trip to the mountains. <break time=\"2000ms\"/>"
    "Um, the weather was amazing today. <break time=\"1800ms\"/>"
    "Let's go and explore the old town together."
    "</speak>"
)
SPEECH_TEXT_FALLBACK = (
    "Welcome to our trip to the mountains. ... Um, the weather was amazing today. ... "
    "Let's go and explore the old town together."
)


VOICE_PROMPT_TEXT = "Make a vertical reel with captions and warm colours."


def make_speech_wav(out: Path, text: str | None = None) -> str:
    """Synthesize speech with a free local TTS (default: the 3-sentence clip script; `text`: anything else).
    Returns the engine used, or 'none' (tone fallback)."""
    ssml = SPEECH_SSML if text is None else (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">' + text + "</speak>")
    if platform.system() == "Windows":
        # SSML goes through a file so quotes/apostrophes never hit PowerShell parsing
        ssml_file = out.with_suffix(".ssml")
        ssml_file.write_text(ssml, encoding="utf-8")
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = 0; "
            f"$s.SetOutputToWaveFile('{out.resolve()}'); "
            f"$s.SpeakSsml([IO.File]::ReadAllText('{ssml_file.resolve()}')); $s.Dispose()"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
        ssml_file.unlink(missing_ok=True)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 10000:
            return "windows-sapi"
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            r = subprocess.run([exe, "-w", str(out), text or SPEECH_TEXT_FALLBACK], capture_output=True, timeout=120)
            if r.returncode == 0 and out.exists():
                return exe
    if platform.system() == "Darwin" and shutil.which("say"):
        aiff = out.with_suffix(".aiff")
        subprocess.run(["say", "-o", str(aiff), text or SPEECH_TEXT_FALLBACK], check=False, timeout=120)
        if aiff.exists():
            run_ffmpeg(["-i", str(aiff), str(out)])
            return "macos-say"
    # Fallback: speech-like tone bursts (no real words -> captions cannot be tested)
    run_ffmpeg(["-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*220*t)*(lt(t,2.5)+between(t,4.5,7)+gt(t,9))':s=22050:d=11", str(out)])
    return "none"


def make_clips(out_dir: Path) -> dict[str, Path]:
    """Three ~10s clips with different sizes/fps/audio so every agent has something to do."""
    out_dir.mkdir(parents=True, exist_ok=True)
    speech = out_dir / "speech.wav"
    engine = make_speech_wav(speech)
    (out_dir / "tts_engine.txt").write_text(engine, encoding="utf-8")

    a = out_dir / "clip_a_talk.mp4"
    # 1280x720@30 test pattern + spoken narration with pauses (silence + filler word "Um")
    run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30",
        "-i", str(speech),
        "-filter_complex", "[1:a]aresample=48000,apad=pad_dur=0.6[a]",
        "-map", "0:v", "-map", "[a]", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(a),
    ])
    b = out_dir / "clip_b_tone.mp4"
    # 640x480 (4:3) fractal motion + 440 Hz tone with a 2.5 s silent gap in the middle
    run_ffmpeg([
        "-f", "lavfi", "-i", "mandelbrot=s=640x480:r=30",
        "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*440*t)*(lt(t,3)+gt(t,5.5))':s=48000",
        "-t", "8", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(b),
    ])
    c = out_dir / "clip_c_scenes.mp4"
    # 1280x720@25 with three hard scene changes + 120 BPM click track
    run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=0x3366cc:s=1280x720:r=25:d=4",
        "-f", "lavfi", "-i", "smptehdbars=s=1280x720:r=25:d=4",
        "-f", "lavfi", "-i", "testsrc=s=1280x720:r=25:d=4",
        "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*1000*t)*lt(mod(t\\,0.5)\\,0.03)':s=48000:d=12",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(c),
    ])
    return {"a": a, "b": b, "c": c, "speech": speech}


def make_silent_clip(out: Path, seconds: float = 4) -> Path:
    """Video without an audio stream."""
    run_ffmpeg(["-f", "lavfi", "-i", f"testsrc=s=640x360:r=30:d={seconds}", "-c:v", "libx264",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
    return out


def make_corrupt_file(out: Path) -> Path:
    out.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"this is not really a video" * 200)
    return out


def make_music(out_dir: Path) -> list[Path]:
    """Two synthesized, royalty-free music beds (public domain — generated here)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    upbeat = out_dir / "upbeat_120bpm.m4a"
    # 120 BPM: kick on every beat, hat on off-beats, C-major pad
    run_ffmpeg([
        "-f", "lavfi", "-i",
        "aevalsrc='0.55*sin(2*PI*55*t)*exp(-14*mod(t,0.5))"
        "+0.08*sin(2*PI*7000*t)*exp(-60*mod(t+0.25,0.5))"
        "+0.06*(sin(2*PI*261.63*t)+sin(2*PI*329.63*t)+sin(2*PI*392*t))':s=44100:d=40",
        "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(upbeat),
    ])
    calm = out_dir / "calm_80bpm.m4a"
    run_ffmpeg([
        "-f", "lavfi", "-i",
        "aevalsrc='0.35*sin(2*PI*65.4*t)*exp(-6*mod(t,0.75))"
        "+0.07*(sin(2*PI*220*t)+sin(2*PI*277.18*t)+sin(2*PI*329.63*t))*(0.7+0.3*sin(2*PI*0.1*t))':s=44100:d=40",
        "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(calm),
    ])
    return [upbeat, calm]


def make_song(out: Path, bpm: float, seconds: float = 30.0, drop_at: float | None = None, busy: bool = False) -> Path:
    """A synthesized test song: kick on every beat, hats on the off-beat (16ths when `busy`), a pad. With `drop_at`
    the drums only start there (quiet intro → drop)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    b = 60.0 / bpm
    gate = f"gte(t,{drop_at:g})" if drop_at is not None else "1"
    hats = f"+0.05*sin(2*PI*9000*t)*exp(-90*mod(t,{b / 4:.5f}))" if busy else ""
    expr = (f"(0.6*sin(2*PI*55*t)*exp(-14*mod(t,{b:.5f}))+0.1*sin(2*PI*7000*t)*exp(-60*mod(t+{b / 2:.5f},{b:.5f})){hats})*{gate}"
            f"+0.05*(0.25+0.75*{gate})*(sin(2*PI*261.63*t)+sin(2*PI*329.63*t)+sin(2*PI*392*t))")
    run_ffmpeg(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={seconds:g}", "-ac", "2", "-c:a", "aac", "-b:a", "128k",
                str(out)])
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--music":
        print([str(p) for p in make_music(Path(sys.argv[2]))])
    else:
        target = Path(sys.argv[1] if len(sys.argv) > 1 else "test_media")
        print({k: str(v) for k, v in make_clips(target).items()})
