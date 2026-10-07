# 04｜音乐方案、连续控制和实际播放

更新：2026-10-07。返回[主文档](../系统架构与功能.md)。

## 1. 分类和音乐方案分开

W/N1/N2是波形模型类别；M1/M2/M3是调度器输出音乐方案。`MusicScheduler`将最近约30秒分类分数平滑，N2≥0.65选择M3，N1≥0.55选择M2，其余M1；历史未来N2风险/基线theta分支仅在实际提供这些字段时参与，LIVE CNN不提供该未来风险。

LIVE建立scheduler时使用确认次数1、最短驻留60秒、质量门槛1、60BPM/16拍状态边界。所谓16拍是代码的控制时钟，不等于识别到原音频的真实节拍。当前分类确认本身也为1（配置项），音乐平滑和驻留仍可能使音乐方案暂时不同于瞬时最高类别。

## 2. 连续控制量

`EegMusicModulator.apply()`：初始概率驱动 `P(W)+0.45×P(N1)`；若提供有效beta_z和theta_z，再以0.8/0.2合成，LIVE CNN通常只用概率项。以时间常数20秒的指数平滑，再做有界非线性对比变换得到0–1控制量L。L是设计的音乐变量，不是经校准的生理唤醒指数。

同一控制变量可以生成音符计划，也可通过 `project_stem_mix()`映射四轨增益；三条音频路径实际执行能力不同，不能将符号计划的和声规则宣称为ACE整曲或四轨音频内部的算法。

## 3. 同源四分轨实际改什么（当前页面未挂载）

当前App选择仅为ace/upload；本节是已保留的组件/引擎与后端API，不是用户在新页面已经能直接选择的功能。

`babyslakh.py`选20首候选中的固定四个非鼓声部，角色piano/strings/bass/pad为混音标记。基础控制：piano=0.18+0.52L，strings=0.32−0.20L，bass=0.04+0.28L，pad=0.28−0.20L；brightness=0.15+0.65L。`stemMix.js`按前端strength进一步增加有界对比，低通范围约550–7200Hz。

`StemEngine`同一时钟起播，长短/单声道校验，3秒增益/低通过渡；原播放位置不因EEG变化重启，循环采用约1秒交叠。它**不读MIDI，不修改音高/节奏，不自动在原曲乐句边界执行每次调参**。后端离散音乐状态有边界限制，连续四轨增益可每个有效更新直接渐变，这两个层次不能混为一谈。

固定分轨对照为相同四轨0.3增益/7200Hz低通，未等响度匹配，也不包含原曲其他声部。需要盲听/响度控制后才能比较艺术性。

## 4. ACE-Step生成与最新提示词

最终prompt为 `Instrumental {STYLES风格}; no vocals, no abrupt transients, even volume. {状态描述}`；lyrics为 `[Instrumental]`、thinking=false、WAV、batch_size=1。

M1状态描述：`Awake relaxation: clear, warm piano melody in the foreground, gently pulsing soft pads, steady slow tempo and recognizable phrases.`

M2状态描述：`Falling asleep: sparse felt-piano notes with long pauses, sustained strings underneath, slower free-flowing pulse and fewer melodic changes.`

M3状态描述：`Light sleep: nearly beatless sustained ambient drones and airy soft pads; no lead piano, no distinct melody, no percussion, minimal changes and very quiet dynamics.`

风格ambient/piano/nature/strings/electronic再组合；未直接传原始EEG。普通自动文本生成120秒，显式预设演示无参考文件30秒；最小提交间隔15秒，每会话按M状态缓存。网络/远端模型耗时没有保证，生成成功前不能声称实际播放。

`AutomaticAcePanel`3秒轮询，下载/解码后循环，约1.5秒交叉淡化；已有音乐的实际状态与wanted状态分别显示。任务完成时再次检查会话/权限，过期时可以保持已开始音乐但不能凭过期事件启动新音频。生成器持有的paused是授权状态，不一定等于已经在浏览器停止。

### 参考音频cover与声部extract

上传参考WAV后：`cover_audio()`取完整10–600秒 → `separate_accompaniment()`发送Demucs → 非vocals之和 → ACE cover。输出任务长度按原始源长度，cover_strength=0.55、noise_strength=0.35；分离失败不以原人声作兜底。生成式模型与分离均可能有伪迹，不能保证“保留同一旋律的精确重新编排”。

`/api/ace/extractions`直接给原始参考请求ACE v15 base、extract、指定track（keyboard/vocals/bass等）、32步；它是独立试听下载工具，不是所有声部自动分离及加入EEG四轨，也不是从声乐轨相减的精准伴奏。

## 5. 本地背景与MIDI实验

`adaptiveEngine.js`播放上传/本地背景并按后端音符合成额外旋律/低音/纹理。固定C大调/A自然小调音阶、C/Am/F/G和弦、音域/跳进限制与种子支持计划可重复；新动机按代码时间变化，不能全部归因EEG。

代码不自动转录上传WAV或识别背景调/拍点。符号pad有计划但浏览器省略其合成，M3保留背景/安静纹理而关闭旋律低音。该引擎60BPM/16拍调度底轨和计划，底轨约8秒淡变，背景起点循环不等于原曲拍点同步。

手动 `MusicWorkbench/ManualEngine`编辑动机、时值、八度、音色，导出MIDI/日志和可选录音；手动请求M状态，不连接自动EEG状态。其背景结束时停止、不按自动背景逻辑无限循环。

## 6. 信号无效时如何持续

LIVE暂时waiting/frozen、质量异常或事件过期：保持已经开始的音乐，冻结新控制；尚未起播的音频不得因此启动，过期解码/下载仍拒绝。用户停止、停止采集、会话变化和错误可停止；Adaptive/Stem/手动引擎还在页面隐藏或音频上下文中断时停止，AutomaticAcePanel没有同等的页面隐藏/播放器所有权监听。不要统一宣称所有播放器都严格互斥或切后台立即停止。

**新N2规则优先于持续音乐策略**：Reports观察连续两个有效LIVE N2窗口后结束采集，App状态通知停止播放器；ACE另有sleep_paused显式暂停。用户实际感到“音乐停止”可能是此终点，不是质量保持失效。不能只看旧“15秒后暂停”或旧“所有坏信号继续”提示。

## 7. 连续、解释和复现的证据范围

四轨可记录L、增益、cutoff与applied sequence；本地MIDI记录音符/调度；ACE记录任务获取/播放时间。`sessionEvidence`追加统一浏览器证据/数字录音，后端report关联EEG窗口。不等于同歌曲音符重新创作、远端生成确定性、扬声器绝对同步或听感/助眠验证。正式对照仍需冻结素材、时间轴/版本/响度、回放与伪闭环协议和盲听。