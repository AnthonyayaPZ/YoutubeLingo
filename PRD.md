# 产品需求文档 (PRD)：YouTube 影子跟读本地生成器 (ShadowGen-Local)
## 1. 产品概述
- 产品形态：基于 Python 的本地自动化脚本/命令行工具（CLI）。未来可套一层简单的本地 GUI（如 Tkinter 或 PyQt）。

- 核心目标：输入 YouTube URL，全自动在本地完成“视频下载 -> 语音识别断句 -> 机器翻译 -> 中文语音生成 -> 视频切片与静帧合并 -> 最终视频渲染”，输出一个专供“影子跟读”的本地 .mp4 文件。

## 2. 核心执行流程 (Execution Flow)
用户在终端输入命令，例如：python main.py --url <YouTube_URL>，随后程序全自动执行以下流程：

1. 资源获取：解析 URL 并下载最高画质（或指定分辨率）的视频及音频流。

2. 语音与文本对齐：提取视频音频，使用本地 AI 模型进行精准的 VAD（语音活动检测）和 ASR（语音识别），输出带精确时间戳的英文句子级数据。

3. 翻译与 TTS 处理：

    - 将英文文本翻译为中文。

    - 调用 TTS 引擎生成对应的中文 .wav/.mp3 音频文件，并记录时长。

4. 视频组装与渲染 (Video Rendering)：

    - 按照时间戳，将原视频“切”出对应的英文句子片段。

    - 截取该片段的最后一帧。

    - 将最后一帧画面延长，时长等同于中文 TTS 音频的时长，并将中文 TTS 音频混流进去，生成“中文静帧解释片段”。

    - 将所有“原声片段”和“中文静帧解释片段”按顺序无缝拼接。

5. 清理与输出：删除所有中间生成的临时切片文件，输出最终的 Output_Shadowing.mp4 到本地指定目录。

## 3. 核心模块与技术选型 (Technical Requirements)
#### 3.1 下载模块
- 核心工具：yt-dlp (Python 库)。

- 逻辑：直接拉取合并好的高质量音视频文件到本地 /temp 目录。

#### 3.2 AI 语音识别与时间轴抽取模块 (核心难点 1)
为了摆脱 YouTube 字幕时间轴不准的问题，建议直接走音频分析。

- 核心工具：Whisper (OpenAI 开源模型，可利用本地 PyTorch 环境和 GPU 加速) 或 WhisperX (能提供更极端的单词级精确时间戳和 VAD 优化)。

- 数据结构输出：

    ```json
    [
    {"id": 1, "start": 0.52, "end": 3.10, "text": "This is a neural network."},
    {"id": 2, "start": 3.15, "end": 6.80, "text": "It consists of multiple layers."}
    ]
    ```
#### 3.3 翻译与语音生成模块
- 翻译 API：调用 DeepL API 或直接本地跑一个小参数量的机器翻译模型（如果你本地显存足够）。

- TTS 生成：推荐使用 edge-tts（Python 开源库，直接调用微软 Edge 浏览器的免费高质量 TTS 接口，声音自然，免 API Key），批量生成对应的中文音频。

#### 3.4 视频剪辑与渲染引擎 (核心难点 2)
这是本地跑的主战场。

- 核心工具：MoviePy (Python 视频编辑库，底层基于 FFmpeg，代码逻辑极度清晰) 或直接构造 FFmpeg 复杂命令（渲染速度最快）。

- 渲染优化：视频渲染是计算密集型任务。在切片和生成静帧片段时，由于各个片段之间互不依赖，非常适合引入并行处理机制。可以使用 Python 的 multiprocessing 或构建类似多线程池的逻辑，同时处理多个片段的静帧合成，最后再单线程把它们 concatenate 起来，以此大幅压榨本地多核 CPU 的性能。

## 4. 目录结构设计参考
为了保持工程整洁，运行时的本地目录架构应如下：
```Plaintext
/ShadowGen
  ├── main.py              # 入口脚本
  ├── downloader.py        # yt-dlp 下载逻辑
  ├── transcriber.py       # Whisper 识别与时间轴对齐逻辑
  ├── translator.py        # 翻译与 Edge-TTS 逻辑
  ├── video_engine.py      # MoviePy/FFmpeg 切片与合成逻辑
  ├── /temp                # 工作区 (运行时产生几百个碎文件)
  │   ├── source.mp4       # 原视频
  │   ├── source_audio.wav # 抽离的音频 (供 Whisper 用)
  │   ├── /tts             # 存放生成的中文语音
  │   └── /clips           # 存放切好的视频段和静帧段
  └── /output              # 最终成品目录
```