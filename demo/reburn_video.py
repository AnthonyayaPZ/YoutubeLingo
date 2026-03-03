from __future__ import annotations

import argparse
import os
import re
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


_SRT_TIME_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2},\d{3})$"
)


def parse_srt_entries(path: Path) -> list[tuple[float, float, str]]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries: list[tuple[float, float, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.isdigit():
            i += 1
            if i >= len(lines):
                break
            line = lines[i].strip()
        m = _SRT_TIME_RE.match(line)
        if not m:
            i += 1
            continue
        start = parse_srt_ts(m.group("start"))
        end = parse_srt_ts(m.group("end"))
        i += 1
        texts: list[str] = []
        while i < len(lines) and lines[i].strip():
            texts.append(lines[i].rstrip("\n"))
            i += 1
        text = "\n".join(texts).strip()
        entries.append((start, end, text))
    return entries


def parse_srt_ts(value: str) -> float:
    h, m, s_ms = value.split(":")
    s, ms = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def build_segments_from_bilingual_srt(
    entries: list[tuple[float, float, str]],
    source_video_duration: float,
    num_chunks: int | None = None,
) -> list[tuple[float, float, float]]:
    """
    Build segments as (source_start, source_end, freeze_duration).
    Assumes odd/even SRT entries are [EN+ZH original clip] then [ZH freeze clip].
    """
    segments: list[tuple[float, float, float]] = []
    cursor = 0.0
    idx = 0
    built = 0
    while idx < len(entries):
        if num_chunks is not None and built >= num_chunks:
            break
        en_start, en_end, _ = entries[idx]
        en_duration = max(0.0, en_end - en_start)
        zh_duration = 0.0
        if idx + 1 < len(entries):
            zh_start, zh_end, _ = entries[idx + 1]
            zh_duration = max(0.0, zh_end - zh_start)

        src_start = cursor
        src_end = min(cursor + en_duration, source_video_duration)
        if src_end > src_start:
            segments.append((src_start, src_end, zh_duration))
            built += 1
        cursor = src_end
        if cursor >= source_video_duration:
            break
        idx += 2
    return segments


def build_freeze_filtergraph(
    segments: list[tuple[float, float, float]],
    subtitle_filter: str,
) -> str:
    if not segments:
        return f"[0:v]{subtitle_filter}[vout]"

    chain: list[str] = []
    refs: list[str] = []
    for i, (src_start, src_end, freeze_sec) in enumerate(segments):
        ref = f"v{i}"
        refs.append(f"[{ref}]")
        chain.append(
            f"[0:v]trim=start={src_start:.3f}:end={src_end:.3f},"
            f"setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={freeze_sec:.3f}[{ref}]"
        )
    concat_inputs = "".join(refs)
    chain.append(f"{concat_inputs}concat=n={len(segments)}:v=1:a=0[vcat]")
    chain.append(f"[vcat]{subtitle_filter}[vout]")
    return ";".join(chain)


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
    parser.add_argument(
        "--num_chunks",
        type=int,
        default=None,
        help="Only process the first N bilingual chunks from subtitle file (for quick checks).",
    )
    parser.add_argument("--out", default=str(default_output), help="Output video path.")
    args = parser.parse_args()

    if args.num_chunks is not None and args.num_chunks <= 0:
        raise RuntimeError("--num_chunks must be greater than 0.")

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
    sub_filter = ffmpeg_subtitles_filter(srt_path)
    entries = parse_srt_entries(srt_path)
    segments = build_segments_from_bilingual_srt(
        entries,
        source_video_duration=video_duration,
        num_chunks=args.num_chunks,
    )
    filter_complex = build_freeze_filtergraph(segments, subtitle_filter=sub_filter)

    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    if audio_path is not None:
        cmd.extend(["-i", str(audio_path)])

    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
        ]
    )

    if audio_path is not None:
        cmd.extend(["-map", "1:a:0", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest"])
    else:
        cmd.extend(["-c:a", "copy"])

    cmd.extend(["-movflags", "+faststart", str(out_path)])

    print(f"Video: {video_path}")
    print(f"Subtitle: {srt_path}")
    if audio_path is not None:
        print(f"Audio: {audio_path}")
    print(f"Output: {out_path}")
    print(f"Segments: {len(segments)}")
    print("Applying freeze+subtitle filtergraph...")
    run(cmd)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
