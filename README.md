# ShadowGen-Local (PRDv2 实现版)

基于 `PRDv2.md` 的本地 CLI 产品原型：输入 YouTube URL，自动生成影子跟读学习包。

## 功能覆盖

- 下载 YouTube 视频（`yt-dlp`）
- ASR 转录与词级时间戳（`whisperx` / `whisper`，自动降级）
- 语义分块（基于词级时间戳）
- 翻译（OpenAI / DeepL / Mock）
- 中文 TTS（`edge-tts` / 静音降级）
- 时间轴重构 + 双语 SRT 生成
- 视频切片、尾帧定格、TTS 混流、拼接（FFmpeg）
- 硬字幕烧录（可关闭）
- 导出学习包：
  - `[Title]_Shadowing_Bilingual.mp4`
  - `[Title]_Shadowing.mp3`
  - `[Title]_Bilingual.srt`
  - `[Title]_WordLevel_Data.json`

## 环境要求

- Python 3.11.x（推荐）
- Python 3.11+（最低要求）
- `ffmpeg` / `ffprobe` 可在命令行直接调用
- `yt-dlp` 可在命令行直接调用

可选：
- `whisperx` 或 `openai-whisper`
- `edge-tts`
- OpenAI/DeepL API Key

推荐说明：
- 推荐 `Python 3.11.x`，在当前项目依赖组合中兼容性更稳。
- 如果你使用 Conda，建议新建环境后再执行 `uv`：

```powershell
conda create -n shadowgen python=3.11 -y
conda activate shadowgen
```

## 关键依赖与版本

以下为当前项目关键依赖及版本策略（以 `pyproject.toml + uv.lock` 为准）：

- `uv`：依赖管理与锁文件工具（建议 `0.10+`）。
- `openai>=1.40.0`（锁定示例：`2.24.0`）：用于 OpenAI 兼容翻译接口调用。
- `edge-tts>=6.1.12`（锁定示例：`7.2.7`）：用于中文 TTS 语音生成。
- `python-dotenv>=1.0.1`（锁定示例：`1.2.1`）：启动时自动加载 `.env` 配置。
- `torch==2.6.0+cu124`（ASR extra）：GPU 推理核心，固定 CUDA 12.4 变体。
- `torchaudio==2.6.0+cu124`（`asr-whisperx` extra）：WhisperX 音频链路依赖。
- `whisperx`（锁定示例：`3.4.3`，`asr-whisperx` extra）：词级时间戳对齐与 ASR。
- `openai-whisper`（锁定示例：`20250625`，`asr-whisper` extra）：备用 ASR 后端。

说明：
- 项目已将 `torch/torchaudio` 显式绑定到 `cu124` 索引，避免 `uv sync` 时回退到通用 CPU 变体。
- 如需完整 ASR 能力，建议直接安装全部可选依赖：`uv sync --all-extras`。

## 系统依赖安装（Windows）

推荐使用 `winget` 安装：

```powershell
winget install --id Gyan.FFmpeg -e
winget install --id yt-dlp.yt-dlp -e
```

说明：
- `ffprobe` 会随 `ffmpeg` 一起安装。
- 安装后建议重开一个终端，再执行下方命令验证。

验证命令：

```powershell
ffmpeg -version
ffprobe -version
yt-dlp --version
```

## 依赖管理（uv）

本项目使用 `uv` 管理 Python 依赖。

## 安装

```bash
uv sync
```

如果使用转录功能，请安装一个 ASR 可选依赖（任选其一）：

```bash
uv sync --extra asr-whisperx
# 或
uv sync --extra asr-whisper
```

如果你希望一次性启用完整能力（推荐）：

```bash
uv sync --all-extras
```

如果你要运行测试：

```bash
uv sync --group dev
```

## 配置 `.env`

项目启动时会自动读取根目录下的 `.env` 文件。请先复制模板：

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`，至少按需配置以下变量：

```dotenv
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
DEEPL_API_KEY=your_deepl_key
```

说明：
- `OPENAI_API_KEY`：使用 `openai` 翻译后端时必需。
- `OPENAI_MODEL`：OpenAI 翻译模型，默认 `gpt-4o-mini`。
- `DEEPL_API_KEY`：使用 `deepl` 翻译后端时必需。

优先级：
- 命令行参数（如 `--translator_backend`）优先于 `.env`。
- API Key/模型等未在命令行提供的配置从 `.env` 读取。

## 使用

### 1) 真实 URL 流水线

```bash
uv run python main.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --target_lang zh
```

### 2) 处理本地视频文件

```bash
uv run python main.py --video_path "./video_1.mp4" --target_lang zh
```

### 3) 本地视频 + 本地字幕（跳过 ASR）
```bash
uv run python main.py --video_path "./video_1.mp4" --subtitle_path "./video_1.en.srt" --target_lang zh
```

未提供 `--subtitle_path` 时，将沿用原逻辑自动进行语音识别（ASR）。

### 4) 本地离线演示（不依赖 URL）

```bash
uv run python main.py --mock
```

## 常用参数

- `--transcribe_backend auto|whisperx|whisper|mock`
- `--translator_backend auto|openai|deepl|mock`
- `--tts_backend auto|edge|silent`
- `--max_workers 4`
- `--retries 3`
- `--keep_temp`
- `--no_burn_subtitles`
- `--subtitle_path ./video_1.en.srt`（可选，指定后优先使用本地字幕并跳过 ASR）
- `OPENAI_PARALLEL_REQUESTS`（环境变量，默认 `1`；仅 OpenAI 生效，值 > 1 时同一段文本并发请求，先返回先用）

## 环境变量

- `OPENAI_API_KEY`（当 translator backend 使用 openai）
- `OPENAI_MODEL`（可选，默认 `gpt-4o-mini`）
- `OPENAI_PARALLEL_REQUESTS`（可选，默认 `1`）
- `DEEPL_API_KEY`（当 translator backend 使用 deepl）

`OPENAI_PARALLEL_REQUESTS` 使用说明：
- 取值 `1`：单请求模式（成本最低）
- 取值 `>1`：并发请求同一段文本，先成功先返回（延迟更低，但 token 成本更高）
- 建议先从 `2` 开始测试，例如：

```bash
OPENAI_PARALLEL_REQUESTS=2 uv run python main.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --target_lang zh
```

## 目录结构

```text
.
├── main.py
├── pyproject.toml
├── .env.example
├── shadowgen
│   ├── chunker.py
│   ├── config.py
│   ├── downloader.py
│   ├── pipeline.py
│   ├── subtitles.py
│   ├── timeline.py
│   ├── transcriber.py
│   ├── translator.py
│   ├── tts.py
│   ├── utils.py
│   └── video_engine.py
├── PRDv2.md
└── uv.lock
```
