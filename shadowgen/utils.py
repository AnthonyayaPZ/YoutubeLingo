from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, TypeVar


logger = logging.getLogger("shadowgen")

T = TypeVar("T")


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def run_command(
    args: list[str],
    timeout_sec: int = 1200,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    logger.debug("Running command: %s", " ".join(args))
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed (exit %s): %s\nstdout:\n%s\nstderr:\n%s"
            % (proc.returncode, " ".join(args), proc.stdout, proc.stderr)
        )
    return proc


def retry(operation: Callable[[], T], retries: int, base_delay: float, task: str) -> T:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - runtime safety path
            last_error = exc
            if attempt == retries:
                break
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("%s failed (%s/%s), retry in %.1fs", task, attempt, retries, delay)
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "Untitled"


def ffmpeg_subtitles_path(path: Path) -> str:
    p = str(path.resolve()).replace("\\", "/")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return f"subtitles='{p}':charenc=UTF-8"


def format_srt_timestamp(seconds: float) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def normalize_spaces(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text


def ensure_command_exists(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(
            f"Required command not found: `{name}`. "
            f"Please install it and ensure it is available in PATH."
        )
