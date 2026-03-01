from __future__ import annotations

import html
import re
from pathlib import Path

from shadowgen.models import SpeechSegment, TranscriptionResult
from shadowgen.utils import logger, run_command

_TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


def download_and_parse_english_subtitles(
    url: str,
    temp_dir: Path,
    timeout_sec: int,
    cookie_args: list[str] | None = None,
) -> TranscriptionResult | None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(temp_dir / "yt_subtitle.%(ext)s")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--no-progress",
        "--no-playlist",
        *(cookie_args or []),
        "--write-sub",
        "--write-auto-sub",
        "--sub-langs",
        "en.*,en",
        "--sub-format",
        "vtt",
        "--output",
        output_template,
        url,
    ]

    proc = run_command(cmd, timeout_sec=timeout_sec, check=False)
    if proc.returncode != 0:
        logger.info("No downloadable English subtitles found (yt-dlp exit=%s).", proc.returncode)
        return None

    subtitle_path = _select_best_english_vtt(temp_dir)
    if subtitle_path is None:
        logger.info("Subtitle download succeeded but no English .vtt file was found.")
        return None

    segments = _parse_vtt_segments(subtitle_path)
    if not segments:
        logger.info("English subtitle file exists but contains no usable cues: %s", subtitle_path)
        return None

    logger.info("Using YouTube English subtitles: %s (%s segments)", subtitle_path, len(segments))
    return TranscriptionResult(segments=segments, words=[], language="en")


def _select_best_english_vtt(temp_dir: Path) -> Path | None:
    candidates = sorted(temp_dir.glob("yt_subtitle*.vtt"))
    if not candidates:
        return None

    # Prefer manually uploaded English subtitles, then regional variants, then auto-generated.
    exact = [p for p in candidates if p.name.endswith(".en.vtt")]
    regional = [
        p
        for p in candidates
        if re.search(r"\.en[-_][A-Za-z0-9]+\.vtt$", p.name) or ".en." in p.name
    ]
    auto = [p for p in candidates if ".en-orig." in p.name or ".en-auto." in p.name]

    for bucket in (exact, regional, auto, candidates):
        if bucket:
            return bucket[0]
    return None


def _parse_vtt_segments(path: Path) -> list[SpeechSegment]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    segments: list[SpeechSegment] = []
    cue_lines: list[str] = []
    start = 0.0
    end = 0.0
    seg_id = 1

    def flush() -> None:
        nonlocal cue_lines, seg_id
        if not cue_lines:
            return
        text = _normalize_cue_text(" ".join(cue_lines))
        cue_lines = []
        if not text:
            return
        segments.append(SpeechSegment(id=seg_id, start=start, end=end, text=text))
        seg_id += 1

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        if line == "WEBVTT" or line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        match = _TIMING_RE.match(line)
        if match:
            flush()
            start = _parse_timestamp(match.group("start"))
            end = _parse_timestamp(match.group("end"))
            continue
        if "-->" in line:
            continue
        if line.isdigit():
            continue
        cue_lines.append(line)

    flush()
    return segments


def _parse_timestamp(value: str) -> float:
    text = value.replace(",", ".")
    parts = text.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    m, s = parts
    return int(m) * 60 + float(s)


def _normalize_cue_text(text: str) -> str:
    cleaned = _TAG_RE.sub("", text)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
