from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    url: str
    local_video_path: Path | None = None
    target_lang: str = "zh"
    work_dir: Path = Path(".")
    temp_dir: Path = Path("temp")
    output_dir: Path = Path("output")

    keep_temp: bool = False
    max_workers: int = 4
    retries: int = 3
    retry_base_delay: float = 1.5
    timeout_sec: int = 1200

    asr_model: str = "small"
    transcribe_backend: str = "auto"
    translator_backend: str = "auto"
    tts_backend: str = "auto"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+0%"
    burn_subtitles: bool = True
    mock: bool = False

    def prepare_dirs(self) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tts_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)

    @property
    def tts_dir(self) -> Path:
        return self.temp_dir / "tts"

    @property
    def clips_dir(self) -> Path:
        return self.temp_dir / "clips"

    @property
    def frames_dir(self) -> Path:
        return self.temp_dir / "frames"

    @property
    def source_video_path(self) -> Path:
        return self.temp_dir / "source.mp4"

    @property
    def source_audio_path(self) -> Path:
        return self.temp_dir / "source_audio.wav"
