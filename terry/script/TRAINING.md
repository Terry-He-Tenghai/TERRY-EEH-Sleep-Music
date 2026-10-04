# 8/16 通道原始波形训练

> 2026-10-04：额区2/4/6新训练入口 `train_sleep_frontal_models.py`，组合为Fp1/Fp2、Fp1/Fp2/F3/F4、Fp1/Fp2/F3/F4/F7/F8；产物独立保存至 `results/waveform_frontal_v1`。旧中央组合和原8/16契约不覆盖。状态见 `terry/docs/eeg-frontal-model-integration-2026-10-04.md`。

> 2026-10-03：新增独立2/4/6路训练入口 `train_sleep_subset_models.py`。电极、质量范围、执行命令和实时集成见 `terry/docs/eeg-subset-model-integration-2026-10-03.md`。新模型仅检查所选电极；以下原8/16路训练契约保持不变。三套新模型实际训练结果须以新文档及各自report.json的完成记录为准。

入口：`train_sleep_waveform_models.py`。原始 EDF/TXT 始终只读；本脚本不会替换网页的实时分类器或旧模型。

## 固定训练任务

- 8 通道：`Fp1 Fp2 C3 C4 P7 P8 O1 O2`（设备前 8 路）。
- 16 通道：上述 8 路，再加 `F7 F8 F3 F4 T7 T8 P3 P4`。
- EDF 别名：`T5→P7`、`T6→P8`、`T3→T7`、`T4→T8`，兼容 `-Ref` 和 `F4-`。
- 标签：TXT 人工分期 W/N1/N2。N3、R/REM、L 排除，不改标、不合并。
- 模型：两套独立小型一维卷积神经网络，输入脑电时序波形，不计算功率谱或频带特征进行分类。
- 初版为三分类研究基线，不能处理整夜所有状态，也未证明可泛化到 LK-Mini 实机或目标人群。

## 环境（在仓库根目录执行）

```powershell
python -m venv terry/script/.venv
.\terry\script\.venv\Scripts\python.exe -m pip install -r terry/script/requirements-training.txt
.\terry\script\.venv\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

CUDA 包用于当前 NVIDIA GPU；不改全局 Python 环境。

## 执行

先用独立目录做小样本预处理检查：

```powershell
.\terry\script\.venv\Scripts\python.exe terry/script/train_sleep_waveform_models.py --dataset "E:\project\test\terry\dataset" --output terry/results/waveform_smoke_v1 --prepare-only --subject EPCTL01 --max-epochs 30
```

正式预处理及训练：

```powershell
.\terry\script\.venv\Scripts\python.exe -u terry/script/train_sleep_waveform_models.py --dataset "E:\project\test\terry\dataset" --output terry/results/waveform_cap_v1 --prepare-only
.\terry\script\.venv\Scripts\python.exe -u terry/script/train_sleep_waveform_models.py --dataset "E:\project\test\terry\dataset" --output terry/results/waveform_cap_v1 --train-only --epochs 30 --batch-size 32 --patience 7
```

也可省略 `--prepare-only/--train-only` 顺序完成两阶段。完整预处理缓存可复用；半途终止后重跑未完成的受试者。训练过程每轮保存验证指标和最佳权重，但未实现优化器断点续训；未完成的模型重跑时从头训练。已经完成且设置相同的模型保留其独立测试报告，不再次训练。

`--subject/--max-epochs` 只用于准备阶段，截断缓存不能进入正式训练。修改数据、预处理或训练配置后请使用新输出目录，避免混用结果。

## 预处理与质量控制

1. 每个 EDF 按电极名称选择 16 路，保留原始名称和参考后缀记录；校验 EDF 单位和采样率。当前实现接受连续 EDF，拒绝需要另行时间对齐的 EDF+D。
2. 从 TXT 读取实际起始秒数，保留 EPCTL23 的非零首标签。拒绝重叠、倒序或非 30 秒标签。
3. 每个目标片段读取“过去 10 秒 + 当前 30 秒”，不会预加载整夜 83 路数据。记录开头不足 10 秒上下文的窗口不训练。
4. 对该 40 秒缓冲区做抗混叠重采样到 250 Hz、50 Hz 陷波、0.5–35 Hz 因果带通；滤波状态在缓冲区开头初始化，丢弃前 10 秒。`resample_poly` 使用整个当前缓冲区，预测在该 30 秒窗口结束后产生，不使用下一窗口。
5. 剔除非有限值、平直段、低变异及高幅度窗口。为使 8/16 通道的比较使用同一批样本，初版要求 16 路均通过质检；这比只检查 8 路更保守。按受试者保存各类样本数和剔除原因。
6. 缓存的是 **16 路未重参考**的滤波微伏波形。训练时先选择 8 或 16 路，再减去该组通道的逐采样均值，最后除以固定 100 µV。没有对整夜或测试受试者拟合归一化统计量。
7. 缓存使用内存映射 NPY，形状容量可能大于有效样本数；只允许通过对应 JSON 的 `labels`/`starts_seconds` 索引读取有效部分。

这套处理必须与未来部署保持一致：实时模型需要 40 秒缓冲区，输入单位、重参考、滤波、切窗、采样率和通道顺序均需遵守模型契约。只在标签或后缀中看到 Ref，并不能确认数据集和实机的原始参考一致；硬件参考验证仍未完成。

## 划分和评估

- 按受试者固定随机划分，随机种子 42；28 人时训练/验证/测试分别为 16/6/6 人。两套模型共享 `split.json`。
- 全部切窗和重叠上下文都保留在受试者所属集合内。测试集不用于早停、类别权重或学习率选择。
- 类别权重仅按训练集计数计算。验证集宏平均 F1 选择最佳轮次并早停。
- 测试报告包括宏平均 F1、平衡准确率、各类召回、混淆矩阵、Cohen kappa、Brier score 和概率校准误差。概率未执行后处理校准，不应直接当成可靠的医学置信度。
- 单次 6 人留出测试只是初版结果；后续可做受试者交叉验证和独立实机标注验证。不得反复查看留出测试分数再调参却仍称其为独立测试。

## 输出

`terry/results/waveform_cap_v1/`（仅 `cap8/best.pt`、`cap16/best.pt` 纳入 Git，其余产物保持忽略）：

- `split.json`：固定受试者划分。
- `manifest.json`、`cache/EPCTLxx.json`：通道映射、源数据元信息、标签与质量统计。
- `cache/EPCTLxx.npy`：共享波形缓存。
- `cap8/best.pt`、`cap16/best.pt`：分别训练的最佳权重。
- 各模型目录下 `history.json`、`report.json`、`test_predictions.csv`、`input_contract.json`。
- `comparison.json`：两套模型完成后的指标汇总。

所有权重都标记 `deployment_ready=false`。训练完成不代表上线完成，不会自动将旧系统的频谱分类切换成新模型。

## 测试

以下命令在仓库根目录运行。`test_train_sleep_waveform_models.py` 检查电极别名与单位、标注时间、受试者独立划分、所选通道重参考和预处理质量门控；`test_training_e2e.py` 使用合成数据检查两套模型的训练、保存和测试划分。两者不需要原始 EDF，不会改写现有训练权重，也不代表实机准确率验证。

```powershell
.\terry\script\.venv\Scripts\python.exe -m pytest terry/script/test_train_sleep_waveform_models.py terry/script/test_training_e2e.py -q
```

若训练环境和 `backEnd/requirements-waveform-live.txt` 的实时依赖已经安装，完整后端测试还需要下列已在 `backEnd/pyproject.toml` 声明的离线依赖。本机补齐与验证命令如下：

```powershell
.\terry\script\.venv\Scripts\python.exe -m pip install soundfile seaborn statsmodels pyarrow
$env:PYTHONPATH = "$PWD\terry\backEnd\src;$PWD\terry\backEnd;$env:PYTHONPATH"
.\terry\script\.venv\Scripts\python.exe -m pytest terry/backEnd/tests -q -rs
```

这不是新电脑的完整安装清单；完整后端依赖以 `backEnd/pyproject.toml` 为准。Windows 无符号链接创建权限时，相关文件安全测试会明确跳过，需在具备权限的环境补验，不能当成通过。
