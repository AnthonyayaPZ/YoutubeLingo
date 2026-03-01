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
        cookie_args = self.config.yt_dlp_cookie_args()
        cmd = [
            "yt-dlp",
            "--no-progress",
            "--no-playlist",
            "--merge-output-format",
            "mp4",
            "--print",
            "before_dl:title:%(title)s",
            "--print",
            "after_move:filepath:%(filepath)s",
            *cookie_args,
            "--print",
            "before_dl:filename:%(filename)s",
            "-o",
            output_template,
            self.config.url,
        ]
        proc = run_command(cmd, timeout_sec=self.config.timeout_sec)
        stdout_lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        title = "Untitled"
        final_path: Path | None = None
        for line in stdout_lines:
            if line.startswith("before_dl:title:"):
                title = line.split("before_dl:title:", 1)[1].strip() or title
            elif line.startswith("after_move:filepath:"):
                raw_path = line.split("after_move:filepath:", 1)[1].strip()
                if raw_path:
                    final_path = Path(raw_path).expanduser().resolve()

        title = sanitize_filename(title)

        # Main path: use the explicit post-move filepath emitted by yt-dlp.
        if final_path is not None and final_path.exists():
            source_path = final_path
        else:
            # Fallback path: scan expected files in temp.
            source_candidates = sorted(
                p for p in self.config.temp_dir.glob("source.*") if p.suffix.lower() != ".part"
            )
            if not source_candidates:
                temp_listing = ", ".join(p.name for p in sorted(self.config.temp_dir.glob("*")))
                cookie_diag = "no cookies configured"
                if "--cookies" in cookie_args:
                    cookie_file = Path(cookie_args[-1]).expanduser()
                    cookie_diag = (
                        f"cookies_file={cookie_file} exists={cookie_file.exists()} "
                        f"is_file={cookie_file.is_file()}"
                    )
                elif "--cookies-from-browser" in cookie_args:
                    cookie_diag = f"cookies_from_browser={cookie_args[-1]}"
                raise RuntimeError(
                    "yt-dlp succeeded but no source file was found in temp directory.\n"
                    f"temp_dir={self.config.temp_dir}\n"
                    f"temp_files=[{temp_listing}]\n"
                    f"cookies={cookie_diag}\n"
                    f"yt-dlp stdout:\n{proc.stdout}\n"
                    f"yt-dlp stderr:\n{proc.stderr}"
                )
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
