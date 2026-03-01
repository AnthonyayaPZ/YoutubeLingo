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
    yt_dlp_cookies_from_browser: str = ""
    yt_dlp_cookies_browser_profile: str = ""
    yt_dlp_cookies_file: Path | None = None

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

    def yt_dlp_cookie_args(self) -> list[str]:
        if self.yt_dlp_cookies_file:
            return ["--cookies", str(self.yt_dlp_cookies_file)]
        browser = self.yt_dlp_cookies_from_browser.strip()
        profile = self.yt_dlp_cookies_browser_profile.strip()
        if not browser:
            return []
        if profile:
            return ["--cookies-from-browser", f"{browser}:{profile}"]
        return ["--cookies-from-browser", browser]
