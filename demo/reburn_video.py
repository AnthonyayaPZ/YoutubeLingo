from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def ffmpeg_subtitles_filter(path: Path) -> str:
    p = str(path.resolve()).replace("\\", "/")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    parts = [f"subtitles='{p}'", "charenc=UTF-8"]

    fonts_dir = os.getenv("SUBTITLE_FONTSDIR", "").strip()
    if fonts_dir:
        d = str(Path(fonts_dir).expanduser().resolve()).replace("\\", "/")
        d = d.replace(":", "\\:").replace("'", "\\'")
        parts.append(f"fontsdir='{d}'")

    font_name = os.getenv("SUBTITLE_FONT", "").strip()
    if not font_name and os.name != "nt":
        font_name = "Noto Sans CJK SC"
    if font_name:
        escaped_font = font_name.replace("'", "\\'").replace(":", "\\:")
        parts.append(f"force_style='FontName={escaped_font}'")

    return ":".join(parts)


def probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"ffprobe failed for {path}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return float(proc.stdout.strip())


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit={proc.returncode})\n{' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    default_video = project_root / "video_2.mp4"
    default_srt = project_root / "output" / "video_2_Bilingual.srt"
    default_audio = project_root / "output" / "video_2_Shadowing.mp3"
    default_output = project_root / "output" / "video_2_Reburned.mp4"

    parser = argparse.ArgumentParser(description="Re-burn subtitles onto an existing video.")
    parser.add_argument("--video", default=str(default_video), help="Source video path.")
    parser.add_argument("--srt", default=str(default_srt), help="Subtitle .srt path.")
    parser.add_argument(
        "--audio",
        default=str(default_audio),
        help="Optional replacement audio path (mp3/aac/wav). If missing, keep source audio.",
    )
    parser.add_argument("--out", default=str(default_output), help="Output video path.")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg/ffprobe not found in PATH.")

    video_path = Path(args.video).expanduser().resolve()
    srt_path = Path(args.srt).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    audio_path = Path(args.audio).expanduser().resolve() if args.audio else None

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not srt_path.exists():
        raise FileNotFoundError(f"Subtitle not found: {srt_path}")
    if audio_path is not None and not audio_path.exists():
        audio_path = None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    video_duration = probe_duration(video_path)
    audio_duration = probe_duration(audio_path) if audio_path is not None else video_duration
    extend_sec = max(0.0, audio_duration - video_duration)

    sub_filter = ffmpeg_subtitles_filter(srt_path)
    if extend_sec > 0.01:
        vf = f"tpad=stop_mode=clone:stop_duration={extend_sec:.3f},{sub_filter}"
    else:
        vf = sub_filter

    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    if audio_path is not None:
        cmd.extend(["-i", str(audio_path)])

    cmd.extend(
        [
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
        ]
    )

    if audio_path is not None:
        cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-ar", "48000", "-ac", "2"])
    else:
        cmd.extend(["-c:a", "copy"])

    cmd.extend(["-movflags", "+faststart", str(out_path)])

    print(f"Video: {video_path}")
    print(f"Subtitle: {srt_path}")
    if audio_path is not None:
        print(f"Audio: {audio_path}")
    print(f"Output: {out_path}")
    print(f"Applying filter: {vf}")
    run(cmd)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
