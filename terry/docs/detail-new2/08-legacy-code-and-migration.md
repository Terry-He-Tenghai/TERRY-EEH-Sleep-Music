# 08 新旧文档差异、保留策略与实验验收

更新：2026-10-11。返回 [目录](README.md)。对照 [旧版目录](../docs-new/detail/README.md) 和 [旧版代码文件指南](../docs-new/detail/07-code-file-guide.md)，本章记录应如何阅读旧资料、整理代码及验收当前实验；不是代码迁移或实验已完成的报告。

## 1. 旧说法与当前实现

| 旧资料容易造成的理解 | 当前源码口径 | 对实验的影响 |
| --- | --- | --- |
| 旧架构/模型说明把 11 特征、未来五分钟 N2 风险、个人基线放在主链 | LIVE 使用 40 秒缓冲的 W/N1/N2 波形 CNN；旧特征/未来风险路径仍服务 DEMO model/离线研究 | 不把旧风险概率当作 C 条件实测终点；对外标清模型版本和来源 |
| 旧报告说明“两次 N2 自动停止” | 当前三个有效 LIVE N2 触发**音乐** 30 秒渐出/暂停，采集继续到截止/停止 | 不再以 N2 触发作为结束时长或睡眠诊断依据 |
| 旧代码指南的 EEG 功率仅有泛泛描述 | `waveform_classifier.py` 已输出 `alpha_8_12`、`theta` 及相对功率，后台有 EegPowerShifts | 提前标注有效基线/干预；不能把重叠窗口算独立样本 |
| 老的报告多用于按会话浏览 | 当前受试者×A/B/C×多次 trial，B 另存测量/脚本窗口；新执行条件不可事后改 | 要分别审核实际条件、设备来源、原始文件及播放证据 |
| 过去的本机音乐/Suno/四轨页面可被误认为当前默认闭环 | 页面闭环为 ACE 或上传背景+MIDI；四轨后端仍注册、部分旧页面未挂载 | 不删除服务导入依赖，也不把调试入口计入正式条件 |
| “有效模型输入”等同于帽位标签名称 | 额区 2/4/6 的实际 Fp2 从名义设备 C3 读入；8/16 契约另行定义 | 固定接线、模型选项和原始列映射；复核旧 EDF 回放 |
| 看到分类耗时/浏览器 PCM 就视为低延迟或安全声压 | 两者都不是电极到耳朵端到端测量 | 另做时钟同步/硬件回采/耳边声压测试，不从当前字段推断 |

旧 [01](../docs-new/detail/01-system-architecture.md) 到 [05](../docs-new/detail/05-api-deployment-limitations.md) 的概念性内容可用来讲解研究背景，不应当作此版本 LIVE/A/B/C 的执行规范；旧 [06](../docs-new/detail/06-session-reports-and-experiments.md) 的两次 N2 自动停机说法已失效。新文档 [01](01-system-architecture.md) 至 [06](06-session-reports-and-experiments.md) 分别给出当前系统、EEG、模型、音频、部署和分析口径。[07](07-code-file-guide.md) 是按实际入口重新分类的代码清单。

## 2. 保留与整理规则

1. **运行/报告必需：**保留当前后端/前端主入口、原始记录、报告、CNN 权重、配置、频段功率分析、音乐播放器和证据采集。`script/train_sleep_waveform_models.py`、`train_sleep_frontal_models.py`、`train_sleep_subset_models.py` 是动态载入的运行依赖，不能把整个 `script/` 当历史目录清理。
2. **条件或模式相关：**DEMO model 的旧流式特征、`classification_gate.py`、`channel_repair.py`，以及 B 的 `demo_showcase.py` 在各自路径仍被调用；外部服务 SongEval/Demucs、手动 MIDI/ACE 调试和已注册四轨 API 不是 C 实验的必经步骤，但有功能/导入依赖。
3. **主入口未用但需要追溯：**未挂载的旧四轨/本地素材页面，旧 CLI 分期/未来预测、Suno、本机播放器和离线素材/训练输出，先列为“历史保留”；不能以搜索不到网页组件为删文件证据。`anphy_sleep/__init__.py`、音乐包 `__init__.py` 的导出还可能触发间接导入。
4. **将来若要移除：**先固定历史分支/资料，建立新旧入口依赖图；证明 LIVE/DEMO/B/ACE/上传/报告启动均可导入和运行，检查独立命令行与对应测试，再决定是否分拆包和删除。此次仅编写文档，没有删除/迁移代码。

## 3. 已知需要单独验证的点

- **额区回放：**[check_subset_replay.py](../../script/check_subset_replay.py) 构建 16 路输入时按 `CAP16.index(name)` 填入额区通道 Fp2，当前 LIVE [waveform_classifier.py](../../backEnd/waveform_classifier.py) 则从名义 C3 取 Fp2。应使用与设备映射相同的输入布局进行重放；目前不能把该脚本结果写为已验证额区硬件一致性。
- **45 分钟浏览器录音：**[sessionEvidence.js](../../frontEnd/src/audio/sessionEvidence.js) 的总 PCM 上限是 360 MiB；双声道 Float32 每秒约 `采样率×8` 字节。按 48 kHz 计算，约 983 秒（16.4 分钟）到上限；44.1 kHz 约 1069 秒（17.8 分钟）。当前实现**不保证 45 分钟完整最终混音 WAV**，会标记 `partial_memory_limit`，也可能从实际开始播放后才录制。原始 EEG 有独立持久化路径，不能以浏览器音频缺段推断 EEG 缺段。正式全段数字音频分析需另行设计分段/流式保存并重新验收。
- **实验基线：**后台阶段区间可手动标注，但系统不会自动提供“未播放音乐的前测基线”。播放若从实验零点开始，前几分钟 EEG 不是无音乐基线。若要比较干预前后，应在协议里明确基线开始/结束与实际播放起点。
- **录制与声音安全：**数字 1 秒 RMS 变化/峰值只检验上传的 PCM，不覆盖 A 的外部播放、音量旋钮、耳机或远端生成等待；显式停止与异常路径也不全是淡出。
- **样本量和证据：**受试者级 Friedman/Wilcoxon + Holm 为已实现探索性统计。效应量/区间、顺序与时期、缺失机制和功效分析未自动完成；无独立随机化/人工审查/硬件测量不可声称助眠效果或工程满分。

## 4. 正式实验前的可执行核对顺序

| 阶段 | 检查与留档内容 | 通过标准 |
| --- | --- | --- |
| 运行准备 | 锁定源码/权重/音频素材版本、许可证、设备/浏览器版本、ACE 端点；匿名 ID 和数据授权 | 五个模型预检中选择实际使用者；所有依赖可加载，实验中不改配置 |
| 设备契约 | 核对 16 路线序、额区 C3→Fp2 真实接线、250 Hz、时间戳/包计数、坏电极反应 | 阻断错误配置；原始与显示/分类来源可追溯 |
| A 固定 | 外部播放器播放预定素材，网页本机静音；仍保存真实 EEG | 报告显示 `fixed`/external、原始文件完整；另记外部设备音量与起停时刻 |
| B 伪闭环 | 真实 EEG 独立测量；脚本控制轨迹单独存储 | `windows` 是测量，`control_windows` 是脚本；不冒充 LIVE 响应 |
| C 真闭环 | 真实脑电→合格分类→音乐事件→浏览器播出 | 检查模型来源、质量、时序、实际音频起播/失败事件；DEMO C 只能做演示 |
| 45 分钟关闭 | 完整时长或原因如实写报告，三次 N2 只改变音乐 | EEG 文件 `complete`、`error`、样本数合格；核对音乐暂停后 EEG 仍在写入 |
| 后台审核 | 按受试者/条件找到每次 trial，标注实际执行、主观问卷、阶段边界 | 合格与排除原因可追溯；缺失保持缺失，固定音乐不比较本机空 PCM |
| 统计及展示 | 锁定主终点、参与者配对、A/B/C 顺序、重复次数和剔除口径 | 以受试者为 n，报告估计值/不确定性和探索性检验；不把窗口数当样本量 |

上述是**待执行验收**，不是本轮完成的测试记录。模型离线性能、采集真实性、声音平滑与人体干预效果要分别留证据。不要在公开材料中放受试者姓名、未脱敏原始 EEG、密钥或外部服务上传凭据。

## 5. 与源码对应的测试入口

- 后端生命周期及原始记录：[test_experiment_execution.py](../../backEnd/tests/test_experiment_execution.py)、[test_web_acquisition.py](../../backEnd/tests/test_web_acquisition.py)、[test_raw_recording.py](../../backEnd/tests/test_raw_recording.py)、[test_session_reports.py](../../backEnd/tests/test_session_reports.py)。重点核对 A 外部/B 测量与脚本分离/C 真实来源、多 trial、停止和数据完整性。
- LIVE 与音乐门控：[test_waveform_classifier.py](../../backEnd/tests/test_waveform_classifier.py)、[test_subset_waveform.py](../../backEnd/tests/test_subset_waveform.py)、[test_live_backlog.py](../../backEnd/tests/test_live_backlog.py)、[test_waveform_ace_safety.py](../../backEnd/tests/test_waveform_ace_safety.py)、[test_ace_step.py](../../backEnd/tests/test_ace_step.py)。区分模型确认和三次 N2 音频淡出。
- 实验统计/额区契约：[test_experiment_analysis.py](../../backEnd/tests/test_experiment_analysis.py)、[test_sleep_frontal_contract.py](../../script/test_sleep_frontal_contract.py)、[check_subset_replay.py](../../script/check_subset_replay.py)。回放脚本当前映射问题须先处理，不能声称已经通过 EDF parity。
- 前端/浏览器：[LiveWaveform.test.mjs](../../frontEnd/src/components/LiveWaveform.test.mjs)、[AdaptiveMusicPanel.test.mjs](../../frontEnd/src/components/AdaptiveMusicPanel.test.mjs)、[experiment-execution.spec.js](../../frontEnd/browser-tests/experiment-execution.spec.js)、[raw-recording.spec.js](../../frontEnd/browser-tests/raw-recording.spec.js)、[eeg-power-shifts.spec.js](../../frontEnd/browser-tests/eeg-power-shifts.spec.js)、[experiment-admin.spec.js](../../frontEnd/browser-tests/experiment-admin.spec.js)、[session-report.spec.js](../../frontEnd/browser-tests/session-report.spec.js)。历史 Stem 用例可能依赖当前未挂载 UI，需单独解释失败或跳过。

本次更新只核对源码与文档链接；上述测试、真实采集、完整 45 分钟录音、远端生成和人体实验均未在本次文档工作中执行。
