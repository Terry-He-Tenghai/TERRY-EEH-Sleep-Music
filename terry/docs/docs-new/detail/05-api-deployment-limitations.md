# 05｜API、部署、测试与限制

更新：2026-10-07。返回[主文档](../系统架构与功能.md)。以下端点来自当前路由，不表示远端服务已在本机运行。

## 1. 采集接口

- `GET /api/health`：本地进程健康，不检查帽子/权重/远端素材。
- `GET /api/status`：采集连接、配置、样本数量和report_id。
- `GET /api/adaptive/status`：最新音乐计划/分类事件，不等同实际播放。
- `POST /api/acquisition/start`：选择mode/demo_profile、IP/port、gain、sample_rate_hz、classification_channels、music_source/music_style、uploaded_track_id/reference_track_id/stem_track_id。
- `POST /api/acquisition/stop`：停止并完成报告；WebSocket `/ws/waveform`发送状态、显示波形和adaptive消息。

合法mode为demo/brainflow；model/showcase为演示配置；classification_channels为2/4/6/8/16。上传底轨和分轨互斥；参考文件只用于ACE。ACE需五种明确风格之一，不能同时指定普通底轨或BabySlakh。运行时重复start返回已有会话，须stop后再改配置。

## 2. 音乐素材与生成

- `GET /api/music`：清单及可用性；`GET /api/music/{track_id}/audio`：安全读取本地音频。
- `GET /api/music/choices`：风格及可用素材数；`POST /api/music/uploads`：本地raw WAV body，非multipart文件名；返回user_编号。
- `GET /api/stem-music`、`GET /api/stem-music/{track_id}/stems/{stem_id}/audio`：20首候选/指定四轨的原始WAV。
- `GET /api/music-workbench/plan`、`GET /api/music-workbench/midi`：手动M状态符号计划/标准MIDI导出。
- `GET /api/ace/styles`、`GET /api/ace/health`、`GET /api/ace/automatic/status`：风格、远端健康和自动生成状态。
- `POST /api/ace/generations`：style、description、duration（10–120秒）、可选reference_track_id；参考cover长度改取原源10–600秒。
- `POST /api/ace/extractions`：reference_track_id＋白名单track；`GET /api/ace/generations/{task_id}`及`.../audio`供上述两类任务查询/播放。

上传归一化：SoundFile解码WAV/WAVEX/RF64，时长>0且≤900秒，解码frames×channels≤40000000；多于双声道平均成单声道，抗混叠重采样44100Hz，超范围峰值缩放后保存PCM16。源请求允许audio/wav或audio/x-wav并检查本机Origin。**最新实现不是旧的“只接收8–900秒/80MB标准PCM16”规则；streaming上传循环未提供统一字节上限，解码限制及磁盘余量检查是另外的防线。** 对外部署需额外配置网关大小/权限限制。

## 3. 报告与实验

- `GET /api/session-reports`：最近最多100份完整JSON；`GET /api/session-reports/{id}`：单份报告。
- `POST /api/session-reports/{id}/browser`：追加浏览器事件/录音元数据；`PUT .../{id}/audio`：上传最终WAV及分析；`GET .../{id}/audio`：下载录音。
- `GET /api/session-reports/experiments/summary`：本地报告实验行与保存目录；`GET .../experiments/export.csv`：全部汇总CSV。
- `PUT /api/session-reports/{id}/experiment`：participant（匿名字符限制）、condition、trial、notes、comfort/musicality 1–7或null。

标签不改变播放模式；API没有随机分配或sham序列生成。CSV导出是全部数据，不一定沿用前端当前筛选。

## 4. 启动与环境

在Windows已配置的Conda环境、当前backEnd目录使用：

```powershell
conda activate D:\pythonenv\conda_envs\terry-backend
cd E:\project\test\terry\new_code\TERRY-EEH-Sleep-Music\terry\backEnd
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

移动仓库后，可编辑安装需重新指向当前目录（`python -m pip install --no-deps -e .`）；必须核对 `anphy_sleep.__file__`/streaming模块来源，工作目录变更不会修正旧安装。该命令不安装所有依赖，新环境仍需按pyproject及实时/训练说明安装。旧DEMO joblib依赖版本与当前锁文件需一致。

`start_waveform_backend.ps1`使用 `terry/script/.venv` 预检五份权重；与当前Conda命令是两种选择，不可混同环境。`start_backend.command/start_all.command`属于Unix/macOS启动入口，不是PowerShell命令。

前端目录执行 `npm install` 后 `npm run dev`，Vite默认5173把/api与/ws代理8000；生产build后须另配置同源API/WebSocket代理或VITE_API_BASE/VITE_WS_BASE。直接file打开dist不能视为部署成功。

## 5. 可选远端服务

ACE默认 `ACE_STEP_URL=http://127.0.0.1:8001`，可选Bearer token仅后端读取；分离 `AUDIO_SEPARATOR_URL=http://127.0.0.1:8002`。不要在文档或前端包含实际密钥。部署说明见 `../../../backEnd/AUDIO_SEPARATION.md`；其示例服务器路径不等于当前环境已存在。

`remote_audio_separator.py`独立FastAPI、Demucs htdemucs CPU、6线程、单推理锁和内容哈希缓存；默认/root/autodl-tmp目录，不能原样假设适用于本地Windows。首次可下载权重，依赖demucs，普通后端不导入该模块。分离请求上限80000000字节/≤600.1秒、最多双声道。

ACE cover需要音频先传分离服务再传生成服务，用户上传音频**不再始终“仅本机保留”**；生成/分离缓存与报告录音是敏感素材，应授权并明确保留/删除策略。普通背景上传读取则是本地路径。

## 6. 测试与验收区分

- 后端 `tests/`：采集、模型契约、连续性、队列恢复、生成门控、上传格式、报告/音频/实验统计等。
- 前端 `npm test`：Node执行组件脚本/模拟音频节点与工具测试，不能证明设备/真实扬声器已验收。
- `npm run test:browser`：Playwright网页行为；新增language/session-report/experiment-admin用例，多用拦截API，非完整外部服务真实闭环。
- `npm run build`：生产编译，不能证明远端可达、权限和素材可用。

本轮只阅读代码及校验文档，不把之前414/57等旧测试数字搬作当前ace3a4e测试结果。

## 7. 部署边界与安全

报告、素材读取存在路径格式/白名单防护，但没有完整账号认证和租户隔离；CORS是来源配置而非鉴权。采集服务为单会话，避免多workers/多人同时控制设备。报告会存声音和匿名标签，需要访问控制、磁盘空间和清理机制。录音缺失、未测指标应保持null，不补0或编造临床/艺术性结论。