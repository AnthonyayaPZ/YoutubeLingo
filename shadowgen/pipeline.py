from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from pathlib import Path

from shadowgen.chunker import SemanticChunker
from shadowgen.config import AppConfig
from shadowgen.downloader import VideoDownloader
from shadowgen.models import SemanticChunk, SpeechSegment, TranscriptionResult, WordTiming
from shadowgen.resume import ResumeManager
from shadowgen.subtitles import build_subtitle_entries, write_srt
from shadowgen.subtitle_input import parse_subtitle_file
from shadowgen.timeline import rebuild_timeline
from shadowgen.transcriber import Transcriber
from shadowgen.translator import Translator
from shadowgen.tts import TTSSynthesizer
from shadowgen.utils import create_progress, ensure_command_exists, logger, sanitize_filename
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
        self.resume: ResumeManager | None = None

    def run(self) -> dict[str, str]:
        self._validate_runtime_dependencies()
        self.config.prepare_dirs()
        self.resume = ResumeManager.create(self.config.resume_state_path, self._resume_input_payload())
        self.resume.load_or_initialize(require_match=self.config.resume)
        outputs: dict[str, str] = {}
        succeeded = False

        try:
            source_video, title = self._prepare_source_video()
            logger.info("Title: %s", title)
            self.resume.set_title(title)
            self.resume.set_artifact("source_video", str(source_video))
            self.resume.set_stage("downloaded")

            transcription: TranscriptionResult | None = None
            if self.config.resume:
                transcription = self._load_transcription_cache()

            if self.config.subtitle_path is not None:
                logger.info("Using provided subtitle file: %s", self.config.subtitle_path)
                transcription = parse_subtitle_file(self.config.subtitle_path)
            elif self.config.url and self.config.local_video_path is None and not self.config.mock:
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

            self._save_transcription_cache(transcription)
            self.resume.set_artifact("transcription_path", str(self.config.transcription_cache_path))
            self.resume.set_stage("transcribed")

            chunks = self.chunker.chunk(transcription)
            if not chunks:
                raise RuntimeError("No semantic chunks generated from transcription.")

            logger.info("Translating and generating TTS for %s chunks...", len(chunks))
            chunks = self._translate_and_tts(chunks)
            self.resume.set_stage("tts_done")
            rebuild_timeline(chunks)

            srt_path = self.config.output_dir / f"{title}_Bilingual.srt"
            subtitle_entries = build_subtitle_entries(chunks)
            write_srt(subtitle_entries, srt_path)
            self.resume.set_artifact("srt_path", str(srt_path))

            wordlevel_path = self.config.output_dir / f"{title}_WordLevel_Data.json"
            self._write_wordlevel_json(wordlevel_path, transcription, chunks)
            self.resume.set_artifact("wordlevel_path", str(wordlevel_path))

            video_path = self.config.output_dir / f"{title}_Shadowing_Bilingual.mp4"
            logger.info("Rendering video...")
            self.video_engine.render_shadowing_video(
                source_video=source_video,
                chunks=chunks,
                srt_path=srt_path,
                output_video=video_path,
                burn_subtitles=self.config.burn_subtitles,
            )
            self.resume.set_stage("rendered")
            self.resume.set_artifact("video_path", str(video_path))

            audio_path = self.config.output_dir / f"{title}_Shadowing.mp3"
            self.video_engine.export_mp3(video_path, audio_path)
            self.resume.set_artifact("audio_path", str(audio_path))
            self.resume.set_stage("completed")

            outputs = {
                "video": str(video_path),
                "audio": str(audio_path),
                "srt": str(srt_path),
                "wordlevel": str(wordlevel_path),
            }
            succeeded = True
            return outputs
        except Exception as exc:
            if self.resume is not None:
                self.resume.set_error(str(exc))
            raise
        finally:
            if succeeded and not self.config.keep_temp:
                self._cleanup_temp()
            elif not succeeded:
                logger.info("Pipeline failed; preserving temp directory for debugging: %s", self.config.temp_dir)

    def _translate_and_tts(self, chunks: list[SemanticChunk]) -> list[SemanticChunk]:
        def process(chunk: SemanticChunk) -> SemanticChunk:
            translation = self.translator.translate(chunk.text)
            tts_path = self.config.tts_dir / f"tts_{chunk.id:04d}.mp3"
            tts_duration = self.tts.synthesize(translation, tts_path)
            chunk.translation = translation
            chunk.tts_path = tts_path
            chunk.tts_duration = tts_duration
            return chunk

        if self.resume is not None:
            self.resume.init_chunks(
                [
                    {"id": c.id, "start": c.start, "end": c.end, "text": c.text}
                    for c in chunks
                ]
            )

        processed: list[SemanticChunk] = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures: dict = {}
            with create_progress(total=len(chunks), desc="Translating+TTS", unit="chunk") as pbar:
                for chunk in chunks:
                    if self._apply_resumed_chunk(chunk):
                        processed.append(chunk)
                        pbar.update(1)
                        continue
                    future = executor.submit(process, chunk)
                    futures[future] = chunk.id
                try:
                    for future in as_completed(futures, timeout=self.config.timeout_sec):
                        chunk_id = futures[future]
                        try:
                            done_chunk = future.result()
                        except Exception as exc:
                            if self.resume is not None:
                                self.resume.mark_chunk_failed(chunk_id, str(exc))
                            raise
                        processed.append(done_chunk)
                        if self.resume is not None:
                            self.resume.mark_chunk_done(
                                chunk_id=done_chunk.id,
                                translation=done_chunk.translation,
                                tts_path=str(done_chunk.tts_path) if done_chunk.tts_path else "",
                                tts_duration=done_chunk.tts_duration,
                            )
                        pbar.update(1)
                except FuturesTimeoutError as exc:
                    pending = [chunk_id for f, chunk_id in futures.items() if not f.done()]
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    preview = pending[:10]
                    if self.resume is not None and preview:
                        self.resume.set_error(
                            "Translating+TTS timeout; pending chunk ids: " + ",".join(str(x) for x in preview)
                        )
                    raise RuntimeError(
                        "Translating+TTS timed out waiting for workers. "
                        f"Pending chunk ids (first 10): {preview}; total pending={len(pending)}."
                    ) from exc

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
            if not (self.config.resume and self.config.source_video_path.exists()):
                ensure_command_exists("yt-dlp")

    def _prepare_source_video(self) -> tuple[Path, str]:
        if self.config.resume:
            resumed_source = self._load_resumed_source_video()
            if resumed_source is not None:
                title = self.resume.get_title() if self.resume is not None else ""
                title = sanitize_filename(title) if title else sanitize_filename(resumed_source.stem)
                logger.info("Resuming with existing source video: %s", resumed_source)
                return resumed_source, title

        downloaded = self.downloader.download()
        title = sanitize_filename(downloaded.title)
        return downloaded.path, title

    def _load_resumed_source_video(self) -> Path | None:
        if self.resume is None:
            return None
        path_text = self.resume.get_artifact("source_video")
        if not path_text:
            return None
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            path = (self.config.work_dir / path).resolve()
        else:
            path = path.resolve()
        if not path.exists() or not path.is_file():
            return None
        return path

    def _save_transcription_cache(self, transcription: TranscriptionResult) -> None:
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
        }
        self.config.transcription_cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_transcription_cache(self) -> TranscriptionResult | None:
        path = self.config.transcription_cache_path
        if not path.exists() or not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        segments = []
        for idx, s in enumerate(payload.get("segments", []), start=1):
            if "start" not in s or "end" not in s or "text" not in s:
                continue
            segments.append(
                SpeechSegment(
                    id=int(s.get("id", idx)),
                    start=float(s["start"]),
                    end=float(s["end"]),
                    text=str(s["text"]),
                )
            )

        words = []
        for w in payload.get("words", []):
            if "text" not in w or "start" not in w or "end" not in w:
                continue
            words.append(
                WordTiming(
                    text=str(w["text"]),
                    start=float(w["start"]),
                    end=float(w["end"]),
                )
            )
        if not segments and not words:
            return None
        logger.info("Loaded transcription cache: %s", path)
        return TranscriptionResult(
            segments=segments,
            words=words,
            language=str(payload.get("language", "en")),
        )

    def _apply_resumed_chunk(self, chunk: SemanticChunk) -> bool:
        if not self.config.resume or self.resume is None:
            return False
        data = self.resume.get_chunk_done(chunk.id)
        if data is None:
            return False
        tts_path_text = str(data.get("tts_path", "")).strip()
        if not tts_path_text:
            return False
        tts_path = Path(tts_path_text).expanduser()
        if not tts_path.is_absolute():
            tts_path = (self.config.work_dir / tts_path).resolve()
        else:
            tts_path = tts_path.resolve()
        if not tts_path.exists() or not tts_path.is_file():
            return False
        chunk.translation = str(data.get("translation", ""))
        chunk.tts_path = tts_path
        chunk.tts_duration = float(data.get("tts_duration", 0.0))
        return bool(chunk.translation) and chunk.tts_duration > 0

    def _resume_input_payload(self) -> dict[str, str]:
        return {
            "url": self.config.url,
            "local_video_path": str(self.config.local_video_path or ""),
            "subtitle_path": str(self.config.subtitle_path or ""),
            "target_lang": self.config.target_lang,
            "asr_model": self.config.asr_model,
            "transcribe_backend": self.config.transcribe_backend,
            "translator_backend": self.config.translator_backend,
            "tts_backend": self.config.tts_backend,
            "tts_voice": self.config.tts_voice,
            "tts_rate": self.config.tts_rate,
            "burn_subtitles": str(self.config.burn_subtitles),
        }
