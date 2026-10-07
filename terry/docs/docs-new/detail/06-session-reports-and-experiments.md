# 06｜会话报告、最终混音录音与实验标注

更新：2026-10-07。返回[主文档](../系统架构与功能.md)。依据 `session_reports.py`、`sessionEvidence.js`、`finalMixRecorder.js`、`SessionReportPanel.vue`和`ExperimentAdmin.vue`。

## 1. 保存位置与生命周期

后端每次真正start创建32位hex UUID，存 `backEnd/session_reports/<id>.json`。metadata含StartRequest配置。采集推理事件经 `Reports.observe()`保存选定字段；手动停止、推理错误、采集异常或N2条件结束后填写ended_at_s、end_reason、received_seconds及eeg_summary。重复finish不会覆写第一次结束。

report_id经采集状态/事件回浏览器；`beginEvidence()`创建本次证据，`bindEvidence()`关联ID，三种自动播放器代码通过 `recordOutput()`支持从自身最终输出节点拉一条录音支路（当前页面只挂ACE/Adaptive，Stem为保留能力）。手动实验台使用独立MediaRecorder；调试ACE、声部提取和报告试听不进入这条会话录音支路。停止或自动结束由页面 `finishEvidence()`上传browser JSON及有数据的WAV；失败时可提供未保存录音下载，并不保证后端已经收到完整证据。

原始EEG大矩阵不存入当前report；保存probabilities、quality、电极/模型info、功率、分类耗时、music_state/增益/控制等窗口事件。它不是完整原始采集重放档案。

## 2. 当前“连续N2”真正含义

观察事件必须有新timestamp_s（相同窗口重复不计）、非stopped/error。LIVE且classification_confirmed真、signal_quality=1、有分数并且argmax=N2，n2_count累加；其他新窗口重置。达到2后 `app.py`设置停止标志、完成 `two_valid_n2` 并启动停止采集流程。

注意：
- 30秒预测窗每6秒重叠，两次N2并非两个独立30秒标签，也不等于已证明持续60秒N2。
- 当前代码不是最短连续睡眠时间判据，也未用人工分期验证此终点。
- eeg_summary.duration_s是启动至结束墙钟，received_seconds是收到样本数量/采样率；启动/网络/模型等待可能包含其中。
- DEMO不以这个LIVE条件自动结束，但仍可手动保存报告。
- ACE自动状态另有N2计数/sleep_paused，它不是report统计的唯一来源，也不等同质量冻结保持音乐。

## 3. 数字音频录音

AudioWorklet将输出声道采样写为立体声float32 PCM，正常扬声器分支不替换。浏览器等audioWorklet初始化后才开始记录，可能包含授权后的静音，不一定从第一个音乐样本精确起录。

内存预算360MiB时设置partial_memory_limit并停止录音支路；事件预算100000时truncated标志；结束flush等最多约300ms，证据记录尾部不确定性0.25秒。后端接受≤400MiB、SoundFile可读的非空单/双声道WAV，异步线程做分析，原子换名保存。此PCM不是麦克风、耳位声压或扬声器硬件回录。

## 4. 后端指标与缺失值

按约1秒块、保留双声道样本峰值：
- RMS dBFS：数字均方根，非LUFS。
- sample_peak_dbfs：样本最大绝对值，非过采样true-peak。
- clipped_samples：abs≥1样本数；仅风险线索。
- centroid_hz：平均声道PSD频谱质心。
- high_frequency_ratio：PSD在≥8kHz的比例；采样率≤16kHz时实验摘要不作可比结果。
- block_boundary_step：相邻1秒块边界样本差，不是完整音乐接缝检测。
- rms_jump_candidates：前块RMS>-60dBFS且上跳>6dB候选，不覆盖所有下降/静音/刺耳问题。

bpm、onset_density、key、chords、true_peak_dbtp、comfort_conclusion为未实现/未测量字段，不补成0。耳位SPL和硬件输出时延未知。分类耗时和浏览器下载/解码日志可以观察；不能从它们推导远端真实排队/模型耗时。

## 5. 从EEG到附近音频的trace

后端按window.sequence匹配browser控制事件，筛选applied/phrase-scheduled/playback-started；音频context时刻减recording_started_audio_s，选邻近音频块。

- 非ACE且sequence匹配时link_scope为same control sequence。
- ACE或无法匹配时明确generation provenance unavailable。
- 原始数据、音频生成随机性、时钟偏移仍缺失，因此trace提供关联证据，不是已证明音乐导致状态变化或完整端到端复现。

## 6. 实验分析功能

人工标注匿名participant、condition（unassigned/fixed/sham/closed_loop）、trial、notes和可选1–7comfort/musicality。界面默认只统计结束的brainflow会话，可包含DEMO作工程检查；后端汇总音频/EEG指标并导出CSV。

分组统计为均值±样本SD、有效指标n；参与者内差值先平均各条件重复试验，再计算closed_loop−fixed/sham。没有p值、置信区间、因果/疗效结论；缺失录音/未测量指标不能按0参与。标签不自动实施fixed或sham，更不会随机分配或盲化播放器。

## 7. 实测前检查

获得声音/生理数据记录授权；统一素材及输出响度；核对真实执行条件后标注；控制参与者内顺序、重复和睡眠环境。记录同一采集会话是否被N2终点提前停止，避免各条件持续时长不同导致错误比较。为原始EEG、报告与音频另制定权限和保留策略；页面看到报告不代表上传/录音完全成功。

当前工作重点从“尚无报告”变成“报告已实现但覆盖边界要清楚”：报告/最终数字录音/描述统计可用代码已经存在，原始EEG归档、网页回放/伪闭环自动实施、可靠音乐结构指标和正式实机实验仍需另行实现验证。