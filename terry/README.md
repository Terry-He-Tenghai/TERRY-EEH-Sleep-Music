# ANPHY-Sleep 16通道入眠分析

本项目是一个面向入眠过程的可解释EEG分析与音乐控制原型。项目只使用预定的
16通道分析ANPHY-Sleep，不与83通道模型比较。

系统同时回答三个问题：

1. 当前处于清醒（W）、入睡过渡（N1）还是稳定浅睡（N2）？
2. 当前窗口之后5分钟内是否会首次进入稳定N2？
3. 如何将状态概率、未来N2概率和可解释频谱特征转化为低频、可回退的音乐控制命令？

## 最新代码架构说明

详见 [项目架构、数据流与算法详解](docs/PROJECT_ARCHITECTURE_AND_ALGORITHMS.md)（代码基准 `ca590ab`）。文档覆盖 Vue/FastAPI、采集与质量控制、特征工程、两个机器学习任务、四分轨自适应播放及上传功能边界，并区分默认预设动态演示与真实模型推理。上传音频暂不纳入 MIDI 修改路线；独立叠加音符不等于修改原曲。本文下方历史研究结果不可直接视为新版硬件配置、通道补全或音乐干预的验证结果。

## macOS 一键启动前后端

### ACE-Step 1.5 风格生成

服务器运行 `./start_api_server.sh` 后，在运行 Terry 后端的同一台电脑上保持 SSH 隧道（该终端不要关闭）：

```bash
ssh -o ExitOnForwardFailure=yes -L 8001:127.0.0.1:8001 -p 36212 root@connect.nmb2.seetacloud.com -N
curl http://127.0.0.1:8001/health
```

设置 `ACE_STEP_URL`（默认 `http://127.0.0.1:8001`）和可选的 `ACE_STEP_API_KEY`，不要把服务器密码写入项目。采集前选择“AI · 脑电分类生成”和音乐风格（氛围、钢琴、自然、弦乐、电子），点击“开始采集”授权浏览器音频。有效的模型分类、质量检查和约5分钟基线就绪后，后端按 M1/M2/M3 状态自动提交 ACE-Step 任务，生成 WAV 并自动播放；状态变化时生成下一段，同状态复用缓存，信号失效时暂停。首次任务及每次新状态生成需要等待，60秒内不会重复提交。默认“模型验证”使用合成 EEG 验证管线，不代表真实睡眠；“预设演示”不触发生成。真实设备须确认250Hz采样、通道映射与模型适配。单独的“高级工具 · AI 生成调试”仅用于手动试听。

Terry 后端提供 `GET /api/ace/health`、`GET /api/ace/styles`、`POST /api/ace/generations`（`style`、`duration`、可选 `description`）、`GET /api/ace/generations/{task_id}`、`GET /api/ace/generations/{task_id}/audio`（支持单段 Range）及 `GET /api/ace/automatic/status`；前端不直接连接远端服务。音频使用 WAV，无需远端 ffmpeg；远端任务保存在 ACE-Step 进程中，重启后旧任务可能不可查询。

在 Finder 中双击项目根目录 `start_all.command`，分别打开后端与前端终端。前端使用 pnpm 安装锁定依赖并启动 Vue 开发服务器，后端复用 `backEnd/start_backend.command` 的 uv 安装与启动流程。前端就绪后自动打开 `http://127.0.0.1:5173`；首次安装需联网，后端准备期间页面可能暂时提示连接失败。

前置依赖：Node.js、pnpm、uv。若端口8000或5173已被占用，脚本提示停止旧服务，不会杀掉已有进程。停止系统时分别在两个服务终端按 Ctrl+C。启动脚本不会自动开始脑电采集或授权声音；进入页面后仍需点击“开始采集”。

## 已实现功能

### EEG与论文分析

1. 自动下载、断点续传和MD5校验ANPHY-Sleep公开压缩包。
2. 从原始EDF和标注中匹配16个目标通道，并兼容`T3/T4`到`T7/T8`的别名。
3. 平均参考、250 Hz降采样、50 Hz陷波及5–50 Hz因果IIR带通滤波、6秒窗口和3秒步长。
4. 联合ANPHY伪迹矩阵、振幅、平坦通道和有效通道比例进行质量控制。
5. 提取delta、theta、alpha、sigma、beta和high-beta功率谱密度特征。
6. 分析额区beta、枕顶alpha、中央theta/sigma和额中央delta的入眠轨迹。
7. 检测中央区spindle，作为N2建立的描述性生理证据。
8. 按30秒AASM epoch进行W/N1/N2三分类，使用严格的受试者留一验证。
9. 从记录起点预测未来5分钟稳定N2，包含时间、状态、静态EEG和动态EEG消融。
10. 输出效应量、bootstrap置信区间、FDR校正、混淆矩阵和事件级提前预警指标。
11. 一键生成论文用PNG/PDF图、CSV表和产物清单。

### 实时接口与音乐控制

1. 使用`EegChunk`接收任意长度的连续16通道EEG数据块。
2. 在线保持平均参考、因果滤波、环形窗口、历史斜率和5分钟稳健基线状态。
3. 每3秒最多输出一次W/N1/N2概率、未来N2概率、信号质量和可解释特征。
4. 提供高觉醒W、放松W、N1过渡、微觉醒修复和N2保护五种音乐控制模式。
5. 使用连续确认、最短驻留时间和冷却时间避免频繁切换。
6. Suno生成、音乐播放和EEG推理分别运行，网络或播放器不会阻塞EEG线程。
7. 支持预生成、回调缓存、人工审核、缓存选曲、交叉淡入、叠加、淡出和停止。
8. 提供无网络、无声卡的策略演示，以及可选的VLC真实播放后端。

### 当前验证结果

当前公开队列纳入28名健康成人。动态多项Logistic Regression的W/N1/N2受试者级
LOSO平衡准确率约为0.774，Macro-F1约为0.746，Cohen's Kappa约为0.675。
记录起点锚定的动态EEG未来N2预测平均AUC约为0.821，目标5分钟事件检出率约为
89.3%，中位提前时间约为3.75分钟。

这些结果属于同一公开队列内的内部验证，不是外部验证、临床诊断或音乐疗效证据。

## 研究目标

1. 描述额区beta、枕顶alpha和额中央theta在首次稳定N2前后的变化。
2. 检测中央区spindle，作为N2建立的描述性证据。
3. 按30秒AASM epoch识别当前W、N1或N2状态。
4. 预测当前窗口之后5分钟内是否进入首次稳定N2。
5. 以通用流式接口接收连续16通道EEG，并可选输出五模式事件驱动音乐命令。

## 科学边界

- “稳定N2”定义为第一次连续60秒N2。
- spindle不进入未来N2预测特征，避免用N2评分依据预测N2造成循环论证。
- 预测窗口只使用当前和过去的数据；滤波为因果IIR，1分钟斜率只向后计算。
- 所有预测验证按受试者留一，禁止随机拆分重叠窗口。
- 结果支持健康人入眠动力学及16通道方案可行性，不证明音乐疗效或失眠诊断性能。

## 16通道

科学分析默认使用`config.yaml`中的睡眠16通道：

`Fp1 Fp2 F3 F4 F7 F8 Fz C3 C4 Cz T7 T8 P3 P4 O1 O2`

ANPHY使用旧命名`T3/T4`，代码分别映射为`T7/T8`。

真实16通道脑电帽使用独立配置`config.hardware.yaml`，不覆盖上述科学通道结果。帽位按设备CH0–CH15为：

`C3 C4 Cz FC3 FC4 CP3 CP4 FCz CPz Fz P3 Pz P4 O1 Oz O2`

区域特征仍用同一组名字（额区beta、枕区alpha、中央theta等），但额区改为`Fz/FC3/FCz/FC4`，中央区加入`CP*`，枕区加入`Pz/Oz`。没有前额和颞叶通道。两条管线的模型文件不能混用。

## 项目结构

```text
terry/
├── frontEnd/                   # Vue 3、Vite、Canvas 波形页面
├── backEnd/                    # Python 工程根目录
│   ├── app.py                  # FastAPI、BrainFlow/demo 和 WebSocket
│   ├── __init__.py
│   ├── src/anphy_sleep/        # 分析、模型、流式接口与音乐系统源码
│   │   └── music_engine/       # 四层混音、MIDI、波形处理与乐句调度
│   ├── tests/                  # 单元与合成数据测试
│   ├── scripts/                # 数据下载、续传和校验脚本
│   ├── results/                # 模型、图、表、回放和音乐缓存
│   ├── data/                   # 按需生成，原始数据和处理后特征
│   ├── .env.example            # 本地环境变量模板
│   ├── config.yaml             # 睡眠16通道科学分析配置
│   ├── config.hardware.yaml    # 真实脑电帽16通道配置
│   ├── eeg.py                  # 硬件采集入口
│   ├── pyproject.toml          # Python包与依赖
│   └── uv.lock                 # uv锁定的依赖版本
├── docs/                       # 方法、接口、实验与 Web 使用说明
├── README.md
├── 进度.md
└── .gitignore
```

`data/`、原始EDF、Parquet中间表、虚拟环境和大部分可重复生成的`results/`内容
默认被`.gitignore`排除。论文图表、关键CSV以及实时和回放所需的四个小型模型会被
Git追踪。接收者不会自动获得原始数据；如需重新训练，仍须下载ANPHY-Sleep并运行
完整数据管线。

## AISAASGO 音乐生成与代码说明

已新增独立命令行工具 `backEnd/scripts/generate_suno.py`，使用环境变量 `AISAASGO_API_KEY` 调用异步 `suno-v5.5` 接口，支持单次提交、任务查询和本地候选下载。工具不自动批准音频或播放，真实密钥不得提交仓库。

- 使用说明与费用/恢复边界：`docs/AISAASGO_SUNO_API.md`。
- 代码解释、数据流、算法公式和状态机：`docs/CODE_AND_ALGORITHMS.md`；后续代码变更须同步维护该文档与 `进度.md`。
- 生成提示词：`docs/offline_music_suno_prompts.md`；人工审核入库：`docs/offline_music_library.md`。

## 环境要求

- Python 3.10或更高版本。
- 使用`uv`同步Python、项目依赖和开发测试依赖。
- 下载完整ANPHY-Sleep需要较大的磁盘空间和稳定网络，建议先下载一个受试者。
- 真实音乐播放需要系统安装VLC/libVLC；仅运行分析、测试和音乐策略演示不需要VLC。
- 以下 Python 命令均在 `terry/backEnd/` 执行，且`--config`必须写在子命令之前。
- 文中的 `config.yaml`、`src/`、`tests/`、`scripts/`、`data/`、`results/` 均相对于 `backEnd/`；`docs/` 路径相对于仓库根目录 `terry/`。
- 根目录仅保留 `frontEnd/`、`backEnd/`、`docs/` 三个业务文件夹；隐藏的 `.git/` 用于版本管理，必须保留。

## 使用uv一键同步

项目已提交 `backEnd/uv.lock`。安装好 uv 后，从仓库根目录进入后端工程：

```bash
cd backEnd
uv sync
```

`uv sync`会自动创建或更新项目的`.venv`，安装基础分析依赖、当前项目和
`pytest`开发依赖。若需要严格按照已提交锁文件同步且不允许锁文件变化：

```bash
uv sync --frozen
```

如需安装可选的Python VLC适配器：

```bash
uv sync --extra music
```

`uv`只管理Python环境。它不会下载ANPHY-Sleep原始数据，也不会安装操作系统的
VLC/libVLC。基础论文分析除数据集外不需要再手工安装其他Python包。

后文统一使用`uv run`执行项目命令，不需要手动激活虚拟环境。

### WSL使用Windows系统代理

`uv`自动读取`HTTP_PROXY`、`HTTPS_PROXY`和`ALL_PROXY`。如果Windows已经开启
系统代理，但WSL下载仍然较慢，可先在Windows代理软件或系统设置中确认代理地址。
例如代理为`127.0.0.1:10808`时：

```bash
export HTTP_PROXY="http://127.0.0.1:10808"
export HTTPS_PROXY="http://127.0.0.1:10808"
export ALL_PROXY="http://127.0.0.1:10808"

uv sync
```

当前终端关闭后这些变量会失效。其他机器应替换为自己的地址和端口，不要直接照搬
`10808`。如果WSL无法访问Windows的`127.0.0.1`，需要在代理软件中允许局域网连接，
并把`127.0.0.1`替换为WSL可访问的Windows主机地址。

### 验证安装

```bash
uv run anphy-sleep --help
uv run anphy-sleep --config config.yaml process --help
```

运行测试：

```bash
uv run pytest
```

## 最短演示

不下载数据、不访问网络、不调用音频设备，也可以先验证五模式状态机：

```bash
uv run anphy-sleep --config config.yaml music-demo \
  --output results/music/policy_demo.jsonl
```

结果写入`results/music/policy_demo.jsonl`。

## 数据下载

下载脚本直接访问ANPHY-Sleep的OSF公开存储，支持`.part`断点续传，并在结束后校验
文件大小和MD5。

列出公开文件：

```bash
uv run python scripts/download_anphy.py --list
```

先下载单名受试者：

```bash
uv run python scripts/download_anphy.py \
  --subject EPCTL11 \
  --output data/raw
```

单人流程验证通过后再下载OSF当前可用的全部受试者。当前公开存储可纳入28人，
缺少`EPCTL08`：

```bash
uv run python scripts/download_anphy.py \
  --all \
  --output data/raw
```

重复执行下载命令时，完整且MD5正确的文件会直接跳过；未完成的`.part`文件会尝试
续传。

## 推荐的完整执行顺序

首次接手项目时，按下面顺序执行。全体分析耗时和内存取决于机器配置。

```bash
# 1. 解压data/raw中的EPCTL*.zip
uv run anphy-sleep --config config.yaml extract

# 2. 先验证一个受试者
uv run anphy-sleep --config config.yaml process --subject EPCTL11
uv run anphy-sleep --config config.yaml process-continuous --subject EPCTL11

# 3. 提取全体N2对齐特征和记录起点连续特征
uv run anphy-sleep --config config.yaml process
uv run anphy-sleep --config config.yaml process-continuous

# 4. 运行生理统计、W/N1/N2分类和未来N2预测
uv run anphy-sleep --config config.yaml analyze
uv run anphy-sleep --config config.yaml classify
uv run anphy-sleep --config config.yaml predict-continuous

# 5. 汇总论文图表
uv run anphy-sleep --config config.yaml paper

# 6. 使用已训练模型验证原始EEG流式公共接口
uv run anphy-sleep --config config.yaml stream-demo \
  --seconds 45 \
  --chunk-seconds 1
```

旧版N2对齐预测仍保留用于复现早期结果，但不作为当前主结论：

```bash
uv run anphy-sleep --config config.yaml predict
```

真实脑电帽不要改`config.yaml`，也不要覆盖`results/models/`里的科学模型。原始EDF仍用同一次`extract`，之后换配置单独提取和训练：

```bash
uv run anphy-sleep --config config.hardware.yaml process
uv run anphy-sleep --config config.hardware.yaml process-continuous
uv run anphy-sleep --config config.hardware.yaml classify
uv run anphy-sleep --config config.hardware.yaml predict-continuous
```

帽位模型写到：

```text
results/hardware/models/sleep_state_logistic_30s.joblib
results/hardware/models/future_n2_logistic_continuous.joblib
```

推理代码不用改。上线时把`--config`换成`config.hardware.yaml`，并保证设备数据块里的16个通道名与帽位名单一致。只替换`.joblib`、仍用`config.yaml`会因通道名不匹配而失败。

## 命令说明

### `extract`

用途：解压`data/raw/EPCTL*.zip`到`data/raw/extracted/`。已解压受试者会跳过。

```bash
uv run anphy-sleep --config config.yaml extract
```

### `process`

用途：截取首次稳定N2前后片段，进行预处理、窗口特征提取和spindle检测。

前置条件：先运行`extract`。

```bash
# 单人，适合调试
uv run anphy-sleep --config config.yaml process --subject EPCTL11

# 全体，已有features.parquet的受试者会跳过
uv run anphy-sleep --config config.yaml process
```

主要输出：

```text
data/processed/EPCTLxx/features.parquet
data/processed/EPCTLxx/spindles.csv
data/processed/EPCTLxx/metadata.json
data/processed/processing_failures.csv
```

全体模式下单个受试者失败不会终止整批处理，失败原因写入
`processing_failures.csv`；指定`--subject`时错误会直接抛出。

### `process-continuous`

用途：从记录起点提取部署式连续特征，避免使用未来N2时间确定预测起点。

前置条件：先运行`extract`。

```bash
# 单人
uv run anphy-sleep --config config.yaml \
  process-continuous --subject EPCTL11

# 全体
uv run anphy-sleep --config config.yaml process-continuous
```

主要输出：

```text
data/processed/EPCTLxx/continuous_features.parquet
data/processed/EPCTLxx/continuous_metadata.json
data/processed/continuous_processing_failures.csv
```

### `analyze`

用途：生成入眠轨迹、16通道地形图、信号质量报告、混合效应模型和配对效应量。

前置条件：先运行全体`process`。少于10名受试者时只生成技术和描述性结果，不运行
组水平推断统计。

```bash
uv run anphy-sleep --config config.yaml analyze
```

### `classify`

用途：将6秒因果窗口聚合到30秒AASM epoch，运行W/N1/N2三分类LOSO、混淆矩阵和
PSD阶段对比，并训练实时状态模型。

前置条件：先运行全体`process`。

```bash
uv run anphy-sleep --config config.yaml classify
```

关键模型：

```text
results/models/sleep_state_logistic_30s.joblib
```

### `predict-continuous`

用途：在记录起点连续流上运行未来5分钟N2预测、模型消融和事件级评价，并训练实时
预测模型。

前置条件：先运行全体`process-continuous`。

```bash
uv run anphy-sleep --config config.yaml predict-continuous
```

关键模型：

```text
results/models/future_n2_logistic_continuous.joblib
```

### `predict`

用途：运行早期的稳定N2对齐预测。该命令只用于复现和方法比较，不是当前推荐的主
预测结果。

前置条件：先运行全体`process`。

```bash
uv run anphy-sleep --config config.yaml predict
```

### `replay`

用途：回放已经提取的历史窗口特征，每3秒产生一个JSON状态。`--speed 0`表示不等待，
立即写出；`--speed 1`表示按真实时间等待；其他正数表示相应倍速。

前置条件：先运行`process`和`predict`，因为该兼容回放使用早期N2对齐模型。

```bash
uv run anphy-sleep --config config.yaml replay \
  --subject EPCTL11 \
  --speed 0
```

输出：`results/replay/EPCTL11.jsonl`。

### `paper`

用途：读取已生成的分析结果，统一生成论文版PNG/PDF图、CSV表和manifest。

前置条件：建议先完成`analyze`、`classify`和`predict-continuous`；缺少可选分析结果
时只生成当前可用的图表。

```bash
uv run anphy-sleep --config config.yaml paper
```

输出：`results/paper/figures/`、`results/paper/tables/`和
`results/paper/manifest.json`。

### `stream-demo`

用途：生成合成16通道EEG，以指定数据块大小通过真实的`RealtimeSession`，验证
“连续原始EEG→因果处理→两个模型→音乐空控制器”的端到端接口。

前置条件：先运行`classify`和`predict-continuous`生成两个部署模型。

```bash
uv run anphy-sleep --config config.yaml stream-demo \
  --seconds 45 \
  --chunk-seconds 1 \
  --output results/realtime/stream_demo.jsonl
```

`--seconds`至少应覆盖预热和30秒状态聚合；推荐不低于45秒。

### `music-demo`

用途：使用一组模拟状态演示五模式状态机。它不需要数据、模型、API Key、网络或
音频设备。

```bash
uv run anphy-sleep --config config.yaml music-demo

# 或写入JSONL
uv run anphy-sleep --config config.yaml music-demo \
  --output results/music/policy_demo.jsonl
```

### `music-callback-server`

用途：接收音乐生成服务的异步回调，并把任务和音轨写入持久缓存。

```bash
export SUNO_CALLBACK_SECRET="替换为不可猜测的随机长字符串"

uv run anphy-sleep --config config.yaml \
  music-callback-server \
  --host 127.0.0.1 \
  --port 8765
```

本地接收路径为：

```text
http://127.0.0.1:8765/suno/callback/<SUNO_CALLBACK_SECRET>
```

音乐服务必须能访问一个公网HTTPS地址，因此真实使用时需要通过反向代理或安全隧道
把该路径暴露为：

```text
https://your-domain.example/suno/callback/<SUNO_CALLBACK_SECRET>
```

不要把secret写入Git、`config.yaml`或命令历史。

### `music-render-demo`：音乐增强离线预览

不接入脑电、不访问网络、不调用播放器，即可验证四层混音、M1/M2/M3 增益、确定性 MIDI 动机和波形指标：

```bash
uv run anphy-sleep --config config.yaml music-render-demo \
  --state M1 --bars 8 --seed 42 \
  --output-dir results/music/renders/M1
```

`--state` 可选 `M1`、`M2` 或 `M3`。命令会生成 `pad.wav`、`melody.wav`、`bass.wav`、`texture.wav`、`mix.wav`、`arrangement.mid` 和 `manifest.json`。`manifest.json` 保存状态、随机种子、层增益、MIDI 约束指标和波形指标，因此可以用于重复性检查。

该命令中的正弦音色仅是无第三方合成器依赖的实验预览，不代表最终听感。正式素材应按照 `docs/SUNO_AUDIO_PROMPTS.md` 生成、审核并冻结到本地。


用途：为四种需要音乐的模式各提交一次生成任务。N2保护模式只淡出，不生成音乐。

前置条件：设置API Key，启动回调服务，并准备可公网访问的回调URL。

```bash
export SUNO_API_KEY="你的API Key"

uv run anphy-sleep --config config.yaml \
  music-pregenerate \
  --callback-url \
  "https://your-domain.example/suno/callback/<SUNO_CALLBACK_SECRET>"
```

已登记任务的模式不会重复提交。任务和回调结果保存在
`results/music/cache.json`。

### `music-cache`

用途：查看已提交任务、生成状态、缓存音轨和人工审核状态。

```bash
uv run anphy-sleep --config config.yaml music-cache
```

### `music-approve`

用途：批准一首已经缓存的音轨。默认`approved_only: true`，未批准音轨不会自动播放。

先运行`music-cache`确认模式和索引，再执行：

```bash
uv run anphy-sleep --config config.yaml \
  music-approve \
  --mode anti_hyperarousal \
  --index 0
```

可用模式：

```text
anti_hyperarousal
alpha_stabilization
theta_transition
micro_arousal_repair
sleep_protection
```

`sleep_protection`通常没有生成音轨，因为它的目标是淡出或停止。

## 真实音乐体验

真实体验不是运行`music-demo`；`music-demo`只验证策略。完整体验需要四部分：

1. `classify`和`predict-continuous`生成部署模型。
2. `music-pregenerate`生成候选音乐，回调写入缓存。
3. 使用`music-cache`检查并用`music-approve`批准音轨。
4. 真实16通道设备持续构造`EegChunk`，通过`RealtimeSession`推理，并把
   `AdaptiveMusicRuntime`作为音乐控制器。

安装系统VLC。Ubuntu/Debian可使用：

```bash
sudo apt update
sudo apt install vlc
uv sync --extra music
```

在`config.yaml`中设置：

```yaml
music:
  enabled: false
  approved_only: true
  player_backend: "vlc"
```

当音轨已经预生成并审核后，推荐保持`enabled: false`，运行期间只使用缓存，不依赖
公网生成。如果希望运行时缓存缺失时后台提交任务，则设置`enabled: true`，同时填写
`music.suno.callback_url`并设置`SUNO_API_KEY`。

接入代码骨架如下：

```python
from anphy_sleep import EegChunk, RealtimeSession, build_music_runtime
from anphy_sleep.config import load_config

config, _ = load_config("config.yaml")
model_dir = "results/models"

music_runtime = build_music_runtime(config)
music_runtime.start(pregenerate=False)

session = RealtimeSession(
    config,
    prediction_model_path=(
        f"{model_dir}/future_n2_logistic_continuous.joblib"
    ),
    state_model_path=f"{model_dir}/sleep_state_logistic_30s.joblib",
    session_id="device-001",
    music_controller=music_runtime,
)

try:
    # 设备驱动负责持续构造EegChunk，然后调用：
    # outputs = session.push(eeg_chunk)
    # 每个output同时包含state和music命令。
    pass
finally:
    music_runtime.shutdown()
```

项目提供公共数据契约和运行时，但不包含特定厂商的EEG设备驱动。设备侧必须自行
实现采集、时间戳、丢包处理，并把数据转换为`EegChunk`。

WSL中的音频设备不等同于Windows主机音频。若VLC无法找到音频输出，建议在具有稳定
声卡的Windows/Linux主机进程中运行播放器或整个实时端。

## 主要输出

`results/`中生成：

- `sleep_onset_band_trajectories.png`：beta、alpha、theta入眠曲线及95%区间
- `band_topographies_16ch.png`：早期基线到N2前5分钟的16通道地形变化
- `mixed_effects_results.csv`：线性/二次混合效应结果
- `paired_effect_sizes.csv`：配对效应量与bootstrap 95%区间
- `signal_quality_summary.csv`：伪迹和有效窗口报告
- `model_comparison.csv`：AUC、平衡准确率、灵敏度、特异度和F1
- `prediction_lead_times.csv`：持续预警的提前时间
- `stage_model_comparison.csv`：W/N1/N2三分类LOSO结果
- `stage_confusion_matrix.csv`：三分类归一化混淆矩阵
- `stage_power_contrasts.csv`：PSD区域频带的W→N1与N1→N2效应
- `continuous_model_comparison.csv`：记录起点预测和特征消融
- `continuous_event_metrics.csv`：目标事件检出率与提前误报
- `continuous_auc_ablation_comparisons.csv`：动态EEG与各基线的配对AUC比较
- `models/sleep_state_logistic_30s.joblib`：实时W/N1/N2状态模型
- `models/future_n2_logistic_continuous.joblib`：实时未来N2预测模型
- `replay/EPCTLxx.jsonl`：每3秒一个离线流式状态输出
- `paper/figures/`：效应量、模型、质量、系数和spindle的PNG/PDF图
- `paper/tables/`：论文用统计表
- `paper/manifest.json`：论文产物和关键参数清单
- `realtime/stream_demo.jsonl`：真实原始信号接口的端到端示例
- `music/cache.json`：Suno任务、回调音轨和人工审核状态

## 第一阶段 Web 采集与波形展示

第一阶段前后端已经分开：

```text
backEnd/    # FastAPI、BrainFlow/demo 采集线程、WebSocket
frontEnd/   # Vue 3、Vite、Canvas 16 通道波形页面
```

详细启动说明见 `docs/web_waveform_phase1.md`。后端在 `terry/backEnd/` 中启动：

```bash
uv sync --extra web --extra hardware
uv run uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

前端在另一个终端中启动（从仓库根目录 `terry/` 开始）：

```bash
cd frontEnd
pnpm install
pnpm dev
```

浏览器访问 `http://localhost:5173`。没有脑电帽时可选择“演示信号”验证完整 WebSocket 和波形显示链路；真实设备模式使用 BrainFlow 连接 LK-Mini-EEG16。第一阶段页面提供数据采集和波形展示，采样率可选 250、500、1000 Hz。现已增加审核后的本地音乐库及手动播放/渐变音量面板，使用方式见 `docs/offline_music_library.md`。睡眠推理和脑电驱动自动音乐控制仍待接入，不能将手动试听视为完整闭环系统。


嵌入式或采集端按任意连续数据块调用`RealtimeSession.push()`。接口按通道名
对齐，支持`T3/T4`别名；v1要求设备输出250 Hz，单位可选`V`或`uV`。

```python
from anphy_sleep import EegChunk, RealtimeSession

session = RealtimeSession(
    config,
    prediction_model_path="results/models/future_n2_logistic_continuous.joblib",
    state_model_path="results/models/sleep_state_logistic_30s.joblib",
    session_id="device-001",
)

outputs = session.push(
    EegChunk(
        timestamp_s=0.0,
        sample_rate_hz=250.0,
        channel_names=(
            "Fp1", "Fp2", "F3", "F4", "F7", "F8", "Fz", "C3",
            "C4", "Cz", "T7", "T8", "P3", "P4", "O1", "O2",
        ),
        samples=eeg_volts,  # shape=(16, n_samples)
        unit="V",
        session_id="device-001",
    )
)
for output in outputs:
    send_json(output.to_dict())
```

每3秒最多输出一次，包含：

- `state.status`：`warming_up`、`ok`或`signal_invalid`
- `state.signal_quality`
- `state.n2_within_5m_probability`
- `state.aasm_state_probabilities`
- `state.interpretable_features`
- `music.action`

默认`NoOpMusicController`始终返回`action="none"`，不会调用外部服务。后续只需
实现`MusicController.update(state)`并注入`RealtimeSession`，无需修改EEG或模型层。
完整字段、状态机和适配器说明见`docs/realtime_interface.md`。

项目同时提供`FiveModeMusicController`和`AdaptiveMusicRuntime`：每30秒评估一次
平滑状态，每个模式至少连续确认两次才切换；Suno生成与播放器分别在后台Worker中
执行，不阻塞EEG。真实API、回调、缓存审核和VLC播放步骤见
`docs/music_integration.md`。默认关闭真实音乐功能且拒绝播放未审核曲目。

前两个窗口用于预测斜率预热；W/N1/N2状态概率使用过去30秒滚动特征。5分钟稳健基线完成前仍可输出模型概率，但
`baseline_ready=false`且基线Z分数为`null`。数据块必须时间连续，不能静默跳样。

## 部署约束

- 输入必须是上述16通道，按通道名匹配而不是依赖数组顺序。
- v1不在模型端实时重采样，设备应直接输出250 Hz。
- 实时端没有ANPHY离线伪迹矩阵，只使用振幅与平坦通道质量规则。
- W/N1/N2为代理概率，不等同于临床睡眠分期。
- 当前模型只在同一健康成人队列中完成内部验证，必须经过外部数据和真实连续设备校准后才能评价音乐控制效果。

## 配置说明

通常只需要修改对应配置文件。科学分析用`config.yaml`，真实帽部署用`config.hardware.yaml`：

- `data.*`：原始数据、处理数据和结果目录。帽位管线写入`data/processed_hardware`和`results/hardware`。
- `channels.target`：固定16通道；更改后必须重提特征并重训，且不能混用另一套配置的模型。
- `signal.target_sfreq_hz`：离线目标采样率和实时输入采样率，当前为250 Hz。
- `signal.amplitude_reject_uv`：窗口振幅拒绝阈值。
- `epoching.*`：6秒窗口、3秒步长、稳定N2和5分钟预测区间。
- `quality.*`：最小有效通道和有效窗口比例。
- `prediction.probability_threshold`：未来N2事件判定阈值。
- `realtime.baseline_seconds`：在线稳健基线长度，当前为300秒。
- `music.enabled`：是否允许运行期后台生成；不影响已缓存音轨播放。
- `music.player_backend`：`null`只记录事件，`vlc`进行真实播放。
- `music.approved_only`：建议始终保持`true`。
- `music.suno.*`：API地址、模型和回调URL。
- `music.policy.*`：决策间隔、确认次数、驻留时间、概率阈值和交叉淡入时间。

修改通道、采样率、频带、窗口或特征定义后，必须重新运行特征提取并训练模型，不能
继续使用旧的`.joblib`文件。

## 常见问题

### `No extracted ANPHY subject EDF files were found`

确认已经把`EPCTL*.zip`放入`data/raw/`并运行：

```bash
uv run anphy-sleep --config config.yaml extract
```

### `No processed feature tables found`

先运行`process`。连续预测报错时，先运行`process-continuous`。

### 找不到部署模型

`stream-demo`和真实设备接口需要：

```text
results/models/sleep_state_logistic_30s.joblib
results/models/future_n2_logistic_continuous.joblib
```

分别通过以下命令生成：

```bash
uv run anphy-sleep --config config.yaml classify
uv run anphy-sleep --config config.yaml predict-continuous
```

### 流式接口暂时没有输出

系统需要积累6秒分析窗口，状态模型还需要过去30秒聚合。推荐至少推送45秒连续数据。
前5分钟`baseline_ready=false`是正常现象，模型概率仍可输出，但基线Z分数为空。

### 流式接口报告采样率或时间不连续

当前v1要求设备直接输出250 Hz，并且相邻数据块的时间戳必须连续。不要静默丢弃样本；
设备驱动应显式记录丢包并重建会话。

### 音乐生成任务没有回调

确认：

1. 回调URL是服务商可访问的公网HTTPS地址，而不是`127.0.0.1`。
2. URL路径中的secret与`SUNO_CALLBACK_SECRET`完全一致。
3. 回调服务或反向代理仍在运行。
4. `music-cache`中存在服务商回调所引用的`taskId`。

### 已有音乐但没有声音

依次检查：

1. `config.yaml`中的`player_backend`是否为`vlc`。
2. 是否同时安装`python-vlc`和系统VLC/libVLC。
3. 音轨是否已经通过`music-approve`批准。
4. 当前模式是否真的产生`play`、`crossfade`或`overlay`命令。
5. 远程音频URL是否仍可访问。
6. WSL是否能够访问主机音频设备。

### 想重新生成某个音乐模式

`music-pregenerate`会跳过已经登记任务的模式。重新生成前应备份并谨慎编辑或移除
`results/music/cache.json`中对应任务。不要在不了解缓存结构时直接删除生产缓存。

## 安全、隐私与科学边界

- `SUNO_API_KEY`和`SUNO_CALLBACK_SECRET`只通过环境变量传入，不写入仓库。
- 当前回调接收器使用不可猜测路径和已登记`taskId`校验；如果服务商提供签名头，
  正式部署前还应增加签名验证。
- `sunoapi.org`可能是第三方服务，正式使用前应核实身份、费用、许可、隐私政策和
  音乐公开播放权。
- 新生成音轨默认不批准。自动播放前应人工检查人声、鼓点、突发瞬态、响度和峰值。
- 不要向音乐API上传原始EEG、身份信息或设备标识。
- 本项目不证明音乐能够缩短入睡时间、治疗失眠或诱发特定脑电节律。
- 若新增人体音乐干预或真实受试者采集，必须在研究开始前完成相应伦理审批。

## 交接给其他人时

至少提供：

1. 完整源码、`config.yaml`、`pyproject.toml`和本README。
2. 确认四个小型回放/部署模型和`results/paper/`已被Git追踪；大型随机森林模型
   和中间结果不会入库。
3. 如果要展示论文结果，提供`results/paper/`和对应CSV，而不是只提供截图。
4. 如果要体验音乐，提供经过审核的缓存及合法可访问的音频；不要提供API Key。
5. 明确数据来自ANPHY-Sleep公开数据集，不要把公开数据描述为自行采集。

仓库目前没有根级开源许可证。私下交接不等于授权公开转载、修改或再分发；如果准备
公开发布，应先添加明确的LICENSE，并分别核对代码、ANPHY-Sleep数据和生成音乐的
许可条款。

## 延伸文档

- `docs/methods.md`：论文方法、统计假设和研究边界。
- `docs/realtime_interface.md`：`EegChunk`、`StateUpdate`、`MusicCommand`完整契约。
- `docs/music_integration.md`：Suno回调、缓存审核、VLC和并发架构。
- `docs/isef_sichuan_competition_analysis.md`：竞赛创新点、风险和答辩定位。
