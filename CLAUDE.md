# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ShadowGen-Local is a Python CLI tool that transforms YouTube videos into bilingual shadowing study materials for language learners. It generates:
- Shadowing video with alternating original audio and Chinese TTS translation
- MP3 audio version
- Bilingual SRT subtitles
- Word-level timestamp data JSON

## Common Commands

```bash
# Install dependencies
uv sync

# Install with ASR support (choose one)
uv sync --extra asr-whisperx   # Recommended: better word-level timestamps
uv sync --extra asr-whisper

# Run pipeline with real YouTube URL
uv run python main.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --target_lang zh

# Run with mock data (offline demo)
uv run python main.py --mock

# Run tests
uv run pytest

# Run single test
uv run pytest tests/test_file.py::test_function
```

## Architecture

The project follows a **pipeline architecture** with modular components:

```
main.py                  # CLI entry point, argument parsing
shadowgen/pipeline.py    # Main orchestration (ShadowGenPipeline class)
```

**Pipeline stages** (in order):
1. `downloader.py` - Download YouTube video via yt-dlp
2. `transcriber.py` - ASR transcription with word-level timestamps (whisperx/whisper)
3. `chunker.py` - Semantic chunking: group words into coherent sentences
4. `translator.py` - Translate English to target language (OpenAI/DeepL)
5. `tts.py` - Generate Chinese audio (edge-tts)
6. `timeline.py` - Recalculate timestamps accounting for TTS durations
7. `subtitles.py` - Generate bilingual SRT file
8. `video_engine.py` - FFmpeg video processing: slice, freeze frames, merge TTS, concatenate, burn subtitles

**Data models** in `models.py`:
- `WordTiming` - Word with start/end timestamps
- `SpeechSegment` - Sentence/segment with timestamps
- `SemanticChunk` - Chunk with original text, translation, TTS audio path, recalculated timeline
- `TranscriptionResult` - Full transcription result

**Configuration** in `config.py`:
- `AppConfig` dataclass holds all pipeline configuration
- Backends selectable via CLI: `auto`, `whisperx`, `whisper`, `mock` for ASR; `auto`, `openai`, `deepl`, `mock` for translator; `auto`, `edge`, `silent` for TTS

## Environment Setup

Required system tools (must be in PATH):
- `ffmpeg` / `ffprobe` - Video processing
- `yt-dlp` - YouTube download

Required `.env` variables:
- `OPENAI_API_KEY` - For OpenAI translation
- `OPENAI_MODEL` - Model name (default: gpt-4o-mini)
- `DEEPL_API_KEY` - For DeepL translation

## Key Patterns

- Use `@retry` decorator from `utils.py` for network operations with automatic retries
- All components receive `AppConfig` in constructor
- Translation and TTS run in parallel using `ThreadPoolExecutor`
- Mock backends available for testing without API calls: `--transcribe_backend mock --translator_backend mock --tts_backend silent`
