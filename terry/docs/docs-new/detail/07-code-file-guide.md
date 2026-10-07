# 07｜代码文件职责索引

更新：2026-10-07，依据 `ace3a4e` 的生产代码、脚本与测试目录。返回[主文档](../系统架构与功能.md)。范围：前后端手写源码、关键配置/启动文件、与当前模型衔接的训练入口；不逐个解释依赖包、lock中的每个包、二进制权重内部张量和生成缓存。

以下路径以 `terry/` 为根；标为“保留”或“离线”不等于当前网页已挂载。直接阅读入口：[后端app.py](../../../backEnd/app.py)、[前端App.vue](../../../frontEnd/src/App.vue)。

## 1. 后端根目录：网页运行主链

- `backEnd/app.py`：装配FastAPI路由、采集线程、消息分发、自动ACE及报告/N2结束逻辑。
- `backEnd/adaptive_web.py`：有界异步分类队列、LIVE/DEMO分发、连续性质量检查、音乐计划和积压恢复。
- `backEnd/waveform_classifier.py`：版本化波形训练契约、CPU权重加载、40秒缓冲、质量诊断、CNN分数与辅助功率/耗时。
- `backEnd/channel_mapping.py`：实际帽位顺序及旧模型的实验映射定义；当前LIVE不用插值兜底。
- `backEnd/display_filter.py`：浏览器波形展示滤波及非有限显示处理，非模型输入清理。
- `backEnd/powerline_filter.py`：独立工频滤波工具；当前显示入口不因实例化而自动调用。
- `backEnd/eeg_music_modulation.py`：概率/可选基线特征到平滑控制量、层参数和音符密度/纹理计划。
- `backEnd/ace_step.py`：远端ACE代理、自动任务/缓存、新鲜度与N2暂停、cover/extract和音频流。
- `backEnd/remote_audio_separator.py`：独立远端Demucs CPU服务，输出非vocals伴奏及哈希缓存，未挂主app。
- `backEnd/music_choices.py`：本地音频选择、WAV上传和统一44100Hz PCM16归一化。
- `backEnd/music_library.py`：本地素材清单、路径防护、可用性与Range音频读取。
- `backEnd/music_workbench.py`：手动音乐计划与标准MIDI下载API，不提供设备分类。
- `backEnd/babyslakh.py`：20首候选四分轨白名单、原始WAV安全读取与EEG控制量到混音参数投影；当前App未挂Stem组件。
- `backEnd/session_reports.py`：会话JSON、窗口/N2终点、浏览器证据、PCM分析、实验标签/汇总CSV与trace关联。
- `backEnd/demo_showcase.py`：固定阶段演示与对应合成波形，非真实分类。
- `backEnd/classification_gate.py`：旧DEMO分期确认门控，不是当前LIVE配置确认次数。
- `backEnd/channel_repair.py`：旧路径按可用通道质量和均值补全的实验工具；当前CNN不以此替代坏电极。
- `backEnd/degraded_classifier.py`：历史频谱启发式分类诊断；当前LIVE分发不使用。
- `backEnd/pretrained_classifier.py`：历史YASA/预训练适配和研究诊断；不是当前额区CNN入口。
- `backEnd/__init__.py`：根包标记。

## 2. 后端根目录：保留训练与设备工具

- `backEnd/eeg.py`：旧独立EEG采集/日志工具，包含自己的summary CSV，不是网页Reports实现。
- `backEnd/download_sleep_edf.py`：旧Sleep-EDF数据下载入口。
- `backEnd/train_sleep_classifier.py`：历史睡眠分类训练工具，非当前额区模型的训练入口。
- `backEnd/train_all_datasets_simple.py`：历史多数据集训练辅助入口，不等于当前模型实际训练协议。
- `backEnd/fix_model_format.py`：旧模型格式兼容处理工具；不应用其改名绕过当前严格checkpoint契约。

## 3. `src/anphy_sleep` 公共数据/离线框架

- `config.py`：YAML/本地环境读取、相对路径解析与输出目录创建。
- `contracts.py`：EEG块、StateUpdate、MusicCommand、RealtimeOutput等数据契约。
- `io.py`：归档/受试者发现、EDF/分期标注、电极规范化和稳定N2事件读取。
- `preprocess.py`：离线脑电片段、参考和伪迹处理。
- `features.py`：频谱、脑区、趋势等特征和纺锤检测，供旧特征学习/统计。
- `streaming.py`：SignalPipeline、在线基线特征与历史RealtimeSession。
- `inference.py`：旧sklearn bundle加载、未来N2风险与当前阶段推理。
- `device_bridge.py`：旧ADC帧→微伏→本机实时监视/音乐运行桥，不等于网页BrainFlow线程。
- `pipeline.py`：离线数据准备、单/多受试者分析和任务编排。
- `statistics.py`：质量摘要、阶段对齐、混合效应/配对统计及频段图。
- `modeling.py`：旧未来N2留一受试者预测、提前量评价和部署模型拟合。
- `staging.py`：30秒W/N1/N2聚合、旧分期训练/留一评价及PSD对照。
- `transition_prediction.py`：从记录起点连续未来N2评估、特征消融和事件指标。
- `replay.py`：历史特征窗口回放，非网页原始EDF回放模式。
- `pilot.py`：试验性单/多人分析结果整理。
- `paper.py`：论文图表/manifest输出，不从网页自动生成临床结论。
- `cli.py`：上述离线分析、预测、回放及旧音乐命令行入口。
- `__init__.py`：公共包接口导出。

### 旧本机音乐运行框架

- `music.py`：音乐控制协议与NoOp实现。
- `adaptive_music.py`：旧状态策略及本地Suno素材目标选择。
- `music_policy.py`：旧五模式音乐策略、确认/驻留及微觉醒控制。
- `music_runtime.py`：旧Suno生成、本机播放器线程与策略连接。
- `audio.py`：Null/pygame/VLC本机输出适配，不是WebAudio。
- `suno.py`：Suno请求、任务/曲目仓库、缓存及独立回调服务。

### `src/anphy_sleep/music_engine`

- `layers.py`：M1/M2/M3和层增益、符号层混合原语。
- `midi.py`：确定性动机/和弦/音域约束、音符计划质量与标准MIDI写出。
- `scheduler.py`：音乐状态平滑、质量/确认/驻留/乐句边界调度。
- `waveform.py`：离线音频处理、增益/混响/淡变、指标及WAV写出。
- `assets.py`：确定性离线素材准备、哈希与人工审核绑定；不代表在线ACE已冻结。
- `__init__.py`：音乐原语入口。

## 4. 后端脚本

- `scripts/inspect_anphy_channels.py`：读取数据头，核对模型所需帽位别名/单位。
- `scripts/inspect_babyslakh.py`：核查BabySlakh素材与分轨元数据。
- `scripts/prepare_music_asset.py`：准备本地播放素材及审核记录。
- `scripts/generate_suno.py`：Suno生成/查询与候选素材工具，不是ACE路径。
- `scripts/import_completed_suno.py`：把完成的Suno音频引入本地库。
- `scripts/download_anphy.py`：ANPHY数据获取辅助。
- `scripts/download_boas_psg.py`：BOAS PSG数据获取辅助。

## 5. 当前模型训练/校验（`script/`）

- `train_sleep_waveform_models.py`：原8/16路的数据筛选、CAP契约、CNN训练和留出指标。
- `train_sleep_subset_models.py`：历史中央少通道契约、选中电极缓存训练与共同测试窗口对照；核心被新额区入口隔离复用。
- `train_sleep_frontal_models.py`：当前额区2/4/6契约、独立权重、checkpoint严格校验与训练入口。
- `check_waveform_replay.py`：原8/16 EDF离线与实时概率一致性。
- `check_subset_replay.py`：当前已切到额区契约的2/4/6一致性，文件名保留subset历史名称。
- `validate_subset_edf_reader.py`：自定义EDF读取与基准读取数值核对。
- `test_train_sleep_waveform_models.py`：原输入/标签/划分/QC契约测试。
- `test_training_e2e.py`：合成数据两模型训练保存测试，不是原始EDF指标。
- `test_sleep_subset_models.py`：历史中央少通道契约不变性测试。
- `test_sleep_frontal_contract.py`：新额区组合/预处理/CPU结构和旧缓存拒绝测试。

其他 `script/` 数据或外部服务实验不默认作为当前网页入口；例如用户打开的 `aisaago.py` 不能仅由文件名推断已接入主系统。

## 6. 前端生产源码（`frontEnd/src`）

### 入口/组件

- `main.js`：加载样式并挂载Vue根组件。
- `App.vue`：当前ACE/upload两个音乐来源，采集请求/WS/绘图/报告绑定、页面切换和结束证据。
- `i18n.js`：响应式zh/en、localStorage和HTML lang；部分组件/错误仍中文，不是全站翻译。
- `components/AutomaticAcePanel.vue`：自动ACE状态/任务结果下载、循环/交叉淡化、当前类别/实际音乐目标与录音证据。
- `components/AdaptiveMusicPanel.vue`：背景＋额外MIDI、分类/控制/质量UI及本地事件日志。
- `components/AceMusicPanel.vue`：手动ACE生成/轮询/试听调试。
- `components/AceStemPanel.vue`：上传参考指定声部提取/轮询/试听下载；不自动插入四轨控制。
- `components/SessionReportPanel.vue`：报告列表/窗口/音频/trace与JSON/失败录音下载。
- `components/ExperimentAdmin.vue`：筛选/人工条件评分、分组均值SD及参与者内差值/CSV。
- `components/WaveformQuality.vue`：模型/质量电极、异常指标、保留缓冲/重置原因。
- `components/MusicWorkbench.vue`：手动音符编排、状态试听、MIDI/日志/独立录音工具。
- `components/StemMusicPanel.vue`：四轨混音与波形频谱/RMS日志组件，当前App未挂载。
- `components/MusicPanel.vue`：本地曲库手动选曲/淡变/播放互斥，当前App未挂载。
- `components/HeroSection.vue`：历史展示页打字/视频/菜单交互，当前App未挂载。

### 音频工具

- `audio/liveClassification.js`：LIVE有效分类与新起播/继续已有音乐权限分开；显式预设演示许可。
- `audio/modelChannels.js`：16路来源/额区模型电极/绘图索引/QC范围与中文诊断。
- `audio/demoOrigin.js`：预设演示来源字段一致性，禁止冒充LIVE预测。
- `audio/adaptiveEngine.js`：背景加载/有界响度补偿、16秒乐句与振荡器符号声部、LIVE保持/停止与证据。
- `audio/manualEngine.js`：手动背景/纹理/符号层、状态边界/渐变、MediaRecorder和日志。
- `audio/stemEngine.js`：四轨同步/音频校验/增益低通与循环保持，代码保留。
- `audio/stemMix.js`：强度/固定对照映射和节点波形、频谱、RMS/peak采样。
- `audio/midiEditing.js`：动机/移调/时值变奏编辑及MIDI序列化。
- `audio/uploadLoudness.js`：背景音频数字RMS/peak与有界补偿，不是LUFS/SPL。
- `audio/sessionEvidence.js`：事件收集、输出节点Worklet连接、PCM/WAV及报告上传/失败恢复。
- `public/finalMixRecorder.js`：AudioWorklet双声道交错Float32 PCM与分批/flush输出，报告录音必要文件。

### 前端构建配置

- `package.json/package-lock.json`：Vue/Vite/Playwright依赖和dev/build/Node/browser测试脚本及锁版本。
- `vite.config.js`：开发5173与/api、/ws到8000代理；非生产代理方案。
- `playwright.config.js`：浏览器测试环境/服务配置，不是实机验证协议。
- `index.html`：SPA挂载入口。
- `src/style.css`：全局布局、配色、表单与响应式样式，不参与分类或音乐规则。

## 7. 后端测试文件的职责

所有测试在 `backEnd/tests/`，多数是隔离/模拟验证，不代表真实服务验收。

- `conftest.py`：共享测试平台能力（Windows符号链接权限判断）。
- `test_web_acquisition.py`：HTTP/WS、采集生命周期、输入/显示/设备指令防护。
- `test_waveform_classifier.py`：原权重与波形契约、连续性/坏输入。
- `test_subset_waveform.py`：当前额区映射/选中QC、坏窗口滚动与拒绝中央旧契约。
- `test_live_availability.py`：LIVE暖机/确认、有效音乐授权与坏电极场景。
- `test_live_backlog.py`：积压丢弃/重收集/在途预测拒绝。
- `test_waveform_ace_safety.py`：分类来源/过期/质量/N2门控的生成安全。
- `test_ace_step.py`：ACE代理、任务/cover/extract/缓存/超时和自动状态。
- `test_music_upload_formats.py`：WAV格式/采样/通道归一化和长度限制。
- `test_session_reports.py`：报告生命周期/N2/PCM/指标/实验标注与trace。
- `test_channel_mapping.py`：帽位名称/旧映射。
- `test_channel_repair.py`：历史过滤质量与补全行为。
- `test_degraded_classifier.py`：保留频谱诊断，不表示LIVE启用。
- `test_pretrained_classifier.py`：历史预训练适配。
- `test_inspect_anphy_channels.py`：数据头/别名核查。
- `test_classification_gate.py`：旧确认规则和有效事件。
- `test_demo_showcase.py`：显式脚本化来源/合成波形/质量连续性防护。
- `test_babyslakh.py`：四轨白名单、文件路径与投影。
- `test_eeg_music_modulation.py`：控制量/密度/符号声部可重复性。
- `test_music_workbench.py`：手动计划和MIDI API。
- `test_music_library.py`：本地清单、Range、路径/符号链接。
- `test_music_assets.py`：素材准备/审核哈希。
- `test_generate_suno.py`：Suno工具接口与素材下载防护。
- `test_music_system.py`：旧本机策略与曲目运行。
- `test_music_engine.py`：音乐状态/层/符号/波形原语。
- `test_device_bridge.py`：旧ADC转换/监视与运行桥。
- `test_hardware_montage.py`：历史硬件配置布局契约。
- `test_streaming.py`：旧因果滤波/窗口/基线实时接口。
- `test_io.py`：数据/标签读取。
- `test_features.py`：频谱/因果特征。
- `test_modeling.py`：旧留一受试者模型输出。
- `test_staging.py`：旧分期训练与生理输出。
- `test_transition_prediction.py`：连续未来N2与消融输出。
- `test_paper.py`：论文结果整理。

## 8. 前端测试及其边界

- `AdaptiveMusicPanel.test.mjs`：背景/MIDI引擎、连续调度、LIVE保持和停止。
- `LiveWaveform.test.mjs`：分类来源/鲜度、ACE异步结果/循环保持与类别展示。
- `ModelChannels.test.mjs`：额区indices、完整buffer、绘图名/色/QC和WS中断。
- `StemMusicPanel.test.mjs`：保留四轨启动、门控、保持/恢复/停止。
- `StemMix.test.mjs`：混音强度、固定对照及输出数字采样。
- `MusicWorkbench.test.mjs`：手动编排/符号编辑/同步/参数及调试组件。
- `MusicPanel.test.mjs`：保留本地手动播放/渐变/停止。
- `DemoMusic.test.mjs`：预设来源标记与门控。
- `HeroSection.test.mjs`：历史展示交互和降动态行为。

### `browser-tests/`逐文件

- `language.spec.js`：中英切换和指定标签/持久化的页面交互验证。
- `session-report.spec.js`：模拟报告与录音上传/下载的UI证据路径。
- `experiment-admin.spec.js`：模拟实验汇总/标签保存、筛选与描述统计显示。
- `workbench.spec.js`：手动MIDI工作台的计划、同步播放和数字音频输出。
- `adaptive-audio.spec.js`：网页自适应背景/音符输出及场景控制。
- `stem-audio.spec.js`：四轨播放数字输出场景；依赖保留Stem界面与素材，默认跳过的配置需核对。
- `stem-ui.spec.js`：历史Stem选择/UI场景，仍引用当前已移除的stems选项。
- `demo-showcase.spec.js`：脚本阶段/音频演示场景，历史Stem入口假设需更新。

language/session-report/experiment-admin主要模拟接口；部分Stem用例默认跳过且仍引用当前已移除的stems选项，开启时需要先与页面架构核对。不能将测试数量直接当设备、远端生成或艺术性验证。

## 9. 后端关键配置与运维文档

- `config.waveform.yaml`：当前LIVE权重目录/确认次数1/最低分数0.55。
- `config.yaml`：公开数据/历史分析与模型配置。
- `config.hardware.yaml`：历史DEMO model帽位/基线配置，不是额区LIVE权重契约。
- `pyproject.toml/uv.lock`：后端包和依赖锁；`requirements-waveform-live.txt`：实时服务依赖清单，不含所有离线验证资源。
- `start_waveform_backend.ps1`：本机训练venv和五模型预检；`start_backend.command`：Unix后端入口。
- `SESSION_REPORTS.md`：报告接口与证据界限；`EXPERIMENT_ANALYSIS.md`：人工实验标注/统计；`AUDIO_SEPARATION.md`：独立Demucs/ACE配置说明。
- `terry/start_all.command`：Unix/macOS前后端启动辅助；不应直接交PowerShell执行。

**审查方式**：本轮只读核查和更新文档，没有运行生成、采集、完整浏览器测试或对所有历史脚本做实测。文件作用以实际调用层次表达，未挂载组件不列作当前页面可用入口。