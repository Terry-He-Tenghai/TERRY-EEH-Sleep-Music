# 01 系统架构与实验闭环

更新：2026-10-11。返回 [目录](README.md)。

## 1. 当前主入口

后端由 [app.py](../../backEnd/app.py) 装配 FastAPI 路由和单例 `AcquisitionService`；前端由 [App.vue](../../frontEnd/src/App.vue) 管理受试者、实验条件、采集配置、WebSocket、音乐组件和后台页面。

```text
App.vue：受试者 + A/B/C + 采集/音乐配置
  -> POST /api/acquisition/start
  -> AcquisitionService.start
     -> Reports.start + 实验标签 + RawRecording
     -> BrainFlow 或 DEMO 采集线程
        -> 原始 EEG 文件
        -> AdaptiveWebService：测量侧分类/频段功率
        -> DisplayFilter：仅供网页波形
     -> 条件路由：A 外部 / B 独立脚本 / C 当前 EEG
  -> WebSocket：波形、状态、测量与音乐控制事件
  -> 浏览器 WebAudio：ACE 或上传背景 + MIDI
  -> sessionEvidence：事件 + 最终混音 PCM
  -> 报告保存 -> 后台标注、筛选和实验分析
```

后端输出的是分类结果和音乐计划；实际数字音频在浏览器中播放。计划已产生不代表音频已成功下载、解码或被受试者听见。

## 2. 三种实验条件

| 条件 | EEG 测量侧 | 音乐控制侧 | 本机音频记录 |
| --- | --- | --- | --- |
| A `fixed` | 仍采集、保存并计算可用 EEG 结果 | 外部设备固定播放；本机音乐静音 | 不录外部播放音频 |
| B `sham` | 仍采集并保存；测量事件为 `eeg_measurement` | 独立 DEMO showcase 信号，不使用该受试者当前 EEG | 可录浏览器输出 |
| C `closed_loop` | 采集并保存 | 有效当前 EEG 驱动分类和音乐更新 | 可录浏览器输出 |

`StartRequest.exclusive_music_source` 对 A 强制 `music_source=external`，清空音乐素材引用，关闭自动 SongEval。命名 A/B/C 实验必须有受试者标识，且强制 `save_raw_data=True`。

B 在 `AcquisitionService.start` 中启动第二个 `AdaptiveWebService` 和 `_run_sham` 线程，使用 `demo_profile=showcase`、250 Hz 合成样本。当前轨迹标识是 `showcase-96s-v1`。测量结果进入 `windows`，脚本控制进入 `control_windows`。B 的脚本分数不能被当作受试者生理结果。

当前 B 是预设脚本控制，不是已证明与 C 在更新次数、曲目或响度上严格匹配的 yoked 对照。实验材料、播放方式和控制轨迹的可比性需要协议另外规定并核验。

## 3. LIVE 和 DEMO 不同

[adaptive_web.py](../../backEnd/adaptive_web.py) 的 `_process` 根据来源分发：

- LIVE：进入 `_process_live_model`，使用 [waveform_classifier.py](../../backEnd/waveform_classifier.py)。加载失败时阻断，不自动切到频谱启发式。
- DEMO model：保留历史 `RealtimeSession`、特征基线和 joblib 模型，供软件演示。
- DEMO showcase：进入 `_process_showcase`，使用 [demo_showcase.py](../../backEnd/demo_showcase.py) 的预设阶段，不加载分类权重。

同一页面选中 C，但采集模式为 DEMO，并不能产生真实人体闭环证据。正式后台分析默认仅纳入 `mode=brainflow`。

## 4. 生命周期与终止

`AcquisitionService.start` 自动分配同一受试者、同一条件的下一个 `trial`，创建报告和原始记录目录。前端当前提交 2700 秒，即 45 分钟。后端允许 60 至 10800 秒；命名实验使用单调时钟设置截止时间。

结束原因包括时长完成 `duration_complete`、手动停止，以及采集或推理错误。线程清理负责关闭原始写入器、更新报告并释放设备。报告结束与浏览器混音上传不是同一个动作，后台应检查录音上传是否完成。

连续三个有效 N2 是音乐暂停条件，不是采集结束条件。`Reports.observe` 仍返回 N2 计数布尔值，但 `app.py` 不使用该返回值自动结束实验。

## 5. 运行范围

当前后端为共享单例设备、自动音乐与当前报告状态，不是多受试者并发服务。多个浏览器可看到同一会话；不能据此假设不同标签页是彼此隔离的实验。

当前网页音乐主路径是 ACE 或上传音频；保留四分轨 API 不代表网页提供四轨入口。详细依赖分类见 [07](07-code-file-guide.md)，实验指标和统计边界见 [06](06-session-reports-and-experiments.md)。
