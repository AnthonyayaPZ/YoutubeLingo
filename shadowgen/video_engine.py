from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from shadowgen.config import AppConfig
from shadowgen.models import SemanticChunk
from shadowgen.utils import ffmpeg_subtitles_path, logger, run_command


def probe_media_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = run_command(cmd, timeout_sec=120, check=True)
    duration_text = proc.stdout.strip()
    if not duration_text:
        raise RuntimeError(f"Could not read media duration for: {path}")
    return float(duration_text)


class VideoEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def extract_audio(self, source_video: Path, output_audio: Path) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_audio),
        ]
        run_command(cmd, timeout_sec=self.config.timeout_sec)

    def render_shadowing_video(
        self,
        source_video: Path,
        chunks: list[SemanticChunk],
        srt_path: Path,
        output_video: Path,
        burn_subtitles: bool = True,
    ) -> None:
        rendered: dict[int, tuple[Path, Path]] = {}
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(self._render_chunk_pair, source_video, chunk): chunk.id
                for chunk in chunks
            }
            for future in as_completed(futures):
                chunk_id = futures[future]
                rendered[chunk_id] = future.result()
                logger.debug("Rendered chunk pair %s/%s", chunk_id, len(chunks))

        ordered_clips: list[Path] = []
        for chunk in sorted(chunks, key=lambda c: c.id):
            original_clip, freeze_clip = rendered[chunk.id]
            ordered_clips.append(original_clip)
            ordered_clips.append(freeze_clip)

        concatenated = self.config.temp_dir / "shadowing_concat.mp4"
        self._concat_clips(ordered_clips, concatenated)

        if burn_subtitles:
            self._burn_subtitles(concatenated, srt_path, output_video)
        else:
            if output_video.exists():
                output_video.unlink()
            concatenated.replace(output_video)

    def export_mp3(self, source_video: Path, output_mp3: Path) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_mp3),
        ]
        run_command(cmd, timeout_sec=self.config.timeout_sec)

    def _render_chunk_pair(self, source_video: Path, chunk: SemanticChunk) -> tuple[Path, Path]:
        if chunk.tts_path is None:
            raise RuntimeError(f"Chunk {chunk.id} has no tts_path.")

        original_clip = self.config.clips_dir / f"{chunk.id:04d}_orig.mp4"
        freeze_clip = self.config.clips_dir / f"{chunk.id:04d}_freeze.mp4"
        frame_image = self.config.frames_dir / f"{chunk.id:04d}_tail.jpg"

        original_duration = max(chunk.end - chunk.start, 0.05)
        frame_time = max(chunk.end - 0.03, chunk.start)
        tts_duration = max(chunk.tts_duration, 0.05)

        original_cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{chunk.start:.3f}",
            "-i",
            str(source_video),
            "-t",
            f"{original_duration:.3f}",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=25",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(original_clip),
        ]
        run_command(original_cmd, timeout_sec=self.config.timeout_sec)

        frame_cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{frame_time:.3f}",
            "-i",
            str(source_video),
            "-frames:v",
            "1",
            str(frame_image),
        ]
        run_command(frame_cmd, timeout_sec=self.config.timeout_sec)

        freeze_cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(frame_image),
            "-i",
            str(chunk.tts_path),
            "-t",
            f"{tts_duration:.3f}",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=25,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-shortest",
            str(freeze_clip),
        ]
        run_command(freeze_cmd, timeout_sec=self.config.timeout_sec)
        return original_clip, freeze_clip

    def _concat_clips(self, clips: list[Path], output_video: Path) -> None:
        if not clips:
            raise RuntimeError("No clips generated for concatenation.")

        concat_file = self.config.temp_dir / "concat.txt"
        lines = []
        for clip in clips:
            p = str(clip.resolve()).replace("\\", "/").replace("'", "\\'")
            lines.append(f"file '{p}'")
        concat_file.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_video),
        ]
        run_command(cmd, timeout_sec=self.config.timeout_sec)

    def _burn_subtitles(self, input_video: Path, srt_path: Path, output_video: Path) -> None:
        subtitle_filter = ffmpeg_subtitles_path(srt_path)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video),
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "copy",
            str(output_video),
        ]
        run_command(cmd, timeout_sec=self.config.timeout_sec)
