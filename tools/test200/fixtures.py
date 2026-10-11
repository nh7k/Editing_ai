"""test200 fixtures: generated with FFmpeg (lavfi patterns, tones) and the local Windows TTS only — no copyrighted
media. Writes tools/test200/fixtures/<name>.mp4 and manifest.json with the ground truth of each (duration, size,
fps, audio, cut times, speech segments measured on the generated speech, beat times).

python tools/test200/fixtures.py [--force] [--long]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from cutmind.ffmpeg_utils import detect_silence, probe, run_ffmpeg  # noqa: E402
from cutmind.media_gen import make_corrupt_file, make_song, make_speech_wav  # noqa: E402

OUT = HERE / "fixtures"
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "128k"]
SPEECH = ('Hello friends, welcome to my travel vlog.<break time="1400ms"/> Um, today we are in the mountains.'
          '<break time="1600ms"/> The weather is amazing and the view is beautiful.<break time="1200ms"/>'
          ' Let us go and see the lake.')


def _speech_segments(wav: Path) -> list[list[float]]:
    """Where speech is, measured on the generated wav (the truth for captions / silence checks)."""
    d = probe(wav).duration
    sil = detect_silence(wav, noise_db=-35, min_dur=0.5)
    segs, t = [], 0.0
    for a, b in sil:
        if a - t > 0.2:
            segs.append([round(t, 2), round(a, 2)])
        t = b
    if d - t > 0.2:
        segs.append([round(t, 2), round(d, 2)])
    return segs


def build(force: bool = False, long: bool = False) -> dict[str, dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "manifest.json"
    man: dict[str, dict] = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() and not force else {}

    def make(name: str, fn, **truth) -> None:  # noqa: ANN001
        p = OUT / f"{name}.mp4"
        if force or not p.exists() or name not in man:
            fn(p)
        info = {"path": str(p.relative_to(ROOT)).replace("\\", "/")}
        try:
            pi = probe(p)
            info.update(duration=round(pi.duration, 3), width=pi.width, height=pi.height, fps=round(pi.fps, 2),
                        has_audio=pi.has_audio, has_video=pi.width > 0)
        except Exception as exc:  # noqa: BLE001 — corrupt / audio-only on purpose
            info.update(probe_error=str(exc)[:120])
        info.update(truth)
        man[name] = info

    speech = OUT / "speech.wav"
    if force or not speech.exists():
        engine = make_speech_wav(speech, SPEECH)
        (OUT / "tts_engine.txt").write_text(engine, encoding="utf-8")
    segs = _speech_segments(speech)
    song = OUT / "song120.m4a"
    if force or not song.exists():
        make_song(song, 120, seconds=20)

    make("speech_pauses", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30", "-i", str(speech),
                                                "-filter_complex", "[1:a]aresample=48000,apad=pad_dur=0.5[a]",
                                                "-map", "0:v", "-map", "[a]", "-shortest", *ENC, *AAC, str(p)]),
         speech_segments=segs, words=["hello", "welcome", "travel", "vlog", "mountains", "weather", "lake"],
         filler_words=["um"])
    make("speech_music", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30", "-i", str(speech),
                                               "-i", str(song), "-filter_complex",
                                               "[1:a]aresample=48000[v];[2:a]aresample=48000,volume=0.35[m];"
                                               "[v][m]amix=inputs=2:duration=first[a]", "-map", "0:v", "-map", "[a]",
                                               "-shortest", *ENC, *AAC, str(p)]),
         speech_segments=segs)
    make("music_beats", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=10", "-i", str(song),
                                              "-map", "0:v", "-map", "1:a", "-t", "10", *ENC, *AAC, str(p)]),
         bpm=120, beats=[round(i * 0.5, 2) for i in range(20)])
    # 4 shots, distinct flat colours + pattern, hard cuts at 2.5 / 5 / 7.5 s, a 440 Hz tone
    make("multishot", lambda p: run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=0xC0392B:s=640x360:r=30:d=2.5", "-f", "lavfi", "-i", "smptebars=s=640x360:r=30:d=2.5",
        "-f", "lavfi", "-i", "color=c=0x2471A3:s=640x360:r=30:d=2.5", "-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=2.5",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
        "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]", "-map", "[v]", "-map", "4:a",
        *ENC, *AAC, str(p)]), cuts=[2.5, 5.0, 7.5])
    make("silent_single", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi",
                                                "-i", "anullsrc=r=48000:cl=stereo", "-t", "6", *ENC, *AAC, str(p)]),
         speech_segments=[])
    make("noisy_speech", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30", "-i", str(speech),
                                               "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.08:r=48000",
                                               "-filter_complex", "[1:a]aresample=48000[s];[s][2:a]amix=inputs=2:duration=first[a]",
                                               "-map", "0:v", "-map", "[a]", "-shortest", *ENC, *AAC, str(p)]),
         speech_segments=segs)
    make("dark", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6,eq=brightness=-0.35",
                                       "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=6",
                                       *ENC, *AAC, str(p)]))
    make("bright", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6,eq=brightness=0.3",
                                         "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=6",
                                         *ENC, *AAC, str(p)]))
    make("shaky", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=720x420:r=30:d=6",
                                        "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=6",
                                        "-filter_complex", "[0:v]crop=640:360:40+30*sin(n*1.7):30+25*sin(n*2.3)[v]",
                                        "-map", "[v]", "-map", "1:a", *ENC, *AAC, str(p)]))
    make("portrait", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=360x640:r=30", "-i", str(speech),
                                           "-map", "0:v", "-map", "1:a", "-shortest", *ENC, *AAC, str(p)]),
         speech_segments=segs)
    make("square", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=480x480:r=30:d=6",
                                         "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=6",
                                         *ENC, *AAC, str(p)]))
    def rotated(p: Path) -> None:  # a phone video: stored landscape, "display rotation" metadata 90°
        tmp = p.with_name("rot_src.mp4")
        run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                    "sine=frequency=330:sample_rate=48000:duration=6", *ENC, *AAC, str(tmp)])
        run_ffmpeg(["-display_rotation", "90", "-i", str(tmp), "-c", "copy", str(p)])
        tmp.unlink(missing_ok=True)

    make("rotated", rotated, rotation=90)
    make("vfr", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                                      "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=6",
                                      "-vf", "setpts='if(lt(N,60),PTS,PTS*1.6)'", "-fps_mode", "vfr",
                                      *ENC, *AAC, str(p)]))
    make("k4", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=3840x2160:r=30:d=3",
                                     "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=3",
                                     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *AAC, str(p)]))
    make("fps60", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=60:d=5",
                                        "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=5",
                                        *ENC, *AAC, str(p)]))
    make("no_audio", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", *ENC, str(p)]))
    make("audio_only", lambda p: run_ffmpeg(["-i", str(speech), "-c:a", "aac", "-f", "mp4", str(p)]))
    make("corrupt", lambda p: make_corrupt_file(p))
    make("short1s", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=1",
                                          "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=1",
                                          *ENC, *AAC, str(p)]))
    if long:
        make("long5min", lambda p: run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=300",
                                               "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=300",
                                               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                                               *AAC, str(p)]))
    man_path.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


if __name__ == "__main__":
    m = build(force="--force" in sys.argv, long="--long" in sys.argv)
    for k, v in m.items():
        print(k, {x: v.get(x) for x in ("duration", "width", "height", "has_audio", "probe_error")})
