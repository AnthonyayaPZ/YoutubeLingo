from __future__ import annotations

import argparse
from pathlib import Path

from shadowgen.config import AppConfig
from shadowgen.env_loader import load_env_file
from shadowgen.pipeline import ShadowGenPipeline
from shadowgen.utils import configure_logging, logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ShadowGen-Local: bilingual shadowing video generator."
    )
    parser.add_argument("--url", help="YouTube URL to process.")
    parser.add_argument("--video_path", help="Local video file path to process.")
    parser.add_argument("--target_lang", default="zh", help="Target translation language.")
    parser.add_argument("--work_dir", default=".", help="Workspace directory.")
    parser.add_argument("--temp_dir", default="temp", help="Temporary working directory.")
    parser.add_argument("--output_dir", default="output", help="Output directory.")
    parser.add_argument("--keep_temp", action="store_true", help="Do not delete temp folder.")
    parser.add_argument("--max_workers", type=int, default=4, help="Parallel worker count.")
    parser.add_argument("--retries", type=int, default=3, help="Retry attempts for network tasks.")
    parser.add_argument("--asr_model", default="small", help="ASR model name.")
    parser.add_argument(
        "--transcribe_backend",
        choices=("auto", "whisperx", "whisper", "mock"),
        default="auto",
        help="Transcription backend.",
    )
    parser.add_argument(
        "--translator_backend",
        choices=("auto", "openai", "deepl", "mock"),
        default="auto",
        help="Translation backend.",
    )
    parser.add_argument(
        "--tts_backend",
        choices=("auto", "edge", "silent"),
        default="auto",
        help="TTS backend.",
    )
    parser.add_argument(
        "--tts_voice",
        default="zh-CN-XiaoxiaoNeural",
        help="Voice for edge-tts backend.",
    )
    parser.add_argument("--tts_rate", default="+0%", help="Speech rate for edge-tts backend.")
    parser.add_argument(
        "--no_burn_subtitles",
        action="store_true",
        help="Disable hard subtitle burn-in.",
    )
    parser.add_argument("--mock", action="store_true", help="Run with local mock data.")
    parser.add_argument(
        "--log_level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Console log level.",
    )
    return parser.parse_args()


def main() -> int:
    load_env_file()
    args = parse_args()
    configure_logging(args.log_level)

    work_dir = Path(args.work_dir).resolve()
    temp_dir = (work_dir / args.temp_dir).resolve()
    output_dir = (work_dir / args.output_dir).resolve()
    local_video_path: Path | None = None
    if args.video_path:
        local_video_path = Path(args.video_path).expanduser()
        if not local_video_path.is_absolute():
            local_video_path = (work_dir / local_video_path).resolve()
        else:
            local_video_path = local_video_path.resolve()

    selected_input_sources = [bool(args.url), bool(local_video_path), bool(args.mock)]
    if sum(selected_input_sources) != 1:
        raise SystemExit(
            "Provide exactly one input source: `--url`, `--video_path`, or `--mock`."
        )

    config = AppConfig(
        url=args.url or "",
        local_video_path=local_video_path,
        target_lang=args.target_lang,
        work_dir=work_dir,
        temp_dir=temp_dir,
        output_dir=output_dir,
        keep_temp=args.keep_temp,
        max_workers=args.max_workers,
        retries=args.retries,
        asr_model=args.asr_model,
        transcribe_backend=args.transcribe_backend,
        translator_backend=args.translator_backend,
        tts_backend=args.tts_backend,
        tts_voice=args.tts_voice,
        tts_rate=args.tts_rate,
        burn_subtitles=not args.no_burn_subtitles,
        mock=args.mock,
    )

    pipeline = ShadowGenPipeline(config)
    try:
        outputs = pipeline.run()
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc)
        return 1

    logger.info("Pipeline completed.")
    logger.info("Video: %s", outputs["video"])
    logger.info("MP3: %s", outputs["audio"])
    logger.info("SRT: %s", outputs["srt"])
    logger.info("Word-level JSON: %s", outputs["wordlevel"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
