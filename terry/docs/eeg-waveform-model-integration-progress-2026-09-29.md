# 脑电波形分类模型：训练与实时集成进度

核查日期：2026-09-29（本次会话，截至晚间）。本文件记录**已完成的代码与离线验证**，以及**尚未完成的设备/音乐服务验证**；不能把离线指标当成脑电帽实机或临床效果。

## 当前结论

- 已从本地 ANPHY-Sleep 数据训练两套独立的 W/N1/N2 原始波形一维卷积神经网络模型：`cap8`、`cap16`。不是频谱阈值分类，也不是“预测未来进入 N2”模型。
- 已把真实设备（`LIVE`）分类入口接到新波形模型；原有演示（`DEMO`）模型入口独立保留。旧频谱方法的私有诊断实现仍在代码中供历史测试使用，但**真实设备分发路径不再调用它**。模型不可用或电极质量不合格时不给出伪装的分类概率。
- 已把经过稳定确认的 W/N1/N2 分类接入现有音乐状态调度与 ACE-Step 自动生成门控，页面能显示“研究性模型、未经过实机验证”。ACE-Step 生成服务与真实脑电帽**尚未做端到端实测**。

## 数据、电极与训练

- 已核查本地去重的 28 名 EPCTL 受试者的 EDF 文件头：均具有目标 16 个帽位。EDF 的 `T5/T6` 对应帽子的 `P7/P8`，`T3/T4` 对应 `T7/T8`。不把 P7/P8 冒充 Fz/Cz。
- 8 路模型按物理设备前八路选择：`Fp1 Fp2 C3 C4 P7 P8 O1 O2`；16 路按物理设备完整顺序增加 `F7 F8 F3 F4 T7 T8 P3 P4`。**8 路分类时硬件仍采集 16 路**；第一版离线比较仅保留 16 路均通过质量检查的相同窗口，因此实时集成也要求完整的 16 路有效输入。单个电极仍可用并不足以安全调用这两套模型。
- 使用 TXT 的人工 30 秒分期 W、N1、N2 作为真值；N3、REM/R、L 没有被改标为 N2。按受试者划分训练/验证/留出测试为 16/6/6 人，8/16 模型共享划分及合格窗口。波形输入采样率 250 Hz、30 秒；按训练契约取前 10 秒上下文，使用相同的滤波和按所选通道求平均参考，再做推理。
- 训练脚本和细节：`terry/script/train_sleep_waveform_models.py`、`terry/script/TRAINING.md`；划分文件：`terry/results/waveform_cap_v1/split.json`。训练产物在 `terry/results/waveform_cap_v1/`；仅 `cap8/best.pt` 和 `cap16/best.pt` 两份部署权重纳入 Git，拉取包含该模型提交的版本会同时取得权重。训练缓存、划分文件和评估报告仍被 Git 忽略。

离线留出测试集为 6 名受试者、3,181 个通过筛选的 30 秒窗口，两套模型测试的是同一批窗口：

- `cap8`：最佳训练轮次 8；准确率 84.72%，宏平均 F1 0.7880，平衡准确率 79.47%，N1 召回率 64.74%。
- `cap16`：最佳训练轮次 15；准确率 84.25%，宏平均 F1 0.7871，平衡准确率 79.91%，N1 召回率 66.67%。

完整混淆矩阵、每类指标和未校准概率的评估在 `cap8/report.json`、`cap16/report.json` 与 `comparison.json`。这一次留出测试不能证明更多通道一定更好，也不能证明模型适用于 N3/REM 或设备使用人群。

## 目前后端实际读取哪个模型文件？

设置文件为 `terry/backEnd/config.waveform.yaml`：

```yaml
enabled: true
model_root: ../results/waveform_cap_v1
```

`model_root` **相对于设置文件所在的 `terry/backEnd/` 目录解析**，因此本机实际解析到：

```text
E:\project\test\terry\new_code\TERRY-EEH-Sleep-Music\terry\results\waveform_cap_v1
```

启动 `LIVE` 采集会话时，`terry/backEnd/waveform_classifier.py` 根据页面的 8/16 通道选择，在后端 **CPU** 上分别加载对应的一个文件，并校验通道顺序、类别、网络结构和预处理契约：

```text
8 通道：E:\project\test\terry\new_code\TERRY-EEH-Sleep-Music\terry\results\waveform_cap_v1\cap8\best.pt
16 通道：E:\project\test\terry\new_code\TERRY-EEH-Sleep-Music\terry\results\waveform_cap_v1\cap16\best.pt
```

**不是**读取 `terry/backEnd/results/models/` 中的旧 `.joblib`，也不是每 6 秒重新加载一次 `.pt`。Windows 启动脚本会先临时检查两份权重都能加载；实际会话按所选通道数只保留对应模型对象。本次核查两条上述路径均存在、可用 CPU 成功加载。若本地路径变化，修改 `config.waveform.yaml` 的 `model_root` 并重启后端；迁移时同时带上两份权重和训练脚本的预处理契约。

## 运行中分类到音乐的路径

1. `terry/backEnd/app.py` 的 BrainFlow 采集仍按 `channel_mapping.CAP_ORDER` 给出 16 路原始微伏 EEG；页面选择 8/16 指**分类模型输入**，不改变物理采集数量。
2. `terry/backEnd/adaptive_web.py` 的 LIVE 分支调用 `WaveformClassifier`。累计连续 40 秒原始数据后，按 6 秒处理批次重新评估最近 30 秒波形；首次可用输出通常在约 42 秒，经过至少两次合格同类判断才确认。断流、计数丢包、设备时间与样本数量不一致、平直/非有限/高幅度信号会等待重新收集，不产生新的模型分类结果。连续性检测同时检查循环包编号和最近约 40 秒的时间偏差变化；暂以 0.5 秒容差兼容传输批次时间戳，避免丢失 256 个样本后包编号回绕而漏检。该容差仍需实机验证；如果驱动同时掩盖包编号和时间缺口，软件不能保证识别全部丢包。
3. 后端用 W/N1/N2 分数和现有音乐调度器确定 M1/M2/M3；`terry/backEnd/ace_step.py` 仅接受来源匹配、已确认、未过期、质量合格的 LIVE 波形模型事件，才允许提交 ACE-Step 生成任务。生成结果完成后，浏览器自动播放组件再从后端获取音频；**模型本身不生成音乐**。生成、缓存、播放和分类可用性是不同环节。
4. 前端 `App.vue`、`AutomaticAcePanel.vue` 和播放校验会显示所用模型、等待/无效状态，拒绝过期或未确认事件。约 15 秒没有新的有效 LIVE 事件时，自动播放组件会停止继续使用旧分类结果。分类概率尚未校准，不应显示为医学意义的确定性置信度。

## 已验证的内容及尚需验证的内容

**已核验：**

- 本机两份训练权重路径实际存在且通过 CPU 加载和输入契约校验；FastAPI 的健康和状态接口可在本地测试客户端返回正常响应。
- 本地留出测试受试者 EPCTL07 的 10 个合格 EDF 窗口重放：8/16 通道两套模型的离线和实时适配器输出概率最大差为 0（该检查只验证数值一致性，不是硬件测试）。重放脚本：`terry/script/check_waveform_replay.py`。
- 本轮修复后重新运行相关后端单元/集成测试 **77 项通过**；训练输入契约及合成训练端到端测试 **26 项通过**；前端测试 **40 项通过**，`npm run build` 成功。新增回归覆盖 8/16 路、批次内部/边界丢失 256/512 个样本、插值时间戳掩盖瞬时缺口、冻结时间戳、批量时间戳容差和恢复后重新确认；测试同时检查恢复前 ACE-Step 缓存音频许可保持暂停。没有通过远程 ACE-Step 实际生成音频，也没有戴帽完成真实设备闭环。
- 已补齐 `terry/script/test_train_sleep_waveform_models.py`，`TRAINING.md` 中的完整测试命令现在可执行。新增训练测试只使用合成数据，不改写原始 EDF 或已有权重。
- 本轮完整后端回归 **382 项通过、4 项跳过**。4 项均为当前 Windows 缺少符号链接创建权限的文件安全测试，需在具备该权限的 Windows 或 Linux 环境补验；没有将跳过计为通过。另有 12 条 FastAPI 生命周期弃用警告，不影响本轮测试结果。
- 完整回归发现并修复了 DEMO 分发遗漏：按 `config.hardware.yaml` 的历史演示通道读取配置并校验顺序，将“预设演示只能来自 DEMO”的保护提前到 LIVE 分发之前；与真实帽位模型的 `config.waveform.yaml` 保持独立。更新了旧分类确认及缓存音乐测试，使其符合现行三次 DEMO 确认和音乐声部映射；未降低 LIVE 分类门控。
- 已向本地 `terry/script/.venv` 补装完整测试需要的 `soundfile`、`seaborn`、`statsmodels`、`pyarrow`；这些依赖原本已在后端 `pyproject.toml` 声明，未改全局 Python 环境。最小实时依赖文件不等于完整离线测试环境。

**Conda 启动环境修复（2026-09-29 晚间）：**

- 用户的 `D:\pythonenv\conda_envs\terry-backend` 环境曾通过旧的可编辑安装导入 `E:\project\test\terry\terry\backEnd\src\anphy_sleep\streaming.py`，导致当前网页后端调用旧 `SignalPipeline` 时缺少 `filter_sos`。当前仓库的该属性原本已存在；本次通过在当前 `backEnd` 目录执行 `python -m pip install --no-deps -e .` 修正了环境中的项目路径。
- 将该 Conda 环境的 scikit-learn 从 1.9.1 对齐到 DEMO `.joblib` 序列化版本 1.7.2，同时在后端依赖声明中固定该版本。此修复针对旧 DEMO 模型，不改变 LIVE 的 PyTorch 波形模型。
- 在用户的 Conda 环境中加载真实 DEMO 权重，将版本不一致警告设为错误，完成 6 秒合成脑电的质量检查与流式处理，正常输出 `warming_up`；相关回归测试 40 项通过。新增测试验证质量检查与 `SignalPipeline` 共用滤波系数但不改写流式滤波状态。
- 已运行的后端仍持有旧模块，必须先停止，再在当前项目 `backEnd` 目录使用 `python -m uvicorn app:app --host 127.0.0.1 --port 8000` 重启。移动仓库后须重新安装可编辑包；切换工作目录本身不会更新旧安装路径。

**下一步：**

1. 戴帽记录 16 路的真实接线、参考/偏置、采样率、增益和滤波设置；核对 BrainFlow 输出和训练 EDF 数据定义是否足够一致。若参考方式或信号质量不匹配，先适配并重做独立设备验证，不要宣称当前离线准确率就是实机准确率。
2. 用有人工同步标注的实际脑电帽数据检验 W/N1/N2，特别检查 N1 少数类、N3/REM 场景与电极断续；必要时重训或扩展为五分类。**当前模型对 N3/REM 不提供有效分类保证。**
3. 确认独立 ACE-Step 服务可用、网络地址/认证与浏览器音频授权；在人工监督下做采集→分类→音乐状态→生成→播放完整测试。生成服务不可用时应显示状态，不表示分类器失效。

在本机 Windows 上，如果准备启动集成后端，先关闭占用 8000 端口的旧后端，然后运行 `terry/backEnd/start_waveform_backend.ps1`。它复用 `terry/script/.venv`（本机已装的训练依赖和后端依赖）并预检两个权重。新电脑需要先按 `terry/script/TRAINING.md` 创建 Python 环境并安装 PyTorch，再安装 `terry/backEnd/requirements-waveform-live.txt` 中的实时服务依赖，并确认拉取的代码版本包含两份模型权重。不要把 `config.waveform.yaml` 的 `enabled: true` 理解为已经完成实机/医学验证，两个权重仍标记 `deployment_ready=false`。
