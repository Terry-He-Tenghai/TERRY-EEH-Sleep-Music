# 五模式EEG音乐控制与Suno接入

## 边界

五条Pipeline是音乐控制模式，不是新的睡眠分期。W、N1、N2来自已完成LOSO
验证的30秒状态模型；PSD阈值和音乐映射仍属于待实验验证的干预假设。

`sunoapi.org`可能是第三方API服务，不能仅凭域名视为Suno官方接口。正式使用前应
核实服务商身份、授权范围、生成音乐许可、隐私政策、费用和数据保留条款。

## 音乐增强引擎

在旧版五模式策略之外，项目现在提供离线优先的 `music_engine` 基础模块。它不读取原始 EEG，只接收已经生成的 `StateUpdate` 或音乐状态，完成：

- `pad`、`melody`、`bass`、`texture` 四层的独立增益和混音；
- M1（较丰富）、M2（过渡）、M3（极简）三个音乐状态；
- 固定调式、和弦循环、确定性动机变奏和 MIDI 质量指标；
- 亮度低通滤波、混响发送、立体声宽度、淡入淡出、限幅和波形指标；
- 经过确认后在乐句边界应用状态变化；
- 信号无效时冻结当前音乐并标记回退。

离线预览命令（在 `terry/backEnd/` 执行，配置和输出路径均相对于该目录）：

```bash
uv run anphy-sleep --config config.yaml music-render-demo \
  --state M1 --bars 8 --seed 42 \
  --output-dir results/music/renders/M1
```

命令输出每一层 WAV、混合 WAV、标准 MIDI 文件和 `manifest.json`。现有 `FiveModeMusicController` 仍保留为五模式基线，并在动作命令中携带层增益、波形参数、MIDI 变奏、乐句边界和冻结/回退状态。Suno 仍只用于离线候选素材，提示词和审核规范见 `docs/SUNO_AUDIO_PROMPTS.md`。


1. `anti_hyperarousal`：默认清醒期低信息密度音乐。
2. `alpha_stabilization`：W概率较高且alpha相对基线较强、beta较低。
3. `theta_transition`：N1概率持续升高，或未来N2概率与theta共同升高。
4. `micro_arousal_repair`：入睡后出现无明显质量问题的短时beta/W反弹。
5. `sleep_protection`：N2概率持续较高，执行淡出而不是继续生成。

默认每30秒决策，连续两次确认后才切换，并设置最短驻留和微觉醒冷却时间。所有
阈值均在`config.yaml`的`music.policy`中，属于初始工程参数而不是临床阈值。

## 并发结构

```text
EEG/RealtimeSession
        │ 非阻塞 MusicCommand
        ▼
MusicPlaybackWorker ───────► VLC/Null播放器
        │ 缓存缺失
        ▼
SunoGenerationWorker ─────► POST /api/v1/generate
                                      │
                                      ▼
                             HTTPS callback
                                      │
                                      ▼
                              TrackRepository
```

网络生成和音频播放均不在EEG线程执行。生成Worker串行提交任务，天然低于API并发
上限。播放Worker会等待缓存出现，不会暂停脑电采集。

## 安装播放后端

默认`player_backend: "null"`只记录命令，不发声。使用VLC：

```bash
uv pip install --python .venv-uv/bin/python -e ".[music]"
```

系统还必须安装libVLC。WSL中的音频设备和Windows主机并不完全等价，真实播放端
更适合运行在具有稳定音频设备的主机进程。

## API Key

只通过环境变量提供：

```bash
export SUNO_API_KEY="..."
```

不得写入`config.yaml`、日志、嵌入式固件或Git仓库。

## 回调服务器

启动本地接收器：

```bash
export SUNO_CALLBACK_SECRET="使用随机长字符串"

.venv-uv/bin/anphy-sleep --config config.yaml \
  music-callback-server \
  --host 127.0.0.1 \
  --port 8765
```

API需要可从公网访问的HTTPS URL，因此生产环境应通过后端反向代理暴露：

```text
https://your-domain.example/suno/callback/<secret>
```

文档未提供回调签名规范，当前使用不可猜测路径，并只接受已登记的`taskId`。若服务
商支持签名头，应在正式部署前增加签名验证。`TrackRepository.ingest_callback()`
兼容常见`taskId`、`audioUrl`和`streamAudioUrl`字段；首次真实调用后应根据官方
回调样例确认字段。

## 预生成与审核

提交四种生成模式；N2保护模式不调用Suno：

```bash
.venv-uv/bin/anphy-sleep --config config.yaml \
  music-pregenerate \
  --callback-url "https://your-domain.example/suno/callback/<secret>"
```

每次调用返回两首，回调写入`results/music/cache.json`。新曲默认
`approved=false`，不会自动播放。检查响度、峰值、突发瞬态、鼓点和人声并试听后：

```bash
.venv-uv/bin/anphy-sleep --config config.yaml music-cache

.venv-uv/bin/anphy-sleep --config config.yaml \
  music-approve \
  --mode anti_hyperarousal \
  --index 0
```

其余模式同样审核。微觉醒音效最好使用固定本地15秒资源，避免在线生成结果出现
意外刺激；当前代码也支持预生成后审核缓存。

## 无网络策略演示

```bash
.venv-uv/bin/anphy-sleep --config config.yaml \
  music-demo \
  --output results/music/policy_demo.jsonl
```

该命令不读取API Key、不访问网络、不播放声音，只展示从高觉醒W到放松W、N1和
N2保护的防抖命令。

## 接入RealtimeSession

```python
from anphy_sleep import (
    AdaptiveMusicRuntime,
    FiveModeMusicController,
    RealtimeSession,
    SunoClient,
    TrackRepository,
)
from anphy_sleep.audio import VlcAudioPlayer
from anphy_sleep.music_policy import PolicyThresholds
from anphy_sleep.music_runtime import SunoGenerationWorker

repository = TrackRepository(config["music"]["cache_file"])
client = SunoClient(base_url=config["music"]["suno"]["base_url"])
generator = SunoGenerationWorker(
    client,
    repository,
    callback_url=config["music"]["suno"]["callback_url"],
)
runtime = AdaptiveMusicRuntime(
    repository,
    policy=FiveModeMusicController(PolicyThresholds.from_config(config)),
    player=VlcAudioPlayer(),
    generation_worker=generator,
    approved_only=True,
)
runtime.start(pregenerate=True)

session = RealtimeSession(
    config,
    "results/models/future_n2_logistic_continuous.joblib",
    "results/models/sleep_state_logistic_30s.joblib",
    music_controller=runtime,
)

# outputs = session.push(eeg_chunk)

runtime.shutdown()
```

首版推荐在会话前完成生成、审核和缓存，运行时只做选择、交叉淡入、短音效叠加及
N2淡出。未经人工审核的生成结果不应自动播放。
