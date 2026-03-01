from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from shadowgen.chunker import SemanticChunker
from shadowgen.config import AppConfig
from shadowgen.downloader import VideoDownloader
from shadowgen.models import SemanticChunk, TranscriptionResult
from shadowgen.subtitles import build_subtitle_entries, write_srt
from shadowgen.timeline import rebuild_timeline
from shadowgen.transcriber import Transcriber
from shadowgen.translator import Translator
from shadowgen.tts import TTSSynthesizer
from shadowgen.utils import ensure_command_exists, logger, sanitize_filename
from shadowgen.video_engine import VideoEngine, probe_media_duration
from shadowgen.youtube_subtitles import download_and_parse_english_subtitles


class ShadowGenPipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.downloader = VideoDownloader(config)
        self.transcriber = Transcriber(config)
        self.chunker = SemanticChunker()
        self.translator = Translator(config)
        self.tts = TTSSynthesizer(config)
        self.video_engine = VideoEngine(config)

    def run(self) -> dict[str, str]:
        self._validate_runtime_dependencies()
        self.config.prepare_dirs()
        outputs: dict[str, str] = {}

        try:
            downloaded = self.downloader.download()
            title = sanitize_filename(downloaded.title)
            source_video = downloaded.path
            logger.info("Title: %s", title)

            transcription: TranscriptionResult | None = None
            if self.config.url and self.config.local_video_path is None and not self.config.mock:
                logger.info("Checking YouTube English subtitles before ASR...")
                transcription = download_and_parse_english_subtitles(
                    url=self.config.url,
                    temp_dir=self.config.temp_dir,
                    timeout_sec=self.config.timeout_sec,
                    cookie_args=self.config.yt_dlp_cookie_args(),
                )

            if transcription is None:
                logger.info("Extracting source audio...")
                self.video_engine.extract_audio(source_video, self.config.source_audio_path)

                media_duration = probe_media_duration(source_video)
                logger.info("Transcribing audio...")
                transcription = self.transcriber.transcribe(self.config.source_audio_path, media_duration)
            else:
                logger.info("Subtitle-first path enabled, skipping ASR.")

            chunks = self.chunker.chunk(transcription)
            if not chunks:
                raise RuntimeError("No semantic chunks generated from transcription.")

            logger.info("Translating and generating TTS for %s chunks...", len(chunks))
            chunks = self._translate_and_tts(chunks)
            rebuild_timeline(chunks)

            srt_path = self.config.output_dir / f"{title}_Bilingual.srt"
            subtitle_entries = build_subtitle_entries(chunks)
            write_srt(subtitle_entries, srt_path)

            wordlevel_path = self.config.output_dir / f"{title}_WordLevel_Data.json"
            self._write_wordlevel_json(wordlevel_path, transcription, chunks)

            video_path = self.config.output_dir / f"{title}_Shadowing_Bilingual.mp4"
            logger.info("Rendering video...")
            self.video_engine.render_shadowing_video(
                source_video=source_video,
                chunks=chunks,
                srt_path=srt_path,
                output_video=video_path,
                burn_subtitles=self.config.burn_subtitles,
            )

            audio_path = self.config.output_dir / f"{title}_Shadowing.mp3"
            self.video_engine.export_mp3(video_path, audio_path)

            outputs = {
                "video": str(video_path),
                "audio": str(audio_path),
                "srt": str(srt_path),
                "wordlevel": str(wordlevel_path),
            }
            return outputs
        finally:
            if not self.config.keep_temp:
                self._cleanup_temp()

    def _translate_and_tts(self, chunks: list[SemanticChunk]) -> list[SemanticChunk]:
        def process(chunk: SemanticChunk) -> SemanticChunk:
            translation = self.translator.translate(chunk.text)
            tts_path = self.config.tts_dir / f"tts_{chunk.id:04d}.mp3"
            tts_duration = self.tts.synthesize(translation, tts_path)
            chunk.translation = translation
            chunk.tts_path = tts_path
            chunk.tts_duration = tts_duration
            return chunk

        processed: list[SemanticChunk] = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {executor.submit(process, chunk): chunk.id for chunk in chunks}
            for future in as_completed(futures):
                processed.append(future.result())

        processed.sort(key=lambda c: c.id)
        return processed

    @staticmethod
    def _write_wordlevel_json(
        output_path: Path,
        transcription: TranscriptionResult,
        chunks: list[SemanticChunk],
    ) -> None:
        payload = {
            "language": transcription.language,
            "segments": [
                {"id": s.id, "start": s.start, "end": s.end, "text": s.text}
                for s in transcription.segments
            ],
            "words": [
                {"text": w.text, "start": w.start, "end": w.end}
                for w in transcription.words
            ],
            "chunks": [
                {
                    "id": c.id,
                    "start": c.start,
                    "end": c.end,
                    "text": c.text,
                    "translation": c.translation,
                    "tts_duration": c.tts_duration,
                    "rebuilt_original_start": c.rebuilt_original_start,
                    "rebuilt_original_end": c.rebuilt_original_end,
                    "rebuilt_tts_start": c.rebuilt_tts_start,
                    "rebuilt_tts_end": c.rebuilt_tts_end,
                }
                for c in chunks
            ],
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _cleanup_temp(self) -> None:
        if self.config.temp_dir.exists():
            logger.info("Cleaning temp directory: %s", self.config.temp_dir)
            shutil.rmtree(self.config.temp_dir, ignore_errors=True)

    def _validate_runtime_dependencies(self) -> None:
        ensure_command_exists("ffmpeg")
        ensure_command_exists("ffprobe")
        if not self.config.mock and self.config.local_video_path is None:
            ensure_command_exists("yt-dlp")
