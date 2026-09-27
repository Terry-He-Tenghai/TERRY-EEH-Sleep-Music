# BabySlakh 脑电控制原曲分轨

## 当前实现（2026-09-19）

新增独立音乐来源“BabySlakh 原曲分轨 · 脑电混音”，现在开放本地Track00001–Track00020共20首，每首从原始非鼓声部中登记四个同步节点。此次控制的是原曲WAV声部的比例与亮度，不读取/修改MIDI，不附加振荡器旋律，不做变速或节拍识别。Suno兼容代码和高级手动试听暂保留，首页默认使用BabySlakh。

- 每首曲目固定四个混音角色：piano、strings、bass、pad；具体S编号见后端 `CURATED` 清单。
- 只列出四个登记WAV均存在、格式可读、采样率一致且时长对齐的曲目；鼓轨不加入。

鼓轨不加入，避免把整曲混音和原曲声部重复播放。上述组合是技术验证候选，不等于已确认助眠音乐。原始下载文件只读，未裁剪、覆盖或改名。

默认目录：`assest/babyslakh_16k.tar/babyslakh_16k`。可在后端进程环境设置 `TERRY_BABYSLAKH_ROOT` 指向其他位置。路径拒绝符号链接及Windows reparse points；请使用实际普通目录。数据目录已加入.gitignore，防止大体积素材误提交。

## 使用

1. 重启后端：在backEnd激活terry-backend环境，执行 `python -m uvicorn app:app --host 127.0.0.1 --port 8000`。
2. 前端执行 `npm run dev` 或刷新已运行的Vite页面。
3. 音频来源默认是“BabySlakh 原曲分轨 · 脑电混音”，可在20首Track00001–Track00020中选择。
4. 采样率250Hz，选择演示或真实BrainFlow。点击开始采集时授权音频，随后加载四轨。
5. 至少存在有效电极且后端允许保守音乐时，先播放低增益固定混音。常规脑电自适应仍需模型、约300秒清洁基线以及有效分类；真实通道映射确认要求不变。
6. 界面显示DEMO/LIVE、固定保守/脑电自适应、后端原因、分类概率、控制量和每轨当前节点增益/已应用目标。节点参数不是声压或实测RMS。
7. 数据有效时持续播放，整曲结束采用1秒交叉淡化循环（非乐句匹配）。停止采集/手动停止/页面隐藏/其他播放器接管/WebSocket断开会停止声音。15秒没有新的有效计划时2秒渐出；重复序号不能刷新有效期。

## 控制策略与边界

复用现有EegMusicModulator经过20秒平滑和有界对比映射后的control_level L，不增加新的睡眠估计，不根据时间编造脑电变化。每个有效更新直接应用3秒参数渐变，而不是等待固定16秒乐句；原曲播放位置不变。

- piano = 0.18 + 0.52 L
- strings = 0.32 - 0.20 L
- bass = 0.04 + 0.28 L
- pad = 0.28 - 0.20 L
- brightness = 0.15 + 0.65 L；低通截止 = 800 + 6200 × brightness Hz

固定保守模式：piano 0.12、strings 0.08、bass 0.02、pad 0.10、brightness 0.15，control_level=null，不冒充分类结果。

输出默认0.18，可手动0–0.30，压缩器阈值−12dB、比率6、knee12dB。低质量或无效分类不会生成新的自适应控制；所有声部不可用则停止。稳定脑电下可能变化很小，这不是需要人为加随机波动的错误。策略是工程假设，未证明助眠疗效；输出限制不等于声压安全保证。

## API与文件

- GET `/api/stem-music`：曲目与固定声部、时长/采样率/声道；只列完整且时长对齐的曲目。
- GET `/api/stem-music/{track_id}/stems/{stem_id}/audio`：固定ID、只读WAV接口；不接受用户路径。
- POST `/api/acquisition/start` 增加 `stem_track_id`，只接受Track00001–Track00020，与uploaded_track_id互斥。
- adaptive_music增加stem_mix：track_id、mode、control_level、gains、brightness、transition_seconds。非ready时为null。
- `backEnd/babyslakh.py`：文件访问和策略投影；`frontEnd/src/audio/stemEngine.js`：有界下载/同AudioContext时钟播放；`StemMusicPanel.vue`：界面和日志。

## 验证

- 后端分轨与现有音乐回归：174通过、1项因Windows无真实符号链接权限跳过；其他symlink/reparse分支使用模拟lstat回归。
- 前端包含模拟时钟10分钟续播、过期事件、停止/恢复、保守与自适应验证。
- Chromium测试实际读取本机Track00008 WAV，使用明确标记的模拟状态：验证四轨同步、改变比例不重启、原始30–38秒片段离线渲染输出存在差异、该测试片段峰值未超过1。
- 页面集成测试验证选择分轨、启动请求绑定曲目、保守转自适应、停止操作。没有启动真实脑电帽，也没有以测试状态冒充真人结果。

可选浏览器集成命令（需要单独在8011启动本地后端）：

```powershell
# 后端测试服务，独立终端
conda activate terry-backend
cd E:\project\test\terry\terry\backEnd
python -m uvicorn app:app --host 127.0.0.1 --port 8011

# 前端终端
cd E:\project\test\terry\terry\frontEnd
$env:TERRY_STEM_INTEGRATION='1'
npx playwright test browser-tests/stem-audio.spec.js browser-tests/stem-ui.spec.js
```

后续需实际脑电帽试听、输出响度/舒适度对照和素材授权确认。若需要音符删减、音长变化或乐器替换，须另实现MIDI读取和音源重合成，不应将此次分轨混音称为已完成MIDI重编排。
