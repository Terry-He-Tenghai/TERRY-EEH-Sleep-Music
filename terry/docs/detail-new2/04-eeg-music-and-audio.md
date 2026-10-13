# 04 EEG 音乐控制、播放与平滑

更新：2026-10-11。返回 [目录](README.md)。

## 1. 当前网页的两条音乐路径

| 来源 | 后端 | 浏览器 | 定位 |
| --- | --- | --- | --- |
| ACE | `ace_step.py`、`ace_music_prompts.py` | `AutomaticAcePanel.vue` | 分类选择 M1/M2/M3，生成或取缓存音频 |
| 上传背景 | `music_choices.py`、`music_library.py`、`eeg_music_modulation.py` | `AdaptiveMusicPanel.vue`、`adaptiveEngine.js` | 上传背景循环，加可调 MIDI/符号声部 |

A 固定条件绕过上述本机播放路径。B 的音乐事件来自独立 showcase，C 来自测量侧有效分类。网页高级工具中的 `AceMusicPanel` 和 `MusicWorkbench` 是调试/手动入口，不应与正式实验混用而不记录偏离。

保留 `babyslakh.py`、`StemMusicPanel.vue`、`stemEngine.js` 四分轨实现，但当前 App 不挂载 `StemMusicPanel`。`AceStemPanel` 是实际挂载的参考音频声部提取工具，不是同一个四轨闭环组件。

## 2. 分类到音乐状态

LIVE CNN 有效分类分数达到配置门槛后，ACE 直接映射 W→M1、N1→M2、N2→M3。ACE 不是按旧 MIDI 调度器的驻留规则切换生成阶段。

上传背景/MIDI 路径使用 `MusicScheduler` 的提交状态和 `EegMusicModulator` 的控制量，输出 notes、gains、waveform、modulation 等计划。调度器在 LIVE 初始化时设确认次数 1、最短驻留 60 秒和质量门槛 1；后端计划和实际浏览器应用时间仍可能不同。

关键代码：[adaptive_web.py](../../backEnd/adaptive_web.py)、[eeg_music_modulation.py](../../backEnd/eeg_music_modulation.py)、[scheduler.py](../../backEnd/src/anphy_sleep/music_engine/scheduler.py)。

## 3. 提示词和生成

[ace_step.py](../../backEnd/ace_step.py) 的 `generate` 为每次生成前置“用于睡前放松、支持睡眠”的音乐意图，并要求柔和起音、安静均匀动态、逐渐过渡和不急促的结尾。这是生成约束，不是经实验验证的助眠效果承诺。

[ace_music_prompts.py](../../backEnd/ace_music_prompts.py) 集中管理阶段编配、风格、流派、调式及和弦进行；共享 [music_harmony.json](../../music_harmony.json) 定义和声选项。`HarmonyControls.vue` 和 `GenreControl.vue` 提供界面选择。

无参考的阶段生成可提交 60 BPM、调性和四拍信息；参考 cover 分支以参考材料为约束，不等同于重新强制固定调性。参考伴奏处理使用独立分离服务；声部 extract 是另一种请求路径。

`AutomaticMusic` 按 session 跟踪目标、任务和阶段缓存，保留最短生成间隔 15 秒。生成、下载、解码和淡变均需要时间，不能把每 6 秒分类更新理解为每 6 秒生成新曲。

## 4. 新鲜度和保持策略

ACE LIVE 许可需要当前 session、研究 CNN 来源、确认标记、质量 1、正常概率向量和 15 秒内事件。重复或倒序 sequence 不增加 N2 计数。无效结果暂停分类驱动更新，不应凭旧分数发起新切换。

[AutomaticAcePanel.vue](../../frontEnd/src/components/AutomaticAcePanel.vue) 可以在许可暂时失效时继续已有曲目，下载完成后仍会再次检查来源和 session，防止过期任务起播。[liveClassification.js](../../frontEnd/src/audio/liveClassification.js) 将“允许新起播”和“允许继续已有音乐”分开。

上传/MIDI 的 [adaptiveEngine.js](../../frontEnd/src/audio/adaptiveEngine.js) 有自己的事件校验、计划新鲜度和 LIVE 保持逻辑。持续质量失效时仍可能渐出停止；不能把两个引擎的全部恢复策略写成完全一致。

## 5. 音量和平滑的具体实现

- ACE 主增益为 0.12；起播与换曲使用 8 秒淡入/交叉淡化。
- ACE 使用 [uploadLoudness.js](../../frontEnd/src/audio/uploadLoudness.js) 扫描实际解码 PCM 的 RMS 和峰值，再用 `min(1, gain)`，只衰减，不放大安静生成曲目。
- 上传背景使用有界 RMS/峰值补偿，工具最大增益为 4；该路径不是 ACE 的“只衰减”策略。
- 上传/MIDI 引擎保留主增益上限 0.22、计划增益渐变和 8 秒曲目交叉淡化。
- 提示词要求无突发峰值，但实际生成结果仍需数字检查和人工盲听。

这些措施不是硬件声压限制，也不是 LUFS 或 true-peak 归一化。耳机灵敏度、系统音量和外部播放设备仍需固定并测量。手动停止、采集停止和某些错误清理路径可以立即停止/关闭音频上下文；当前代码并非所有退出都保证缓慢淡出。

## 6. 三次 N2 淡出

ACE 后端 `AutomaticMusic.consider` 对连续三个有效 LIVE N2 进入 `sleep_paused`；前端 `pauseForSleep` 将正在播放的 source 用 30 秒渐弱到零。EEG 继续记录到实验截止或手动结束。

后续有效非 N2 可解除 ACE 生成暂停；实际声音恢复仍需获得有效状态和音频。上传/MIDI 引擎独立计数，触发 `fadeStop(..., 30)` 后完成渐出并解除播放武装，需要重新显式启动，不能套用 ACE 自动恢复结论。

无效结果会打断连续计数。这里“三次”是连续模型输出，窗口重叠，不是三个独立 30 秒 PSG epoch；DEMO/sham 不触发真实 LIVE 的 N2 暂停证据。

## 7. 音乐性与记录

[sessionEvidence.js](../../frontEnd/src/audio/sessionEvidence.js) 和 [finalMixRecorder.js](../../frontEnd/public/finalMixRecorder.js) 记录输出节点的最终混音，以及下载、解码、起播、淡变等事件。评价对象应是最终输出，不只是生成提示词或后台计划。

保留人工盲听舒适度/音乐性 1 至 7 分、可选音频 AI 评价和 SongEval 原生五维 1 至 5 分。数字平滑、艺术性和主观接受度是不同层面的结果，详情见 [06](06-session-reports-and-experiments.md)。
