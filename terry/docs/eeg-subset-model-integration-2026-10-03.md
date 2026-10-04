# 2/4/6 路波形模型训练与集成

> 2026-10-04：当前页面2/4/6改为额区组合，新契约与权重目录见 `eeg-frontal-model-integration-2026-10-04.md`。本文中央组合及其离线指标保留为历史记录，不能套用到额区模型。

更新：2026-10-03。状态：2/4/6路代码集成、真实EDF训练、留出测试和EDF实时预处理回放均已完成；真实脑电帽与ACE-Step端到端验证仍未完成。不能将公开数据指标当成实机或临床效果。

## 模型及质量范围

- cap2：C3、C4。
- cap4：Fp1、Fp2、C3、C4。
- cap6：Fp1、Fp2、C3、C4、F3、F4。
- 三套新模型仅检查所选电极，按该组合计算平均参考。物理设备仍采集16路；其他电极出现平直或非有限值，不进入所选模型的质量检查和推理。
- 旧cap8/cap16权重、训练脚本和all16clean输入契约保留不变。没有提高质量阈值、插值坏电极或恢复频谱兜底。
- 分类仍为W/N1/N2，不包含N3/REM，不代表实机或临床验证。

## 实现

训练入口 `terry/script/train_sleep_subset_models.py`，契约版本 `cap-waveform-subset-v1`；不复用旧的全部16路合格缓存。从原始EDF按每套模型分别重新提取和筛选；受试者划分沿用原28人的16/6/6划分，验证集选择权重，全部训练完成后再评估留出测试及共同合格窗口。

产物目录 `terry/results/waveform_subset_v1/cap2/`、`cap4/`、`cap6/`。三份 `best.pt` 已完成训练并可由后端加载；训练缓存、历史和测试报告也已生成。仅三个best.pt文件放行Git，其余仍忽略。本轮不自动提交或推送。

## 留出测试结果

沿用原28人16/6/6受试者划分，测试集为6名受试者。三套模型共同合格测试窗口为3223个；指标来自公开数据，不代表实机效果。

- cap2：自身合格测试3365个窗口，准确率0.8107，宏平均F1 0.7518，W/N1/N2召回率0.8620/0.6062/0.8348；合格率为3371个候选中的99.82%。
- cap4：自身合格测试3228个窗口，准确率0.8346，宏平均F1 0.7691，W/N1/N2召回率0.8714/0.5717/0.8841；合格率为3371个候选中的95.76%。
- cap6：自身合格测试3223个窗口，准确率0.8328，宏平均F1 0.7550，W/N1/N2召回率0.8783/0.4789/0.9016；合格率为3371个候选中的95.61%。

在共同3223个窗口上，cap2宏平均F1为0.7478、准确率0.8048；cap4为0.7689、0.8343；cap6为0.7550、0.8328。N1仍是三套模型的主要薄弱类别，不能只看总体准确率选择模型。完整指标见各模型 `report.json` 和根目录 `comparison.json`。

后端 `waveform_classifier.py` 支持两个版本契约与独立权重目录；`config.waveform.yaml` 的 `subset_model_root` 指向新产物。模型未生成时明确阻断，不使用旧模型假装新模型。事件包含selected_channels、quality_channels、quality_scope，以及无效窗口的失败电极、原因和指标。

前端模型选项包括2/4/6/8/16及对应电极。完整16路缓冲和采集消息检查不变，独立绘图索引默认显示模型选中电极；“查看全部16路”仅控制显示，不改变模型输入。采集数、分类数和显示数分别标明。

## 当前验证

- 完整后端回归：404通过、4跳过；跳过均因Windows符号链接权限不足。
- 新旧训练契约及合成测试：31通过。
- 前端单元测试46通过；`npm run build`成功。
- 三份实际权重CPU加载通过：cap2、cap4、cap6分别使用C3/C4、Fp1/Fp2/C3/C4、Fp1/Fp2/C3/C4/F3/F4。
- EPCTL07的10个合格EDF窗口完成离线/实时预处理回放，三套模型最大概率差均为0.0；该检查只证明数值一致性，不是硬件验证。
- 三模型真实训练、测试评估和共同窗口比较已完成，结果见上文。
- 真实三模型最终权重CPU加载、EDF数值一致性回放、测试集指标：待训练完成后记录，当前不填入估计数值。
- 真实设备和ACE-Step远端闭环未验证。

## 命令

在仓库根目录使用训练虚拟环境执行：

```powershell
.\terry\script\.venv\Scripts\python.exe -u terry/script/train_sleep_subset_models.py --dataset "E:\project\test\terry\dataset" --output terry/results/waveform_subset_v1 --epochs 30 --patience 7 --batch-size 32
.\terry\script\.venv\Scripts\python.exe -m pytest terry/script/test_sleep_subset_models.py -q
```

当前入口使用CUDA训练。已有合格缓存可复用，训练摘要与设置不一致时拒绝混用；运行多个实例会争用同一缓存，应只启动一个。旧划分split.json本机存在但被Git忽略，迁移训练需提供相同划分或显式--split。

训练完成后数值回放：

```powershell
.\terry\script\.venv\Scripts\python.exe terry/script/check_subset_replay.py --edf "E:\project\test\terry\dataset\EPCTL07\EPCTL07.edf" --labels "E:\project\test\terry\dataset\EPCTL07\EPCTL07.txt" --windows 10
```

标签路径以实际TXT文件名为准；该回放只验证数值一致性，不调用远端音乐服务，不等同于网页数据集回放功能。
