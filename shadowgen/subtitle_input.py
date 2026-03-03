from __future__ import annotations

import html
import re
from pathlib import Path

from shadowgen.models import SpeechSegment, TranscriptionResult
from shadowgen.utils import normalize_spaces

_SRT_TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)
_VTT_TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3}|\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3}|\d{2}:\d{2}[,.]\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_subtitle_file(path: Path) -> TranscriptionResult:
    source = path.expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Subtitle file not found: {source}")

    suffix = source.suffix.lower()
    if suffix == ".srt":
        segments = _parse_srt(source)
    elif suffix == ".vtt":
        segments = _parse_vtt(source)
    else:
        raise RuntimeError(f"Unsupported subtitle format: {source.suffix}. Use .srt or .vtt")

    if not segments:
        raise RuntimeError(f"No usable subtitle cues found in: {source}")
    return TranscriptionResult(segments=segments, words=[], language="en")


def _parse_srt(path: Path) -> list[SpeechSegment]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    segments: list[SpeechSegment] = []
    seg_id = 1
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
        match = _SRT_TIMING_RE.match(line)
        if not match:
            i += 1
            continue
        start = _parse_timestamp(match.group("start"))
        end = _parse_timestamp(match.group("end"))
        i += 1
        text_lines: list[str] = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        text = _clean_text(" ".join(text_lines))
        if text:
            segments.append(SpeechSegment(id=seg_id, start=start, end=end, text=text))
            seg_id += 1
    return segments


def _parse_vtt(path: Path) -> list[SpeechSegment]:
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
        text = _clean_text(" ".join(cue_lines))
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
        match = _VTT_TIMING_RE.match(line)
        if match:
            flush()
            start = _parse_timestamp(match.group("start"))
            end = _parse_timestamp(match.group("end"))
            continue
        if "-->" in line or line.isdigit():
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


def _clean_text(text: str) -> str:
    cleaned = _TAG_RE.sub("", text)
    cleaned = html.unescape(cleaned)
    return normalize_spaces(cleaned)
