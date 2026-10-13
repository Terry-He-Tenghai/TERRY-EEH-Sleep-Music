# 07 当前代码文件职责与保留边界

更新：2026-10-11。返回 [目录](README.md)。本文按当前本地工作区源码（含未提交改动）重写旧版 [07 代码文件指南](../docs-new/detail/07-code-file-guide.md)；路径以 `terry/` 为根。这里的“必需”指指定运行路径，而非所有 A/B/C 条件都调用文件里的每个函数。文件被导入或路由已注册，也不等于该功能是当前实验的主要入口；“主入口未调用”也不等于可以安全删除。

## 1. 从实验开始到报告的最短路径

```text
frontEnd/src/App.vue (受试者、A/B/C、设备、音乐)
  -> backEnd/app.py /api/acquisition/start
  -> RawRecording 写原始 EEG；DisplayFilter 只用于显示
  -> AdaptiveWebService -> WaveformClassifier (LIVE)
     -> EEG 测量窗口/Alpha-Theta 频段功率
     -> A: 外部播放，不在网页播放
     -> B: 测量照常进行，另起独立 showcase 控制音乐
     -> C: 测量侧有效 EEG 控制音乐
  -> ACE 或上传背景+MIDI 的浏览器播放器
  -> sessionEvidence -> Reports -> ExperimentAdmin -> 实验统计
```

仅选择网页的 C 不保证真实人体闭环：必须同时使用 `mode=brainflow`、250 Hz、匹配接线及可加载权重。A/B/C 命名实验强制原始数据保存，B 的 `control_windows` 不能算作人体脑电。详细条件定义见 [01](01-system-architecture.md)。

## 2. 后端：当前运行主链

| 代码 | 当前职责 | 边界 |
| --- | --- | --- |
| [app.py](../../backEnd/app.py) | FastAPI、采集单例、A/B/C 生命周期、设备线程、WS 与路由装配 | A 外部静音、B 双 worker、C 测量侧控制；不会因 N2 自动结束采集 |
| [adaptive_web.py](../../backEnd/adaptive_web.py) | 有界推理队列、连续性校验、LIVE/DEMO 分类到音乐计划 | `_process_live_fallback` 留作诊断，不是 LIVE 自动降级入口 |
| [waveform_classifier.py](../../backEnd/waveform_classifier.py) | LIVE CNN、权重契约、通道 QC、Alpha/Theta 频段功率 | W/N1/N2 研究分类，非旧特征未来 N2 预测 |
| [channel_mapping.py](../../backEnd/channel_mapping.py) | `CAP_ORDER` 供采集/LIVE 通道顺序验证 | 历史通道映射不代表额区模型采用缺失通道插值 |
| [raw_recording.py](../../backEnd/raw_recording.py) | 原始 16 路微伏和设备时间/包计数异步 CSV 写入及完整性标记 | `complete` 不等于信号质量合格 |
| [display_filter.py](../../backEnd/display_filter.py) | 页面波形显示滤波 | 显示数据不送给 CNN 或原始记录器 |
| [demo_showcase.py](../../backEnd/demo_showcase.py) | B 脚本化控制和独立 DEMO showcase | 不是参与者真实睡眠分期 |
| [session_reports.py](../../backEnd/session_reports.py) | 报告路由/存储、测量与控制窗口、实验字段、浏览器音频、trace 和统计接口 | 报告结束不证明浏览器音频上传完毕 |
| [experiment_analysis.py](../../backEnd/experiment_analysis.py) | 阶段功率、问卷/实验汇总、探索性配对统计；保留可选外部生理数据解析 | 不直接连接心率硬件，不自动给出 EEG 过渡速度 |
| [ace_step.py](../../backEnd/ace_step.py)、[ace_music_prompts.py](../../backEnd/ace_music_prompts.py) | ACE 代理/自动任务、阶段生成、N2 暂停、风格/和声提示词 | ACE 是外部服务；任务提交不等于播放成功 |
| [eeg_music_modulation.py](../../backEnd/eeg_music_modulation.py) | 有效状态转上传/MIDI 参数、音符和控制量 | 计划不是最终声学输出 |
| [music_choices.py](../../backEnd/music_choices.py)、[music_library.py](../../backEnd/music_library.py) | 上传、规范化、素材查询/安全读取 | 上传曲音量增益与 ACE 的增益策略不同 |
| [music_evaluation.py](../../backEnd/music_evaluation.py) | 可选实际音频评价适配器，由报告模块导入 | 未配置命令时返回 unavailable，不是人工音乐性评分 |

`app.py` 同时导入/注册 [music_workbench.py](../../backEnd/music_workbench.py) 和 [babyslakh.py](../../backEnd/babyslakh.py)：前者提供已挂载页面的手动 MIDI 实验台，后者是**仍注册的四轨 API 和 `adaptive_web.py` 的导入依赖**，不是当前 A/B/C 页面的默认音乐来源。不要把“未显示四轨面板”误写成“可移除后端模块”。[powerline_filter.py](../../backEnd/powerline_filter.py) 在 `app.py` 中被实例化，采集发布主路没有调用其处理方法，不能将其算作已串联到 EEG 模型的滤波步骤。

## 3. 运行时复用的训练代码与公共包

- [train_sleep_waveform_models.py](../../script/train_sleep_waveform_models.py)：`WaveformClassifier` 动态载入其预处理/网络定义；8/16 权重契约所需。
- [train_sleep_frontal_models.py](../../script/train_sleep_frontal_models.py) 与 [train_sleep_subset_models.py](../../script/train_sleep_subset_models.py)：额区 2/4/6 的契约与复用实现，运行时仍要保留。`subset` 同时也是历史中央 montage 的独立训练入口。
- [config.waveform.yaml](../../backEnd/config.waveform.yaml) 和相应 `results/waveform_frontal_v1` / `results/waveform_cap_v1` 权重：模型路径/门槛及实际参数，缺文件或契约不符则阻断 LIVE。
- [contracts.py](../../backEnd/src/anphy_sleep/contracts.py)：LIVE 的 `StateUpdate` 数据契约；[scheduler.py](../../backEnd/src/anphy_sleep/music_engine/scheduler.py)、[midi.py](../../backEnd/src/anphy_sleep/music_engine/midi.py)、[layers.py](../../backEnd/src/anphy_sleep/music_engine/layers.py)、[waveform.py](../../backEnd/src/anphy_sleep/music_engine/waveform.py)：上传/MIDI 计划及手动实验台复用的音乐原语。
- [config.py](../../backEnd/src/anphy_sleep/config.py)、[streaming.py](../../backEnd/src/anphy_sleep/streaming.py)、[features.py](../../backEnd/src/anphy_sleep/features.py)、[inference.py](../../backEnd/src/anphy_sleep/inference.py)、[io.py](../../backEnd/src/anphy_sleep/io.py)、[music.py](../../backEnd/src/anphy_sleep/music.py)：DEMO model 的配置/旧特征推理依赖，并非 LIVE CNN 的推理算法。`anphy_sleep/__init__.py` 会导出旧音乐/流式模块；先做真实导入图和启动验证，再考虑拆包瘦身。
- [classification_gate.py](../../backEnd/classification_gate.py) 与 [channel_repair.py](../../backEnd/channel_repair.py)：仍用于 DEMO model；[degraded_classifier.py](../../backEnd/degraded_classifier.py) 和 [pretrained_classifier.py](../../backEnd/pretrained_classifier.py) 只在 LIVE 不可达的诊断 `_process_live_fallback` 中按需导入。均不构成 LIVE 自动回退。

`src/anphy_sleep/music_engine/__init__.py` 会导出 `waveform.py`，即使当前网页不使用它写 WAV，导入音乐包也可能加载它。删除时必须考虑包初始化的间接依赖。

## 4. 前端：实际页面和播放证据

| 文件/组 | 页面内用途 |
| --- | --- |
| [App.vue](../../frontEnd/src/App.vue)、[main.js](../../frontEnd/src/main.js)、[style.css](../../frontEnd/src/style.css) | 页面挂载、A/B/C 配置、采集与导航、布局 |
| [i18n.js](../../frontEnd/src/i18n.js)、[audioMessages.js](../../frontEnd/src/audioMessages.js) | 中英文本及音频状态文案 |
| [WaveformQuality.vue](../../frontEnd/src/components/WaveformQuality.vue)、[modelChannels.js](../../frontEnd/src/audio/modelChannels.js) | 波形与实际来源电极、模型选择、QC 呈现；额区名义 Fp2 来自设备 C3 |
| [AutomaticAcePanel.vue](../../frontEnd/src/components/AutomaticAcePanel.vue)、[liveClassification.js](../../frontEnd/src/audio/liveClassification.js)、[demoOrigin.js](../../frontEnd/src/audio/demoOrigin.js) | ACE 自动播放，LIVE 来源/新鲜度门控和演示来源区分 |
| [AdaptiveMusicPanel.vue](../../frontEnd/src/components/AdaptiveMusicPanel.vue)、[adaptiveEngine.js](../../frontEnd/src/audio/adaptiveEngine.js)、[uploadLoudness.js](../../frontEnd/src/audio/uploadLoudness.js) | 上传背景 + MIDI、计划/质量门控、曲目过渡及数字增益 |
| [HarmonyControls.vue](../../frontEnd/src/components/HarmonyControls.vue)、[GenreControl.vue](../../frontEnd/src/components/GenreControl.vue)、[music_harmony.json](../../music_harmony.json) | 音乐风格、调式/和弦输入 |
| [sessionEvidence.js](../../frontEnd/src/audio/sessionEvidence.js)、[finalMixRecorder.js](../../frontEnd/public/finalMixRecorder.js) | 浏览器事件和最终数字混音 PCM 录制/上传；A 外部播放不录 |
| [ExperimentAdmin.vue](../../frontEnd/src/components/ExperimentAdmin.vue)、[ExperimentCharts.vue](../../frontEnd/src/components/ExperimentCharts.vue)、[EegPowerShifts.vue](../../frontEnd/src/components/EegPowerShifts.vue)、[SessionReportPanel.vue](../../frontEnd/src/components/SessionReportPanel.vue) | 搜索同一受试者多次试验、审核/统计、Alpha/Theta 偏移和报告查看 |

[MusicWorkbench.vue](../../frontEnd/src/components/MusicWorkbench.vue) / [manualEngine.js](../../frontEnd/src/audio/manualEngine.js) / [midiEditing.js](../../frontEnd/src/audio/midiEditing.js) 是页面内已挂载的手动高级工具。[AceMusicPanel.vue](../../frontEnd/src/components/AceMusicPanel.vue) 是已挂载的 ACE 生成调试；[AceStemPanel.vue](../../frontEnd/src/components/AceStemPanel.vue) 是已挂载的参考音频声部提取，**不是**旧四轨 `StemMusicPanel`。这些操作需在正式实验中限制或记录偏离。

## 5. 旧功能、可选服务与离线材料

| 类别 | 文件 | 现状与处置 |
| --- | --- | --- |
| 页面未挂载 | [StemMusicPanel.vue](../../frontEnd/src/components/StemMusicPanel.vue)、[MusicPanel.vue](../../frontEnd/src/components/MusicPanel.vue)、[HeroSection.vue](../../frontEnd/src/components/HeroSection.vue) | 不在当前 `App.vue` 的渲染树；原有测试/资源可能继续引用，暂不删除 |
| 四轨浏览器实现 | [stemEngine.js](../../frontEnd/src/audio/stemEngine.js)、[stemMix.js](../../frontEnd/src/audio/stemMix.js) | 为未挂载的旧四轨面板保留；后端路由另行注册 |
| 独立服务 | [remote_audio_separator.py](../../backEnd/remote_audio_separator.py)、[songeval_server.py](../../backEnd/songeval_server.py)、[songeval_client.py](../../backEnd/songeval_client.py) | Demucs/SONGEVAL 各有独立服务或可选报告评价；client 被报告接口按需调用，非采集前置 |
| 旧本机音乐 | [adaptive_music.py](../../backEnd/src/anphy_sleep/adaptive_music.py)、[music_policy.py](../../backEnd/src/anphy_sleep/music_policy.py)、[music_runtime.py](../../backEnd/src/anphy_sleep/music_runtime.py)、[audio.py](../../backEnd/src/anphy_sleep/audio.py)、[suno.py](../../backEnd/src/anphy_sleep/suno.py) | 不是当前浏览器 ACE 播放链；包初始化和旧 CLI 可能导入，不可直接批量删除 |
| 旧离线分析 | [pipeline.py](../../backEnd/src/anphy_sleep/pipeline.py)、[preprocess.py](../../backEnd/src/anphy_sleep/preprocess.py)、[statistics.py](../../backEnd/src/anphy_sleep/statistics.py)、[modeling.py](../../backEnd/src/anphy_sleep/modeling.py)、[staging.py](../../backEnd/src/anphy_sleep/staging.py)、[transition_prediction.py](../../backEnd/src/anphy_sleep/transition_prediction.py)、[replay.py](../../backEnd/src/anphy_sleep/replay.py)、[pilot.py](../../backEnd/src/anphy_sleep/pilot.py)、[paper.py](../../backEnd/src/anphy_sleep/paper.py)、[cli.py](../../backEnd/src/anphy_sleep/cli.py) | 不在当前 A/B/C 在线数据分析路由；用于旧研究/CLI 复验，不等于废弃 |
| 旧采集/模型工具 | [eeg.py](../../backEnd/eeg.py)、[train_sleep_classifier.py](../../backEnd/train_sleep_classifier.py)、[train_all_datasets_simple.py](../../backEnd/train_all_datasets_simple.py)、[fix_model_format.py](../../backEnd/fix_model_format.py)、[download_sleep_edf.py](../../backEnd/download_sleep_edf.py)、[device_bridge.py](../../backEnd/src/anphy_sleep/device_bridge.py) | 不用于当前网页 BrainFlow/CNN 路径；旧独立入口，需保留历史重现实验时使用 |
| 离线资源工具 | [scripts/](../../backEnd/scripts/)、[assets.py](../../backEnd/src/anphy_sleep/music_engine/assets.py)、[aisaago.py](../../script/aisaago.py) | 数据下载/素材准备或独立实验，不会在当前采集开始时自动运行 |

模型训练/回放脚本中的 [check_waveform_replay.py](../../script/check_waveform_replay.py)、[check_subset_replay.py](../../script/check_subset_replay.py) 与 [validate_subset_edf_reader.py](../../script/validate_subset_edf_reader.py) 是**必要的验证工具**而非每次采集的进程。`check_subset_replay.py` 当前以 `CAP16.index(name)` 将额区 Fp2 填入名义 Fp2；LIVE 的 `WaveformClassifier` 对额区却读取名义 C3。用它作为额区离线/在线一致性证据前需核对或修正该映射并重跑，不能仅凭脚本名称/历史文档宣称已通过。

## 6. 配置、测试与阅读入口

| 类型 | 当前入口 |
| --- | --- |
| 后端依赖/启动 | [pyproject.toml](../../backEnd/pyproject.toml)、[uv.lock](../../backEnd/uv.lock)、[start_backend.command](../../backEnd/start_backend.command)、[start_waveform_backend.ps1](../../backEnd/start_waveform_backend.ps1)、[start_all.command](../../start_all.command) |
| 前端开发/浏览器测试 | [package.json](../../frontEnd/package.json)、[vite.config.js](../../frontEnd/vite.config.js)、[playwright.config.js](../../frontEnd/playwright.config.js)；测试默认单独使用 5178，用户页面常用 5173 |
| 后端关键隔离测试 | [test_experiment_execution.py](../../backEnd/tests/test_experiment_execution.py)、[test_raw_recording.py](../../backEnd/tests/test_raw_recording.py)、[test_session_reports.py](../../backEnd/tests/test_session_reports.py)、[test_experiment_analysis.py](../../backEnd/tests/test_experiment_analysis.py)、[test_subset_waveform.py](../../backEnd/tests/test_subset_waveform.py)、[test_waveform_ace_safety.py](../../backEnd/tests/test_waveform_ace_safety.py) |
| 前端/浏览器关键回归 | [LiveWaveform.test.mjs](../../frontEnd/src/components/LiveWaveform.test.mjs)、[experiment-execution.spec.js](../../frontEnd/browser-tests/experiment-execution.spec.js)、[raw-recording.spec.js](../../frontEnd/browser-tests/raw-recording.spec.js)、[eeg-power-shifts.spec.js](../../frontEnd/browser-tests/eeg-power-shifts.spec.js)、[experiment-admin.spec.js](../../frontEnd/browser-tests/experiment-admin.spec.js) |

更详细的存储和统计字段见 [06](06-session-reports-and-experiments.md)。测试代码验证逻辑与接口，不能替代 45 分钟真人采集、浏览器真实声音和设备延迟测量；具体迁移/验收顺序见 [08](08-legacy-code-and-migration.md)。
