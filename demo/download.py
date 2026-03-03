# YouTube 视频下载脚本
#
# 运行方式: python demo/download.py
#
# 输入参数说明:
#   1. YouTube 视频 URL (必填)
#   2. Cookie 模式选择:
#      - 1: 使用浏览器 cookies (推荐，可避免机器人验证)
#      - 2: 使用 cookies.txt 文件
#      - 3: 不使用 cookies
#   3. 若选择模式 1，需填写:
#      - 浏览器名称: chrome/edge/firefox/brave/chromium/opera/vivaldi
#      - 浏览器配置(可选): 如 Default、Profile1 等
#   4. 若选择模式 2，需填写 cookies.txt 文件路径
#
# 示例运行:
#   Enter YouTube video URL: https://www.youtube.com/watch?v=tx5OP6h2ph0
#   Cookie mode: 2
#   Browser [chrome/edge/firefox], default chrome: chrome
#   Browser profile (optional, e.g. Default): demo\www.youtube.com_cookies.txt

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


VIDEO_NAME_PATTERN = re.compile(r"video_(\d+)\.mp4$")
SUPPORTED_BROWSERS = {"chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi"}


def get_next_output_path(base_dir: Path) -> Path:
    max_index = 0
    for file_path in base_dir.iterdir():
        if not file_path.is_file():
            continue
        match = VIDEO_NAME_PATTERN.fullmatch(file_path.name)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return base_dir / f"video_{max_index + 1}.mp4"


def choose_cookie_args() -> list[str]:
    print("Cookie mode:")
    print("1) Browser cookies (recommended)")
    print("2) cookies.txt file")
    print("3) No cookies")
    choice = input("Choose [1/2/3], default 1: ").strip() or "1"

    if choice == "1":
        browser = input("Browser [chrome/edge/firefox], default chrome: ").strip().lower()
        browser = browser or "chrome"
        if browser not in SUPPORTED_BROWSERS:
            raise RuntimeError(f"Unsupported browser: {browser}")
        profile = input("Browser profile (optional, e.g. Default): ").strip()
        if profile:
            return ["--cookies-from-browser", f"{browser}:{profile}"]
        return ["--cookies-from-browser", browser]

    if choice == "2":
        cookies_path_text = input("Path to cookies.txt: ").strip()
        if not cookies_path_text:
            raise RuntimeError("cookies.txt path is required for mode 2.")
        cookies_path = Path(cookies_path_text).expanduser().resolve()
        if not cookies_path.exists() or not cookies_path.is_file():
            raise RuntimeError(f"cookies file not found: {cookies_path}")
        return ["--cookies", str(cookies_path)]

    if choice == "3":
        return []

    raise RuntimeError(f"Invalid choice: {choice}")


def find_english_subtitles(output_path: Path) -> list[Path]:
    parent = output_path.parent
    stem = output_path.stem
    name = output_path.name

    patterns = [
        f"{stem}.en*.vtt",
        f"{name}.en*.vtt",
        f"{stem}.en*.srt",
        f"{name}.en*.srt",
    ]
    found: list[Path] = []
    for pat in patterns:
        found.extend(parent.glob(pat))
    unique_sorted = sorted({p.resolve() for p in found})
    return unique_sorted


def download_with_yt_dlp(url: str, output_path: Path, cookie_args: list[str]) -> list[Path]:
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp not found in PATH.")
    ffmpeg_path = shutil.which("ffmpeg")
    has_ffmpeg = ffmpeg_path is not None

    if has_ffmpeg:
        # Prefer MP4 video + M4A audio for reliable merge/playback in mp4 container.
        format_selector = "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b"
        print(f"Using ffmpeg: {ffmpeg_path}")
    else:
        # Without ffmpeg, yt-dlp cannot merge separate streams. Force a single-file format with audio.
        format_selector = "b[ext=mp4]/b"
        print("Warning: ffmpeg not found, falling back to lower-quality single-file format with audio.")

    merge_args = ["--merge-output-format", "mp4"] if has_ffmpeg else []

    cmd = [
        "yt-dlp",
        "--no-progress",
        "--no-playlist",
        "-f",
        format_selector,
        "--write-sub",
        "--write-auto-sub",
        "--sub-langs",
        "en.*,en",
        "--sub-format",
        "vtt",
        *merge_args,
        *cookie_args,
        "-o",
        str(output_path),
        url,
    ]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr or ""
        if "Sign in to confirm you're not a bot" in stderr:
            raise RuntimeError(
                "YouTube blocked anonymous access. Retry with browser cookies "
                "(choose cookie mode 1) or cookies.txt (mode 2)."
            )
        raise RuntimeError(
            f"yt-dlp failed (exit={completed.returncode}).\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{stderr}"
        )
    return find_english_subtitles(output_path)


def main() -> int:
    url = input("Enter YouTube video URL: ").strip()
    if not url:
        print("URL cannot be empty.")
        return 1

    try:
        cookie_args = choose_cookie_args()
    except Exception as exc:
        print(f"Invalid cookie config: {exc}")
        return 1

    output_path = get_next_output_path(Path.cwd())
    print(f"Downloading to: {output_path}")

    try:
        subtitle_paths = download_with_yt_dlp(url, output_path, cookie_args)
    except Exception as exc:
        print(f"Download failed: {exc}")
        return 1

    print(f"Done: {output_path}")
    if subtitle_paths:
        print("English subtitles downloaded:")
        for sub in subtitle_paths:
            print(f"  - {sub}")
    else:
        print("No downloadable English subtitles found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
