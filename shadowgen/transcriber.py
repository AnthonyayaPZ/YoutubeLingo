from __future__ import annotations

import os
from pathlib import Path

from shadowgen.config import AppConfig
from shadowgen.models import SpeechSegment, TranscriptionResult, WordTiming
from shadowgen.utils import logger


class Transcriber:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def transcribe(self, audio_path: Path, media_duration: float) -> TranscriptionResult:
        backend = self.config.transcribe_backend
        if self.config.mock or backend == "mock":
            return self._mock_result()

        if backend in ("auto", "whisperx"):
            try:
                return self._transcribe_with_whisperx(audio_path)
            except Exception as exc:  # pragma: no cover - optional dependency path
                if "Weights only load failed" in str(exc):
                    logger.warning(
                        "whisperx blocked by torch weights_only policy. "
                        "For trusted checkpoints, set TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1."
                    )
                if backend == "whisperx":
                    raise
                logger.warning("whisperx unavailable, fallback to whisper: %s", exc)

        if backend in ("auto", "whisper"):
            try:
                return self._transcribe_with_whisper(audio_path)
            except Exception as exc:  # pragma: no cover - optional dependency path
                if backend == "whisper":
                    raise
                logger.warning("whisper unavailable, fallback to single segment: %s", exc)

        return self._fallback_result(media_duration)

    def _transcribe_with_whisperx(self, audio_path: Path) -> TranscriptionResult:
        self._prepare_torch_whisperx_compat()
        import whisperx  # type: ignore

        device = "cuda" if self._cuda_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        model = whisperx.load_model(self.config.asr_model, device=device, compute_type=compute_type)
        audio = whisperx.load_audio(str(audio_path))
        result = model.transcribe(audio)
        language = result.get("language", "en")

        align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
        aligned = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )

        segments: list[SpeechSegment] = []
        words: list[WordTiming] = []
        for idx, seg in enumerate(aligned["segments"], start=1):
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
            text = str(seg.get("text", "")).strip()
            segments.append(SpeechSegment(id=idx, start=start, end=end, text=text))
            for w in seg.get("words", []):
                ws = w.get("start")
                we = w.get("end")
                wt = str(w.get("word", "")).strip()
                if ws is None or we is None or not wt:
                    continue
                words.append(WordTiming(text=wt, start=float(ws), end=float(we)))

        return TranscriptionResult(segments=segments, words=words, language=language)

    @staticmethod
    def _prepare_torch_whisperx_compat() -> None:
        # PyTorch 2.6 changed torch.load default to weights_only=True.
        # Some whisperx/pyannote checkpoints require allowlisted OmegaConf types.
        try:
            import torch  # type: ignore
            from omegaconf.dictconfig import DictConfig  # type: ignore
            from omegaconf.listconfig import ListConfig  # type: ignore

            if hasattr(torch.serialization, "add_safe_globals"):
                torch.serialization.add_safe_globals([ListConfig, DictConfig])
        except Exception:
            return

        # Optional escape hatch when third-party checkpoints still fail.
        if os.getenv("SHADOWGEN_TRUST_CHECKPOINTS", "").strip().lower() in (
            "1",
            "y",
            "yes",
            "true",
        ):
            os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

    def _transcribe_with_whisper(self, audio_path: Path) -> TranscriptionResult:
        import whisper  # type: ignore

        model = whisper.load_model(self.config.asr_model)
        result = model.transcribe(str(audio_path), word_timestamps=True, fp16=self._cuda_available())

        segments: list[SpeechSegment] = []
        words: list[WordTiming] = []
        for idx, seg in enumerate(result.get("segments", []), start=1):
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
            text = str(seg.get("text", "")).strip()
            segments.append(SpeechSegment(id=idx, start=start, end=end, text=text))
            for w in seg.get("words", []):
                ws = w.get("start")
                we = w.get("end")
                wt = str(w.get("word", "")).strip()
                if ws is None or we is None or not wt:
                    continue
                words.append(WordTiming(text=wt, start=float(ws), end=float(we)))

        return TranscriptionResult(
            segments=segments,
            words=words,
            language=str(result.get("language", "en")),
        )

    def _fallback_result(self, media_duration: float) -> TranscriptionResult:
        text = "Transcription unavailable. Install whisperx or whisper for full ASR."
        segment = SpeechSegment(id=1, start=0.0, end=max(media_duration, 1.0), text=text)
        words = [
            WordTiming(text="Transcription", start=0.0, end=0.4),
            WordTiming(text="unavailable.", start=0.4, end=0.9),
        ]
        return TranscriptionResult(segments=[segment], words=words, language="en")

    def _mock_result(self) -> TranscriptionResult:
        words = [
            WordTiming(text="Learning", start=0.0, end=0.4),
            WordTiming(text="English", start=0.4, end=0.8),
            WordTiming(text="with", start=0.8, end=1.0),
            WordTiming(text="shadowing", start=1.0, end=1.5),
            WordTiming(text="is", start=1.5, end=1.7),
            WordTiming(text="effective.", start=1.7, end=2.2),
            WordTiming(text="Repeat", start=2.6, end=2.9),
            WordTiming(text="short", start=2.9, end=3.2),
            WordTiming(text="phrases", start=3.2, end=3.6),
            WordTiming(text="and", start=3.6, end=3.8),
            WordTiming(text="imitate", start=3.8, end=4.2),
            WordTiming(text="intonation.", start=4.2, end=4.8),
        ]
        segments = [
            SpeechSegment(id=1, start=0.0, end=2.2, text="Learning English with shadowing is effective."),
            SpeechSegment(id=2, start=2.6, end=4.8, text="Repeat short phrases and imitate intonation."),
        ]
        return TranscriptionResult(segments=segments, words=words, language="en")

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch  # type: ignore

            return bool(torch.cuda.is_available())
        except Exception:
            return False
