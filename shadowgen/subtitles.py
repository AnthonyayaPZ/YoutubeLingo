from __future__ import annotations

from pathlib import Path

from shadowgen.models import SemanticChunk, SubtitleEntry
from shadowgen.utils import format_srt_timestamp


def build_subtitle_entries(chunks: list[SemanticChunk]) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    for chunk in chunks:
        bilingual = f"{chunk.text}\n{chunk.translation}".strip()
        zh_only = chunk.translation or chunk.text
        entries.append(
            SubtitleEntry(
                start=chunk.rebuilt_original_start,
                end=chunk.rebuilt_original_end,
                text=bilingual,
            )
        )
        entries.append(
            SubtitleEntry(
                start=chunk.rebuilt_tts_start,
                end=chunk.rebuilt_tts_end,
                text=zh_only,
            )
        )
    return entries


def write_srt(entries: list[SubtitleEntry], output_path: Path) -> None:
    lines: list[str] = []
    for idx, entry in enumerate(entries, start=1):
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(entry.start)} --> {format_srt_timestamp(entry.end)}")
        lines.append(entry.text)
        lines.append("")
    # utf-8-sig improves subtitle parser compatibility on some ffmpeg/libass builds.
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")
