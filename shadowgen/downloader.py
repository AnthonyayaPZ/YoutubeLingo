from __future__ import annotations

from pathlib import Path

from shadowgen.config import AppConfig
from shadowgen.models import DownloadedVideo
from shadowgen.utils import logger, retry, run_command, sanitize_filename


class VideoDownloader:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def download(self) -> DownloadedVideo:
        if self.config.mock:
            return self._create_mock_video()
        if self.config.local_video_path is not None:
            return self._use_local_video()
        return retry(
            operation=self._download_once,
            retries=self.config.retries,
            base_delay=self.config.retry_base_delay,
            task="yt-dlp download",
        )

    def _use_local_video(self) -> DownloadedVideo:
        local_path = self.config.local_video_path
        if local_path is None:
            raise RuntimeError("`local_video_path` is not configured.")

        source_path = local_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Local video not found: {source_path}")
        if not source_path.is_file():
            raise RuntimeError(f"Local video path is not a file: {source_path}")

        logger.info("Using local source video: %s", source_path)
        return DownloadedVideo(title=sanitize_filename(source_path.stem), path=source_path)

    def _download_once(self) -> DownloadedVideo:
        output_template = str(self.config.temp_dir / "source.%(ext)s")
        cmd = [
            "yt-dlp",
            "--no-progress",
            "--merge-output-format",
            "mp4",
            "--print",
            "%(title)s",
            "--output",
            output_template,
            self.config.url,
        ]
        proc = run_command(cmd, timeout_sec=self.config.timeout_sec)
        title = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "Untitled"
        title = sanitize_filename(title)

        source_candidates = sorted(
            p for p in self.config.temp_dir.glob("source.*") if p.suffix.lower() != ".part"
        )
        if not source_candidates:
            raise RuntimeError("yt-dlp succeeded but no source file was found in temp directory.")

        source_path = max(source_candidates, key=lambda p: p.stat().st_mtime)
        final_path = self.config.source_video_path
        if source_path.resolve() != final_path.resolve():
            source_path.replace(final_path)
            source_path = final_path

        logger.info("Downloaded source video: %s", source_path)
        return DownloadedVideo(title=title, path=source_path)

    def _create_mock_video(self) -> DownloadedVideo:
        mock_path = self.config.source_video_path
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(mock_path),
        ]
        run_command(cmd, timeout_sec=self.config.timeout_sec)
        logger.info("Created mock source video: %s", mock_path)
        return DownloadedVideo(title="Mock_Demo", path=mock_path)
