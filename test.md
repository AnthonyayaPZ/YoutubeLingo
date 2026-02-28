# ShadowGen-Local 测试方案（模块级）

## 1. 测试目标与粒度

本方案按 4 个粒度设计：

- L0 单元测试：纯函数、数据结构、参数分支、异常分支。
- L1 组件测试：单模块内方法协作，外部依赖通过 mock/stub 隔离。
- L2 集成测试：多个模块串联，允许文件系统 I/O，禁用真实网络。
- L3 端到端冒烟：最短链路验证（`--mock` + 伪外部命令或真实 ffmpeg 环境）。

覆盖模块范围：

- `main.py`
- `shadowgen/config.py`
- `shadowgen/models.py`
- `shadowgen/utils.py`
- `shadowgen/downloader.py`
- `shadowgen/transcriber.py`
- `shadowgen/chunker.py`
- `shadowgen/translator.py`
- `shadowgen/tts.py`
- `shadowgen/timeline.py`
- `shadowgen/subtitles.py`
- `shadowgen/video_engine.py`
- `shadowgen/pipeline.py`

## 2. 测试环境与工具

- 依赖安装：`uv sync --group dev`
- 测试框架：`pytest`
- Mock：`pytest-mock` / `unittest.mock`
- 覆盖率：`pytest-cov`
- 临时目录：`tmp_path`
- 环境变量控制：`monkeypatch`
- 网络替身：mock `openai` 客户端与 `urllib.request.urlopen`
- 子进程替身：mock `shadowgen.utils.run_command`

建议目录：

- `tests/unit/`
- `tests/component/`
- `tests/integration/`
- `tests/e2e/`
- `tests/fixtures/`

## 3. 通用替身策略

- 外部命令（`ffmpeg`/`ffprobe`/`yt-dlp`）全部通过 mock `run_command` 控制返回值与错误码。
- 媒体时长探测通过 mock `probe_media_duration` 固定数值，避免依赖真实媒体文件。
- API Key 场景通过 `monkeypatch.setenv` / `delenv` 切换。
- 文件输出断言优先检查内容结构，不依赖平台换行符。

## 4. 模块测试矩阵

## 4.1 `main.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| MAIN-001 | L0 | 参数解析默认值 | `sys.argv=["main.py","--url","u"]` | 返回默认 `target_lang=zh`、`max_workers=4` 等 |
| MAIN-002 | L0 | 缺少 `--url` 且非 `--mock` | `sys.argv=["main.py"]` | 触发 `SystemExit` |
| MAIN-003 | L1 | 主流程成功 | mock `ShadowGenPipeline.run` 返回 4 个路径 | `main()` 返回 0 |
| MAIN-004 | L1 | 主流程失败 | mock `run` 抛异常 | `main()` 返回 1 |

## 4.2 `shadowgen/config.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| CFG-001 | L0 | 路径属性拼接 | 构造 `AppConfig(temp_dir=tmp_path/"temp")` | `tts_dir/clips_dir/frames_dir/source_video_path/source_audio_path` 正确 |
| CFG-002 | L1 | `prepare_dirs` 创建目录 | 初始目录不存在 | 目标目录全部创建成功 |
| CFG-003 | L1 | `prepare_dirs` 幂等 | 连续调用两次 | 无异常，目录保持存在 |

## 4.3 `shadowgen/models.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| MODEL-001 | L0 | 默认字段值 | 创建 `SemanticChunk`/`TranscriptionResult` | 默认值符合定义 |
| MODEL-002 | L0 | 可序列化字段 | dataclass 转 dict | 字段完整且类型正确 |

## 4.4 `shadowgen/utils.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| UTIL-001 | L0 | `sanitize_filename` 清理非法字符 | `a:b*c?` | 返回下划线替换结果 |
| UTIL-002 | L0 | `format_srt_timestamp` 边界 | `0`, `61.234`, `-1` | 输出 `00:00:00,000` 等正确格式 |
| UTIL-003 | L0 | `normalize_spaces` 去冗余空格 | `Hello  ,   world !` | 标点前空格被移除 |
| UTIL-004 | L1 | `retry` 成功重试 | 前两次抛错第三次成功 | 返回成功值，调用次数=3 |
| UTIL-005 | L1 | `retry` 最终失败 | 始终抛错 | 抛最后一次异常 |
| UTIL-006 | L1 | `run_command` 成功 | mock `subprocess.run(returncode=0)` | 返回对象 |
| UTIL-007 | L1 | `run_command` 失败且 `check=True` | `returncode!=0` | 抛 `RuntimeError`，消息含 stdout/stderr |
| UTIL-008 | L0 | `ffmpeg_subtitles_path` 转义 | 路径含 `:`、`'` | 返回可用于 FFmpeg 的滤镜字符串 |
| UTIL-009 | L1 | `ensure_command_exists` | mock `shutil.which` 返回 `None` | 抛缺失依赖异常 |

## 4.5 `shadowgen/downloader.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| DL-001 | L1 | `mock=True` 走假视频生成 | mock `run_command` | 调用 ffmpeg 命令，返回 `Mock_Demo` |
| DL-002 | L1 | 正常下载并重命名 | mock `run_command` + 在 temp 放 `source.webm` | 最终产物为 `source.mp4` |
| DL-003 | L1 | 多候选文件选最新 | 创建多个 `source.*` 不同 mtime | 选择最新文件 |
| DL-004 | L1 | 忽略 `.part` | 仅有 `.part` 文件 | 抛“no source file”异常 |
| DL-005 | L1 | 重试机制接入 | mock `_download_once` 前失败后成功 | `download()` 最终成功 |

## 4.6 `shadowgen/transcriber.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| ASR-001 | L1 | `mock` 后端 | `config.mock=True` | 返回固定 mock 结果 |
| ASR-002 | L1 | `auto`：whisperx 失败回退 whisper | mock `_transcribe_with_whisperx` 抛错、whisper 成功 | 返回 whisper 结果 |
| ASR-003 | L1 | `auto`：whisperx 与 whisper 都失败 | 两者都抛错 | 返回 `_fallback_result` |
| ASR-004 | L1 | 指定 `whisperx` 失败 | `backend=whisperx` | 异常直接抛出，不回退 |
| ASR-005 | L1 | 指定 `whisper` 失败 | `backend=whisper` | 异常直接抛出 |
| ASR-006 | L0 | fallback 时长下限 | `media_duration=0.2` | segment end 至少 `1.0` |
| ASR-007 | L0 | CUDA 检测 | mock `torch.cuda.is_available` | True/False 分支正确 |

## 4.7 `shadowgen/chunker.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| CHUNK-001 | L0 | 有 `words` 时按词切块 | 构造带句号词列表 | 句末正确断块 |
| CHUNK-002 | L0 | 超过 `max_words` 断块 | 设置 `max_words=3` | 每块词数不超过 3 |
| CHUNK-003 | L0 | 超过 `max_duration` 断块 | 设置 `max_duration` 很小 | 按时长断块 |
| CHUNK-004 | L0 | 空白词跳过 | 包含空字符串词 | 不进入块文本 |
| CHUNK-005 | L0 | 无词级数据回退 segment | `transcription.words=[]` | chunk 数量与 segment 一致 |
| CHUNK-006 | L0 | 文本空格标准化 | 输入多空格与标点空格 | 输出符合 `normalize_spaces` |

注：当前代码中的中文标点字符存在编码风险，需专门加一个断句字符回归用例，避免“中文句末不切块”。

## 4.8 `shadowgen/translator.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| TR-001 | L1 | `mock` 后端 | `backend=mock` | 返回 mock 翻译文本 |
| TR-002 | L1 | `deepl` 缺 key | 清空 `DEEPL_API_KEY` | 抛明确错误 |
| TR-003 | L1 | `openai` 缺 key | 清空 `OPENAI_API_KEY` | 抛明确错误 |
| TR-004 | L1 | `auto` 优先 DeepL | 同时设置两个 key，mock deepl/openai | 优先调用 deepl |
| TR-005 | L1 | DeepL 响应空结果 | mock `urlopen` 返回 `translations=[]` | 抛异常 |
| TR-006 | L1 | OpenAI 空文本回退 mock | mock message content 空字符串 | 返回 mock 翻译 |
| TR-007 | L0 | `target_lang` 映射 | `zh/zh-cn/zh-hans/en` | 返回 `ZH/EN` 等 |
| TR-008 | L1 | API 调用重试 | mock 第一次异常第二次成功 | 最终成功 |

## 4.9 `shadowgen/tts.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| TTS-001 | L1 | `silent` 后端 | `backend=silent` | 调 ffmpeg 生成静音，返回时长 |
| TTS-002 | L1 | `auto` Edge 成功 | mock `_edge_tts` + `probe_media_duration` | 返回探测时长 |
| TTS-003 | L1 | `auto` Edge 失败回退 silent | `_edge_tts` 抛错 | 调用 `_silent_tts` |
| TTS-004 | L1 | 指定 `edge` 失败 | `backend=edge` 且 `_edge_tts` 抛错 | 异常上抛 |
| TTS-005 | L0 | 静音时长估算上下界 | 极短文本/超长文本 | 时长范围 [1,12] |
| TTS-006 | L1 | 事件循环已存在分支 | mock `asyncio.run` 抛 `RuntimeError` | 能走 `new_event_loop` 成功 |

## 4.10 `shadowgen/timeline.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| TL-001 | L0 | 正常时间轴重构 | 2 个 chunk | rebuilt 时间连续无重叠 |
| TL-002 | L0 | 原始时长为负/零 | `end<=start` | 采用 0.05 下限 |
| TL-003 | L0 | tts 时长为负/零 | `tts_duration<=0` | 采用 0.05 下限 |

## 4.11 `shadowgen/subtitles.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| SUB-001 | L0 | 双语+中文条目生成 | 1 个 chunk | 产出 2 条字幕 |
| SUB-002 | L0 | 无翻译时中文条目回退原文 | `translation=""` | 第二条字幕文本为原文 |
| SUB-003 | L1 | 写 SRT 格式 | 调用 `write_srt` | 序号/时间轴/空行结构正确 |
| SUB-004 | L1 | UTF-8 写入 | 含中文文本 | 文件编码为 UTF-8，可读回 |

## 4.12 `shadowgen/video_engine.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| VE-001 | L1 | `probe_media_duration` 正常解析 | mock `run_command.stdout="12.34"` | 返回 `12.34` |
| VE-002 | L1 | `probe_media_duration` 空输出 | stdout 为空 | 抛异常 |
| VE-003 | L1 | `extract_audio` 命令参数 | mock `run_command` | 包含 `-vn -ac 1 -ar 16000` |
| VE-004 | L1 | `_render_chunk_pair` 缺 `tts_path` | `tts_path=None` | 抛异常 |
| VE-005 | L1 | `_render_chunk_pair` 三段命令完整 | mock `run_command` | 依次调用原片切片/抽帧/静帧合成 |
| VE-006 | L1 | `_concat_clips` 空列表 | `clips=[]` | 抛异常 |
| VE-007 | L1 | `_concat_clips` 写 concat 清单 | 2 个 clip | `concat.txt` 内容与转义正确 |
| VE-008 | L1 | `render_shadowing_video` 排序拼接 | 输入 chunk 顺序打乱 | 仍按 id 顺序拼接 |
| VE-009 | L1 | `burn_subtitles=False` 分支 | mock `_concat_clips` | 使用 `replace`，不调用 `_burn_subtitles` |
| VE-010 | L1 | `export_mp3` 命令参数 | mock `run_command` | 包含 `libmp3lame` |

## 4.13 `shadowgen/pipeline.py`

| 用例ID | 粒度 | 场景 | 输入/前置 | 预期 |
|---|---|---|---|---|
| PL-001 | L1 | 依赖检查（mock 模式） | `mock=True` | 检查 `ffmpeg/ffprobe`，不检查 `yt-dlp` |
| PL-002 | L1 | 依赖检查（非 mock） | `mock=False` | 额外检查 `yt-dlp` |
| PL-003 | L2 | 主流程成功 | 全模块 mock 返回稳定值 | 输出 4 个交付物路径 |
| PL-004 | L2 | 分块为空 | mock `chunker.chunk` 返回空 | 抛 `No semantic chunks` |
| PL-005 | L2 | `_translate_and_tts` 并发后排序 | 输入 chunk id 乱序 | 返回按 id 升序 |
| PL-006 | L1 | 写 `WordLevel_Data.json` 结构 | 调 `_write_wordlevel_json` | `language/segments/words/chunks` 字段完整 |
| PL-007 | L2 | `finally` 清理临时目录 | `keep_temp=False` 且中途异常 | `_cleanup_temp` 仍执行 |
| PL-008 | L2 | 保留临时目录 | `keep_temp=True` | 不调用 `_cleanup_temp` |

## 5. 集成与端到端方案

## 5.1 集成测试（无真实网络）

- IT-001：`downloader -> transcriber(mock) -> chunker -> translator(mock) -> tts(silent) -> timeline -> subtitles`，验证中间产物一致性。
- IT-002：`pipeline.run` 全链路（mock 外部命令），断言最终调用顺序与产物命名规则 `[Title]_*.{mp4,mp3,srt,json}`。
- IT-003：异常注入（翻译失败、视频渲染失败），验证重试与清理逻辑。

## 5.2 端到端冒烟（建议两档）

- E2E-A（离线）：`python main.py --mock --transcribe_backend mock --translator_backend mock --tts_backend silent`
- E2E-B（在线可选）：真实 URL + `yt-dlp` + `ffmpeg` + `whisperx/whisper`，验证真实产物可播放、字幕可读。

## 6. 非功能测试

- NFT-001 性能：100 个 chunk 条件下，统计 `_translate_and_tts` 与 `render_shadowing_video` 并发耗时。
- NFT-002 稳定性：连续运行 20 次 mock 链路，确认无临时目录泄漏。
- NFT-003 容错：模拟 API 超时与命令失败，确认重试次数与最终错误信息可诊断。

## 7. 质量门禁

- 单元测试通过率：100%
- 关键路径覆盖率（`pipeline.py`、`video_engine.py`、`downloader.py`、`transcriber.py`）：>= 85%
- 全量覆盖率：>= 75%
- E2E-A 必须通过后才能合并

## 8. 执行建议命令

```bash
uv run pytest -q
uv run pytest tests/unit -q --maxfail=1
uv run pytest tests/component -q
uv run pytest tests/integration -q
uv run pytest tests/e2e -q -m smoke
uv run pytest --cov=shadowgen --cov=main --cov-report=term-missing
```
