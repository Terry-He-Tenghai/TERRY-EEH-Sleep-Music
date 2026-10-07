# 01｜系统架构、线程与消息

更新：2026-10-07，依据 `ace3a4e`。返回[主文档](../系统架构与功能.md)。

## 1. 四个运行边界

**浏览器**：Vue界面接收消息，Web Audio执行播放/参数自动化，AudioWorklet采样最终数字混音，上传证据。界面显示“目标音乐状态”不等于音频已播放。

**本地FastAPI**：`app.py` 装配路由、采集服务和浏览器消息；`adaptive_web.py` 做质量/分类/音乐计划；`session_reports.py` 持久化报告与分析PCM。当前服务使用全局单个采集对象、单个报告对象和单个自动生成器，适合单机单活动会话，不是多租户云服务。

**独立可选服务**：ACE-Step生成/改写/声部提取；Demucs伴奏分离。主后端仅代理调用，不将这两个模型嵌入普通分类工作线程。配置地址可指向SSH隧道。

**离线工具**：`src/anphy_sleep` 包含数据分析、旧特征模型、音乐渲染/CLI与设备桥；`terry/script` 包含波形CNN训练和EDF校验。模块存在不代表网页有对应按钮。

## 2. 一次采集的实际生命周期

1. 页面开始按钮在用户手势中授权音频、创建证据会话，发送 `StartRequest`。
2. 后端 `Reports.start()` 创建报告ID；按mode建立完整通道列表，启动分类工作线程和采集线程；ACE来源另启动会话生成状态。
3. 采集到的原始微伏波形先提交分类队列，另外经过显示滤波发给浏览器。
4. 分类按LIVE CNN、DEMO旧模型、DEMO预设分别分发；发送 `adaptive_music` 计划事件。
5. 后端同时观察分类事件、存报告、通知ACE；前端更新分类与质量提示并分发所选播放器。
6. LIVE连续两个有效N2窗口、推理错误、采集异常、手动结束可完成报告并停止采集。浏览器结束证据，上传日志与可选最终混音WAV。

## 3. 队列不等于数据归档

- 分类 `_Session.chunks` 最多32批；每批有原始样本、样本起点、采样率、硬件时间戳/包编号和接收时间。
- LIVE积压恢复丢弃旧批次、重新积累，保护推理新鲜度；不是保证零丢包。
- 浏览器订阅队列最多8条，可丢弃旧显示消息；WebSocket循环另外检查最新adaptive状态，避免波形消息挤掉控制状态。
- 原始EEG并未因此写入报告；报告保存的是窗口摘要/事件。显示曲线仅有页面最近数秒的缓冲。

## 4. 消息与时间字段

- `status`：连接/streaming、采样率、电极列表、样本计数、report_id。某些staleness字段仍有默认值，不能当设备时钟测量。
- `samples`：显示滤波后的 `samples_uv`，`timestamp_s` 来自采集样本索引/采样率。
- `adaptive_music`：session_id、sequence、source、status/reason、EEG窗口末时间timestamp_s、服务器墙钟emitted_at_s、probabilities、模型info、质量范围、音乐状态/控制计划。
- App接收后保留 `eeg_timestamp_s`，同时把供播放器鲜度验证的 `timestamp_s` 改为 `emitted_at_s`；不要混淆EEG时间和网络事件发布时间。
- 浏览器证据另存 `browser_at_s` 与 `audio_time_s`。这些时轴尚无硬件回环校准。

## 5. 通信与一致性

WebSocket `/ws/waveform` 主动送波形和控制；HTTP `/api/adaptive/status` 供定时补取，播放器还取ACE任务状态与实际音频文件。前端按session/sequence拒绝重复旧事件，不因重复包刷新鲜度。采集期间音乐选项锁定；再次start返回已有会话状态，并不是实时切换模型。

可解释性分为两层：音乐映射/执行日志可解释，CNN分类本身不是因此变成可解释模型。trace关联日志也不是“音乐改变引起了脑电改变”的因果证据。

## 6. 当前前端组成

`App.vue`：主控制台、波形绘制、消息/HTTP、ACE或上传音频组件选择、报告/实验入口；`AutomaticAcePanel`：ACE播放器；`AdaptiveMusicPanel`：背景与额外符号音；`StemMusicPanel`和`MusicPanel/HeroSection`源码保留但当前App未挂载；`MusicWorkbench`：手动MIDI；`AceMusicPanel/AceStemPanel`：生成/提取辅助；`SessionReportPanel/ExperimentAdmin`：证据与标注。

具体文件职责见[07](07-code-file-guide.md)，报告生命周期见[06](06-session-reports-and-experiments.md)。