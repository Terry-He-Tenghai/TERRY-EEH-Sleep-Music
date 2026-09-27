# 第一阶段：脑电采集与波形展示

## 目标

第一阶段只实现：

```text
LK-Mini-EEG16
→ BrainFlow
→ Python FastAPI
→ WebSocket
→ Vue 3 Canvas
→ 16 通道实时波形
```

睡眠状态推理和自动音乐控制暂不接入页面主链路。2026-09-12 已增加经人工审核的本地音乐库和手动播放面板，详见 `offline_music_library.md`；该功能不通过网络实时调用 Suno。

## 目录

```text
backEnd/
├── __init__.py
├── app.py                 # FastAPI、BrainFlow/demo 采集线程和 WebSocket
├── src/anphy_sleep/        # Python 分析与音乐库
├── tests/
├── scripts/
├── results/
├── .env.example
├── config.yaml
├── config.hardware.yaml
├── eeg.py
├── pyproject.toml
└── uv.lock
frontEnd/
├── package.json           # Vue 3 + Vite
├── vite.config.js         # 开发代理
├── index.html
└── src/
    ├── App.vue            # 控制面板和 Canvas 波形
    ├── main.js
    └── style.css
```

## 后端安装

在 `terry/backEnd` 目录执行：

```bash
uv sync --extra web --extra hardware
```

如果只想验证前端和波形链路，不连接脑电帽，可以只安装：

```bash
uv sync --extra web
```

真实设备模式需要 BrainFlow，并且设备应处于与 demo 相同的网络环境，默认地址为
`192.168.4.1:12345`。

## 启动后端

在 `terry/backEnd` 目录执行：

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

接口：

```text
GET  /api/health
GET  /api/status
POST /api/acquisition/start
POST /api/acquisition/stop
WS   /ws/waveform
```

启动请求示例：

```bash
curl -X POST http://127.0.0.1:8000/api/acquisition/start \
  -H 'Content-Type: application/json' \
  -d '{"mode":"demo"}'
```

真实脑电帽模式：

```bash
curl -X POST http://127.0.0.1:8000/api/acquisition/start \
  -H 'Content-Type: application/json' \
  -d '{"mode":"brainflow","ip_address":"192.168.4.1","gain":24}'
```

`demo` 模式生成确定性的 16 通道模拟微伏数据，便于在没有设备时验证页面；`brainflow` 模式按照 `LK-Mini-EEG16-Python/main_ui_plot.py` 的连接方式读取设备数据。

## 启动 Vue 前端

需要先安装 Node.js 18 或更高版本。然后在 `terry/frontEnd` 目录执行：

```bash
pnpm install
pnpm dev
```

浏览器打开：

```text
http://localhost:5173
```

Vite 会将 `/api` 和 `/ws` 代理到 `127.0.0.1:8000`。页面可以选择演示信号或 BrainFlow 设备、设置设备 IP 和增益、开始/停止采集、暂停显示、改变显示窗口、清空波形，并逐通道显示/隐藏。

## WebSocket 消息

样本消息格式如下：

```json
{
  "type": "samples",
  "timestamp_s": 0.0,
  "sample_rate_hz": 250,
  "channels": ["C3", "C4", "Cz", "FC3", "FC4", "CP3", "CP4", "FCz", "CPz", "Fz", "P3", "Pz", "P4", "O1", "Oz", "O2"],
  "samples_uv": [[0.1, 0.2], [0.3, 0.4]]
}
```

实际消息的 `samples_uv` 始终包含 16 个数组，每个数组包含当前数据块的样本。通道顺序固定为 `config.hardware.yaml` 的物理帽位顺序。

## 设计约束

1. 后端只负责采集和展示数据，不在第一阶段调用 `RealtimeSession`。
2. BrainFlow 原始数据保持微伏单位，不使用新版 Qt 界面已经滤波的数据；正式模型接入时再由 Terry 的实时管线统一滤波。
3. Web 采集可选 250、500、1000 Hz，分别发送 `~6`、`~5`、`~4`。包时间戳、缓冲窗口和页面采样率随选择更新。现有睡眠模型仍要求 250 Hz；500/1000 Hz 数据必须经抗混叠重采样并验证后才能接入模型，当前 Web 服务尚未调用模型。
4. 真实设备模式的通道编号和物理帽位对应关系仍需通过设备资料或逐通道验证确认，页面显示的名称不能代替硬件验证。
5. 采集线程和 WebSocket 推送分离，浏览器断开不会停止设备采集；点击停止或后端关闭时才释放 BrainFlow 会话。
6. WebSocket 队列有长度上限，浏览器处理较慢时丢弃旧显示块，避免内存无限增长；这只影响页面显示，不改变设备读取线程。
