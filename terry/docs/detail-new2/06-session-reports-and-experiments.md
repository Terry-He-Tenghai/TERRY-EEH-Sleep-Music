# 06 会话报告、实验指标与统计

更新：2026-10-11。返回 [目录](README.md)。

## 1. 从开始到分析

`App.vue` 输入受试者编号、A/B/C 和 visit；后端自动为受试者×条件分配 trial。每次启动产生独立 report ID，允许同一受试者同一条件多次保存。

[session_reports.py](../../backEnd/session_reports.py) 的 `Reports` 保存到 `backEnd/session_reports/<id>.json`，关联原始 EEG 路径和最终混音。`windows` 保存测量分类、质量和功率，B 的 `control_windows` 另存脚本控制，`browser` 保存播放事件，`audio` 保存数字音频分析结果。

结束后 [ExperimentAdmin.vue](../../frontEnd/src/components/ExperimentAdmin.vue) 提供受试者搜索、条件筛选、记录多选、查看/标注、CSV 导出。没有多选时分析使用当前筛选记录，有多选时仅使用选中记录。只筛选单一条件通常不能完成三条件配对比较。

新执行记录的 condition 不能事后更改；偏离应写 notes。旧记录允许补标签，但补标签不证明当时真正执行了对应播放条件。

## 2. 数据完整性

- 原始 EEG：检查 `raw_recording.complete`、`error`、样本数量及设备时间戳/包计数。
- 测量窗口：检查 `source`、质量、阶段和功率字段，不能使用 B 的脚本分数作为人体结果。
- 浏览器录音：检查 `recording_status`、秒数、录音起点、内存限制和上传错误。
- A 固定：标记 `external_audio_not_recorded`；不能拿本机空音频与 B/C 比较音乐平滑度。
- 报告：已结束不代表已完成、条件已核验或数据质量合格。后台审核需分别填写。

[sessionEvidence.js](../../frontEnd/src/audio/sessionEvidence.js) 输出双声道 Float32 PCM WAV，记录节点是数字输出支路，不改变正常扬声器连接。事件数量上限 100000，音频缓存上限 360 MiB；尾部 flush 有时间不确定性。

## 3. 主观指标

| 指标 | 当前字段与计算 | 注意事项 |
| --- | --- | --- |
| KSS | `kss_before`、`kss_after`；后−前 | 正值表示更困，不宜命名为提高警觉性 |
| LSEQ GTS | 三个 0 至 100 条目全部有效后取均值 | 需固定题目、端点、语言和使用时机；45 分钟改编用途须注明 |
| 放松 VAS | `relaxation_vas`，0 至 10 | 更高通常表示更放松 |
| 入睡困难 VAS | `sleep_difficulty_vas`，0 至 10 | 补充指标，不等同客观入睡时间 |
| SUS | 十个原始 1 至 5 条目；奇数题减1、偶数题5减原值，和乘2.5 | 系统可用性，不是音乐自然度量表 |
| 过渡自然度 | `transition_naturalness_vas`，0 至 10 | 独立于 SUS |
| 盲听音乐性/舒适度 | `musicality`、`comfort`，1 至 7 | 需记录盲法、评分者和材料 |

问卷缺失保持 null。软件可存储分数并不说明量表在本实验时长与语境中已经验证。A/B/C 的 SUS 评价对象是否相同，也需要实验协议定义。

## 4. EEG 指标

现有 Alpha 8–12 Hz、Theta 4–8 Hz 的阶段绝对功率及相对功率变化，详见 [02](02-eeg-acquisition-signal.md)。基线与干预均用从 EEG 会话开始计的秒数，阶段不允许重叠。

没有阶段边界时，整段均值仍可能显示，但不能计算前后变化。系统当前不会自动插入无音乐基线；若从开始就播放，事后标一个时间区间不能将其变成未干预基线。

当前结果是重叠窗口的阶段均值，不自动提供过渡速度、平稳性、临床入睡时间或临床 N2 潜伏期。

## 5. 工程与数字音乐指标

| 指标 | 已实现口径 | 不代表什么 |
| --- | --- | --- |
| `classification_ms` | 分类函数耗时，含该次辅助计算 | 不含完整采集窗、网络、远端生成或扬声器延迟 |
| 合格窗口比例 | 被评估窗口中质量为1的比例 | 不是按采样时长统计的覆盖率 |
| 回退比例 | 干预内相邻 ready/frozen 控制区间，间隔≤12秒，统计 frozen 时长 | 不含所有缺口；A 外部音乐不测；B 使用脚本控制窗口 |
| RMS 变化 | 上传最终音频相邻1秒块 RMS dBFS 的平均绝对变化 | 尚未验证与 EEG 阶段的时钟对齐 |
| 音频风险筛查 | sample peak、削顶、谱质心、高频比例、块边界跳变、RMS 上跳候选 | 不是舒适度结论、LUFS 或 true peak |
| 后端 CPU | 进程 CPU 时间/会话墙钟时间×100%，单核满负载=100% | 不含浏览器和远端服务 |
| 峰值内存 | 进程启动以来的峰值 RSS，平台不支持则缺失 | 不是会话独占峰值或系统总内存 |

RMS 上跳候选为前一块高于 −60 dBFS 且上升超过 6 dB。谱通量、可靠 BPM、onset density、调性/和弦和过采样 true peak 目前未实现；后端计划中的 BPM 不能当作最终生成音频的实测 BPM。

trace 将播放事件关联到附近窗口和音频块，但 ACE API 尚未完整暴露生成触发窗口；这种关联不能证明准确因果链或声学端到端延迟。

## 6. AI 音乐评价与 SongEval

[music_evaluation.py](../../backEnd/music_evaluation.py) 是可选实际音频评价适配器；未配置命令时明确 unavailable，不用音频启发式伪造艺术性分数。输出 pleasantness、coherence、transition_naturalness，范围1至7，并要求模型版本和方法来源。

[songeval_client.py](../../backEnd/songeval_client.py) / [songeval_server.py](../../backEnd/songeval_server.py) 使用 SongEval 原生1至5分：coherence、musicality、memorability、structure_clarity、vocal_naturalness。要求实际分析音频、时长和覆盖范围；无歌声音频的 vocal_naturalness 需谨慎解释。

手动提交需要明确允许传送最终混音；自动模式需实验启动时选择。不得因为分数范围类似就混合 AI 评分、SongEval 和人工盲听分数。保留原有音乐性指标，但它们不是助眠有效性的替代终点。

## 7. 当前自动统计

[experiment_analysis.py](../../backEnd/experiment_analysis.py) 的 `analyze_cohort`：

1. 默认排除 DEMO；要求受试者、A/B/C 标签、已结束、`trial_status=completed` 和 `condition_verified=True`，排除列出的采集/推理/意外结束错误。
2. 每位受试者每种条件先对合格重复会话取指标均值，以参与者为统计单位。
3. 每个指标取三条件完整参与者；至少3人且存在条件差异时计算 Friedman 总体检验。
4. 对 C−A、C−B 的有效参与者差值，至少3人时计算 Wilcoxon signed-rank；全零差值返回 p=1。
5. 对所有可计算的探索性配对检验共同实施 Holm 校正，不是每个指标单独校正两次比较。

输出各组 n、均值、SD、中位数，以及配对差值描述统计、原始 p 和 `p_holm`。Friedman 总体 p 不包含在上述配对 Holm 家族。后台另有包含未审核记录的描述表，它与正式三条件统计纳入范围不同。

**限制：**当前没有自动实现效应量及其置信区间、样本量功效分析、顺序/时期/残留效应模型、完整混合效应模型或缺失机制分析。配对检验和总体检验也可能使用不同完整样本集合。标签审核并不自动保证原始文件和音频都完整。

若用于正式展示，应预先指定主终点和对比、随机/平衡六种 A/B/C 顺序、记录时期与重复试验规则，并报告有效人数和排除原因。大量窗口不能扩充 n；后台 p 值不能替代预注册和效果大小报告。普通独立样本卡方不适用于这些连续/有序配对指标；配对二分类另需 Cochran Q 或 McNemar 等方法，当前后台未实现。

## 8. 外部生理数据的范围

项目已经保留 `/physiology` 的 CSV/JSON 导入以及 HR、RR/RMSSD、motion 的计算工具，但没有直接连接心率硬件。本轮不把心率列为本项目闭环必需项，也不新增硬件接入。

外部导入需相对于 EEG 开始时间对齐；RMSSD 需要有效连续 NN 间期，未经校正 RR 仅探索性。低活动指标为连续300秒低于阈值区间的起点潜伏期，不是检测确认时刻，也不是临床入睡时间。未观察到完整低活动段且覆盖不足时不能认定“没有发生”。
