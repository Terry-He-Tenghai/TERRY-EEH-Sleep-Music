# 03 当前模型、训练与历史推理

更新：2026-10-11。返回 [目录](README.md)。

## 1. 当前 LIVE 主模型

[waveform_classifier.py](../../backEnd/waveform_classifier.py) 的 `WaveformClassifier` 使用 CPU 加载 PyTorch CNN，输出 W/N1/N2 三类 softmax 分数。来源标识为 `trained_waveform_cnn_experimental`。

| 参数 | 当前实现 |
| --- | --- |
| 实际采集 | 16 路原始微伏 |
| 分类模型选项 | 2、4、6、8、16 |
| LIVE 采样率 | 250 Hz |
| 滚动缓冲 | 40 秒 |
| 分类输入 | 最近 30 秒，前 10 秒供滤波初始化 |
| 更新步长 | 6 秒，即 1500 样本 |
| 时间滤波 | 因果 50 Hz notch，Q=30；四阶 0.5 至 35 Hz 带通 |
| 参考/归一化 | 对应选中 montage 平均参考，微伏除以 100 |
| 分数门槛 | `minimum_stage_probability=0.55` |
| 配置确认次数 | `confirmations_required=1` |

上述 40 秒是缓冲需求，不保证第 40.000 秒立即出结果；推理按 6 秒块推进，还受数据质量和调度影响。模型确认次数和“三次 N2 音乐淡出”是两种独立规则。

## 2. 模型与权重目录

[config.waveform.yaml](../../backEnd/config.waveform.yaml) 相对于后端解析路径：

| 选择 | 电极 | 默认权重 |
| --- | --- | --- |
| 2 | Fp1、Fp2 | `results/waveform_frontal_v1/cap2/best.pt` |
| 4 | Fp1、Fp2、F3、F4 | `results/waveform_frontal_v1/cap4/best.pt` |
| 6 | Fp1、Fp2、F3、F4、F7、F8 | `results/waveform_frontal_v1/cap6/best.pt` |
| 8 | CAP 顺序前 8 路 | `results/waveform_cap_v1/cap8/best.pt` |
| 16 | CAP 全部 16 路 | `results/waveform_cap_v1/cap16/best.pt` |

额区模型的实际设备来源映射见 [02](02-eeg-acquisition-signal.md)。历史中央少通道权重 `results/waveform_subset_v1` 仍保留，但不是当前 LIVE 2/4/6 默认入口。

加载器严格检查 `channels`、`classes`、`pipeline`、`architecture`，并严格加载 `state_dict`。仅改目录、文件名或 checkpoint 标签不能使不匹配模型成为有效模型。缺权重、依赖错误或契约不符会阻断，不提供“猜一个阶段”的实时兜底。

## 3. 训练代码也是运行依赖

`WaveformClassifier.training_code` 动态加载 [train_sleep_waveform_models.py](../../script/train_sleep_waveform_models.py)，取得预处理和网络定义。2/4/6 额区入口还加载 [train_sleep_frontal_models.py](../../script/train_sleep_frontal_models.py)，后者隔离复用 [train_sleep_subset_models.py](../../script/train_sleep_subset_models.py) 的实现。

因此不能把 `script/` 全部当作部署时可删的离线目录。即便不现场训练，以上三个文件仍参与运行契约加载。subset 文件同时具有“历史中央 montage 的独立训练入口”和“当前额区代码复用核心”两个身份。

当前训练按受试者划分 train/validation/test，而不是随机混合所有窗口。额区训练复用原 split，并检查缓存/权重契约，防止中央旧模型混入。部署所需的是对应 `best.pt` 和代码契约；缓存、预测 CSV、训练报告则用于可追溯和复验。

## 4. 模型校验入口

- [check_waveform_replay.py](../../script/check_waveform_replay.py)：原 8/16 模型离线与实时输出一致性。
- [check_subset_replay.py](../../script/check_subset_replay.py)：文件名仍为 subset，意图验证额区模型；目前回放构造输入时把 Fp2 放在名义 Fp2 路，而当前 LIVE 额区契约从名义 C3 路取 Fp2。必须先按实际接线修正或核对输入映射、重新运行，不能把现状当成已通过一致性验证。
- [validate_subset_edf_reader.py](../../script/validate_subset_edf_reader.py)：EDF 读取数值核对。
- `script/test_train_sleep_waveform_models.py`、`test_sleep_frontal_contract.py`、`test_sleep_subset_models.py`、`test_training_e2e.py`：分别覆盖基础、额区、历史 subset 契约和合成训练流程。

这些验证不等价于在当前头帽、参考方式、受试者人群上验证准确率。

## 5. 旧推理仍保留在哪里

DEMO model 使用 [config.hardware.yaml](../../backEnd/config.hardware.yaml)、`src/anphy_sleep/streaming.py`、`inference.py` 等模块，以及历史 `sleep_state_logistic_30s.joblib`、`future_n2_logistic_continuous.joblib`。旧特征基线和未来 N2 预测不再是 LIVE CNN 的前置步骤。

`adaptive_web.py._process_live_fallback` 保留频谱启发式、通道修复和预训练诊断实现，但当前 `_process` 的 LIVE 分支明确调用 `_process_live_model` 后返回。它不是自动失败回退入口。

## 6. 对外表述

当前输出是研究模型估计类别和未校准分数，不是临床 PSG 分期，也不是可信的“已经入睡概率”。训练表现、软件一致性、硬件泛化、干预有效性是四种不同证据。文档不填入未经本轮核验的准确率，也不把历史离线图表当作当前 A/B/C 实验结果。
