from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WordTiming:
    text: str
    start: float
    end: float


@dataclass
class SpeechSegment:
    id: int
    start: float
    end: float
    text: str


@dataclass
class SemanticChunk:
    id: int
    start: float
    end: float
    text: str
    translation: str = ""
    tts_path: Path | None = None
    tts_duration: float = 0.0
    rebuilt_original_start: float = 0.0
    rebuilt_original_end: float = 0.0
    rebuilt_tts_start: float = 0.0
    rebuilt_tts_end: float = 0.0


@dataclass
class TranscriptionResult:
    segments: list[SpeechSegment] = field(default_factory=list)
    words: list[WordTiming] = field(default_factory=list)
    language: str = "en"


@dataclass
class DownloadedVideo:
    title: str
    path: Path


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str
