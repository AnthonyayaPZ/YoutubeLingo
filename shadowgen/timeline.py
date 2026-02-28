from __future__ import annotations

from shadowgen.models import SemanticChunk


def rebuild_timeline(chunks: list[SemanticChunk]) -> list[SemanticChunk]:
    cursor = 0.0
    for chunk in chunks:
        original_duration = max(chunk.end - chunk.start, 0.05)
        tts_duration = max(chunk.tts_duration, 0.05)

        chunk.rebuilt_original_start = cursor
        chunk.rebuilt_original_end = cursor + original_duration
        chunk.rebuilt_tts_start = chunk.rebuilt_original_end
        chunk.rebuilt_tts_end = chunk.rebuilt_tts_start + tts_duration

        cursor = chunk.rebuilt_tts_end
    return chunks
