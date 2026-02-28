from __future__ import annotations

from shadowgen.models import SemanticChunk, TranscriptionResult, WordTiming
from shadowgen.utils import normalize_spaces


class SemanticChunker:
    def __init__(self, max_words: int = 18, max_duration: float = 8.0) -> None:
        self.max_words = max_words
        self.max_duration = max_duration

    def chunk(self, transcription: TranscriptionResult) -> list[SemanticChunk]:
        if transcription.words:
            return self._chunk_by_words(transcription.words)
        return [
            SemanticChunk(id=s.id, start=s.start, end=s.end, text=s.text)
            for s in transcription.segments
        ]

    def _chunk_by_words(self, words: list[WordTiming]) -> list[SemanticChunk]:
        chunks: list[SemanticChunk] = []
        buffer: list[WordTiming] = []
        chunk_id = 1

        for word in words:
            if not word.text.strip():
                continue
            buffer.append(word)
            duration = buffer[-1].end - buffer[0].start
            token = word.text.strip()
            should_cut = (
                token.endswith((".", "?", "!", ";", "。", "？", "！"))
                or len(buffer) >= self.max_words
                or duration >= self.max_duration
            )
            if should_cut:
                chunks.append(self._build_chunk(chunk_id, buffer))
                chunk_id += 1
                buffer = []

        if buffer:
            chunks.append(self._build_chunk(chunk_id, buffer))

        return chunks

    @staticmethod
    def _build_chunk(chunk_id: int, words: list[WordTiming]) -> SemanticChunk:
        text = normalize_spaces(" ".join(w.text for w in words))
        return SemanticChunk(
            id=chunk_id,
            start=words[0].start,
            end=words[-1].end,
            text=text,
        )
