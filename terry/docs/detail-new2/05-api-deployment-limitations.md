# 05 接口、依赖与部署边界

更新：2026-10-11。返回 [目录](README.md)。

## 1. 本地服务

| 服务 | 常用端口 | 是否必需 |
| --- | --- | --- |
| Vue/Vite 前端 | 5173 | 当前网页必需 |
| FastAPI 后端 | 8000 | 采集、报告和音乐代理必需 |
| ACE-Step | 默认连接 8001 | ACE 路径必需，外部服务 |
| SongEval | 默认连接 8002 | 可选分析，不是闭环前置条件 |
| Demucs 分离服务 | 按独立配置 | 参考伴奏分离路径需要 |

[vite.config.js](../../frontEnd/vite.config.js) 在开发时代理 `/api` 和 `/ws` 到后端。`VITE_API_BASE` 影响前端地址配置；跨域部署还需核对 WebSocket、代理和后端允许来源，不能直接把 Vite 开发配置当作生产配置。

## 2. 采集与状态 API

| 方法与路径 | 作用 |
| --- | --- |
| `GET /api/health` | 后端健康检查 |
| `GET /api/status` | 采集、原始记录和实验状态 |
| `GET /api/adaptive/status` | 当前音乐控制状态；B 附测量侧状态 |
| `POST /api/acquisition/start` | 创建并启动会话 |
| `POST /api/acquisition/stop` | 手动结束 |
| `GET /api/acquisition/recording-info` | 原始保存能力/版本信息 |
| `WS /ws/waveform` | 状态、显示波形和分类/控制事件 |

命名 A/B/C 的最小请求意图示例，不代表应在真实设备上自动执行：

```json
{
  "mode": "brainflow",
  "sample_rate_hz": 250,
  "classification_channels": 4,
  "experiment_duration_s": 2700,
  "save_raw_data": true,
  "music_source": "ace",
  "music_style": "ambient",
  "experiment": {
    "participant": "P001",
    "condition": "closed_loop",
    "visit": 1
  }
}
```

实际设备地址、接线和增益应按现场核验设置。API `music_source` 默认仍是 `stems`，网页则显式提交 ACE/upload 或 A 的 external；直接调用 API 时必须指定所需来源。

## 3. 音乐与报告路由

- `/api/music`：素材库、候选及上传；`music_choices.py` 将上传 WAV 转换为 44100 Hz PCM16，但不等于感知响度标准化。
- `/api/music-workbench`：手动计划、MIDI 下载。
- `/api/stem-music`：保留四轨接口；当前前端主入口未提供四轨选择。
- `/api/ace`：styles、health、generations、任务查询、音频、extractions 和 automatic/status。
- `/api/session-reports`：列表、报告详情、browser 事件、audio 上传/下载、experiment 标签、physiology 导入、songeval。
- `/api/session-reports/experiments/summary`、`export.csv`、`analysis`：实验行、导出与参与者级分析；analysis 支持 `ids` 和 `include_demo`。

具体字段以 [app.py](../../backEnd/app.py)、[ace_step.py](../../backEnd/ace_step.py)、[session_reports.py](../../backEnd/session_reports.py) 的模型和处理函数为准。

## 4. 依赖与启动文件

[pyproject.toml](../../backEnd/pyproject.toml) / `uv.lock` 管理完整后端依赖；`web`、`hardware`、`waveform` extras 分别提供 FastAPI、BrainFlow 和当前 CNN 依赖。历史 DEMO joblib 的 sklearn 版本也仍受约束。

[start_backend.command](../../backEnd/start_backend.command) 在 macOS/Unix 入口中执行 uv 同步并绑定 `127.0.0.1:8000`。[start_waveform_backend.ps1](../../backEnd/start_waveform_backend.ps1) 使用训练 venv，先预检五种模型契约，再启动服务。[start_all.command](../../start_all.command) 为 macOS 双击启动辅助，端口占用时拒绝继续，不杀已有服务。

`requirements-waveform-live.txt` 是专项依赖说明，不包含整个系统的所有资源和分析依赖，不能取代完整环境核对。`script/` 的三个模型契约文件和对应权重也必须随运行目录保留。

## 5. 外部服务配置

| 配置 | 用途 |
| --- | --- |
| `ACE_STEP_URL` | ACE 代理目标，默认 `http://127.0.0.1:8001` |
| `ACE_STEP_API_KEY` | 可选服务凭据 |
| `SONGEVAL_API_URL` | SongEval 目标，默认 `http://127.0.0.1:8002` |
| `SONGEVAL_ROOT` | 独立 SongEval 服务器模型资源目录 |
| `MUSIC_AUDIO_EVALUATOR_COMMAND` | 可选本地实际音频评价命令 |
| `TERRY_WEB_ORIGINS` | 后端 CORS 允许来源 |
| `TERRY_BABYSLAKH_ROOT` | 保留四轨素材目录 |

本地 ACE 代理和独立 `songeval_server.py` 并不包含全部远端模型服务。隧道、权重、运行环境和鉴权需单独配置。不得在文档或报告中写入服务密钥。

## 6. 部署限制

当前系统没有多租户隔离或实验管理鉴权，不应直接开放公共网络。实验标识与原始 EEG 属于敏感研究数据，建议使用受试者编号、限制文件访问并确定备份和保留策略。

当前资源统计只覆盖后端进程，不能据此声称 ACE/SongEval 能在树莓派本地运行。远端生成、网络、浏览器内存和音频设备资源必须单独测量。浏览器最终混音为双声道 Float32 PCM，360 MiB 缓存上限在 48 kHz 下约容纳 16.4 分钟，故当前不能默认保存完整 45 分钟音频；应检查 `recording_status` 与实际录制时长。原始 EEG 另有独立保存链路。
