from __future__ import annotations

import asyncio
from pathlib import Path

from shadowgen.config import AppConfig
from shadowgen.utils import retry, run_command
from shadowgen.video_engine import probe_media_duration


class TTSSynthesizer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def synthesize(self, text: str, output_path: Path) -> float:
        backend = self.config.tts_backend

        if self.config.mock or backend == "silent":
            return self._silent_tts(text, output_path)

        if backend in ("auto", "edge"):
            try:
                retry(
                    operation=lambda: self._edge_tts(text, output_path),
                    retries=self.config.retries,
                    base_delay=self.config.retry_base_delay,
                    task="edge-tts synthesis",
                )
                return probe_media_duration(output_path)
            except Exception:
                if backend == "edge":
                    raise

        return self._silent_tts(text, output_path)

    def _edge_tts(self, text: str, output_path: Path) -> None:
        import edge_tts  # type: ignore

        async def _save() -> None:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.config.tts_voice,
                rate=self.config.tts_rate,
            )
            await communicate.save(str(output_path))

        try:
            asyncio.run(_save())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_save())
            finally:
                loop.close()

    def _silent_tts(self, text: str, output_path: Path) -> float:
        estimated_seconds = max(1.0, min(12.0, len(text) / 4.0))
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{estimated_seconds:.3f}",
            "-q:a",
            "9",
            "-acodec",
            "libmp3lame",
            str(output_path),
        ]
        run_command(cmd, timeout_sec=self.config.timeout_sec)
        return probe_media_duration(output_path)
