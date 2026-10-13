# 02 EEG 采集、保存与频段功率

更新：2026-10-11。返回 [目录](README.md)。

## 1. 设备与通道

[app.py](../../backEnd/app.py) 的 `_run_brainflow` 使用 BrainFlow `CYTON_DAISY_WIFI_BOARD`，配置地址、端口、增益和采样率。接口允许 250/500/1000 Hz，但当前 LIVE CNN 契约只接受 250 Hz。因此“设备能采集该采样率”与“模型能分类该采样率”必须分开。

[channel_mapping.py](../../backEnd/channel_mapping.py) 定义采集顺序：

```text
Fp1, Fp2, C3, C4, P7, P8, O1, O2,
F7, F8, F3, F4, T7, T8, P3, P4
```

当前额区 2/4/6 模型有一项专门接线约定：名义设备通道 `C3`，即第 3 路，作为实际头皮位置 Fp2 的来源。`WaveformClassifier.source_channels` 和前端 [modelChannels.js](../../frontEnd/src/audio/modelChannels.js) 都执行此映射。原始 CSV 列名仍使用采集通道名；不能直接把 CSV 的 `Fp2_uV` 当作当前额区模型的 Fp2 输入。

8/16 模型保持原 CAP 契约，不采用此额区替换。切换模型前应核实接线是否符合对应契约，不能把额区配置下的验证结论自动推广到 8/16 模型。

## 2. 同一采样块的三条去向

`AcquisitionService._publish_chunk` 按以下职责分离处理：

1. [raw_recording.py](../../backEnd/raw_recording.py)：提交未滤波、未补全的原始微伏采样及设备时间戳、包计数。
2. [adaptive_web.py](../../backEnd/adaptive_web.py)：将原始采样提交给独立推理队列，由模型自己的质量检查和训练契约处理。
3. [display_filter.py](../../backEnd/display_filter.py)：只对网页显示滤波；无效显示块可以置零，但原始块仍保留并接受推理质量检查。

因此网页波形“平滑”不说明原始 EEG 合格，网页出现零线也不代表原始记录被删除。`PowerlineNoiseFilter` 虽在 app 中实例化，但这条主入口没有调用它，不能把它写成实际串联滤波步骤。

## 3. 连续性与质量

LIVE 推理检查块形状、采样索引、采样率、设备时间戳及 0 至 255 包计数。丢包、重复包或时间偏移异常会清空模型历史并重收集窗口；积压也会使在途结果失效，不能使用过期结果控制音乐。

质量诊断包括非有限采样、平直信号、滤波后幅度过大和变化过低。2/4/6 模型只要求选中电极质量合格；8/16 保留全部 16 路质量合格的契约。当前 CNN 不使用均值补全坏电极。

采集线程长时间收不到数据与分类线程暂时等待是不同状态。前者可能结束会话；后者可以暂停更新、等待新窗口。需要同时核对采集状态、模型原因和音乐状态。

## 4. 原始文件

命名 A/B/C 实验强制保存。默认目录为 `backEnd/recordings/<日期时间_随机标识>/`：

- `raw_eeg.csv`：`sample_index`、`relative_time_s`、`hardware_timestamp_s`、`package_id`、`received_at_s` 和 16 个微伏列。
- `metadata.json`：采样率、通道、实验配置、报告 ID、写入样本数、`complete` 和 `error`。

`RawRecording` 使用容量 256 的异步写入队列。队列满或写盘失败会标记文件不完整；不能只依据“目录存在”认定实验数据保存成功。`complete=True` 表示写入器正常完成，不等于信号无伪迹或硬件无丢包。

## 5. 频段功率偏移已经实现

[waveform_classifier.py](../../backEnd/waveform_classifier.py) 对质量合格的原始 40 秒缓冲计算 Welch PSD，`nperseg=采样率×4`，按频率区间积分输出 `band_power_uv2`：

| 键 | 范围 | 用途 |
| --- | --- | --- |
| `alpha` | 8 至小于 13 Hz | 保留历史 Alpha 口径 |
| `alpha_8_12` | 8 至小于 12 Hz | 当前实验 Alpha 指标 |
| `theta` | 4 至小于 8 Hz | Theta 指标 |
| `beta` | 13 至小于 30 Hz | 辅助频段 |
| `total_1_30` | 1 至小于 30 Hz | 相对功率分母 |

相对 Alpha 使用 `alpha_8_12 / total_1_30`，相对 Theta 使用 `theta / total_1_30`。这些 PSD 来自原始质量合格缓冲，不是 CNN 参考、归一化后的输入，也不是显示滤波后的波形。

[experiment_analysis.py](../../backEnd/experiment_analysis.py) 先对每窗口的有效通道取均值，再对阶段窗口取均值。阶段窗口需要末端时间落在阶段内，且 `窗口末端−40秒 >= 阶段起点`，排除跨阶段窗口。变化定义为干预均值减基线均值。

后台 [EegPowerShifts.vue](../../frontEnd/src/components/EegPowerShifts.vue) 显示整段均值、基线、干预及变化。缺阶段标注、旧报告没有功率字段或无合格窗口时显示缺失，不补零。相对功率变化以百分点显示。

## 6. 解释限制

当前有阶段均值变化，没有自动实现“Alpha 到 Theta 过渡更快/更平稳”的预注册时间序列终点。该论点需要另行定义轨迹斜率、变化时间或波动量，再按参与者分析。每 6 秒更新的 40 秒窗口高度重叠，不能把每个窗口当独立受试者。

不同模型的电极范围不同，频段均值不宜未经控制直接混合；正式实验应固定接线、参考、采样率和分类模型。Alpha/Theta 变化是生理代理，不是临床入睡证明。
