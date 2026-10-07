# 03｜训练、模型契约与当前推理

更新：2026-10-07。返回[主文档](../系统架构与功能.md)。

## 1. LIVE与历史模型任务分离

当前LIVE使用1D卷积神经网络（CNN）判断最近30秒波形属于W/N1/N2；不预测未来进入N2时间。`src/anphy_sleep`中的历史任务包括特征LogisticRegression当前分期、未来5分钟稳定N2风险、跨受试者验证等；DEMO model沿用这套模型。代码同时存在不意味着LIVE同时运行二者。

显式showcase按脚本生成阶段及分数，不参与准确率评价；新版本允许其触发ACE演示生成，界面应保留来源标记。

## 2. 权重及版本隔离

`waveform_classifier.py`校验通道名称/顺序、classes、pipeline、architecture、state_dict严格形状，并在CPU eval/inference_mode运行；缺失或不匹配时阻断，不悄悄回退。

- `model_root: ../results/waveform_cap_v1`：cap8/cap16，契约 `cap-waveform-v1`，完整16路质量合格。
- `frontal_model_root: ../results/waveform_frontal_v1`：cap2 Fp1/Fp2，cap4加F3/F4，cap6再加F7/F8，契约 `cap-waveform-frontal-v1`，所选电极质量合格。
- `subset_model_root: ../results/waveform_subset_v1`：旧C3/C4等组合留存，当前页面不选它，不能只改名变成新额区权重。

路径相对config.waveform.yaml所在目录解析。`training_code()/frontal_training_code()`加载 `terry/script` 契约代码，因此迁移不能只复制best.pt而省略训练入口/依赖模块。预检脚本加载五种当前模型；真正会话按选择加载一种，并非每次6秒重新加载。

## 3. 输入契约

所有会话物理捕获16路；分类器按明确名称选择要求电极；250Hz、40秒；50Hz陷波＋0.5–35Hz因果带通；舍弃前10秒滤波启动；在所选组上逐采样平均参考，再除100µV。训练从EDF有抗混叠重采样，实时仅接受250Hz而不任意在线改采样率。

三类softmax分数和为1，但未做概率后校准；当前记录 `hardware_validated: false`、`probabilities_calibrated: false`，权重研究性标记不能解释为部署/临床就绪。

## 4. 离线准备与训练

`train_sleep_waveform_models.py`定义原CAP8/16、EDF别名/单位/标签解析、质量预处理、受试者划分、CNN、指标；`train_sleep_subset_models.py`提供独立所选电极缓存/训练/共同窗口评估；`train_sleep_frontal_models.py`隔离复用subset核心并替换为额区契约，旧组合常量不覆盖。

来源为人工30秒TXT标签及EDF，N3/REM/R/L不改标成N2；EPCTL实际起始时间保留，按目标电极名而非EDF前N行取数据。训练数据只读，缓存和权重独立输出。28人使用固定16训练/6验证/6测试，验证F1选择权重、早停；报告分类计数、每类召回、混淆矩阵、宏F1、准确率及概率误差。少通道各自合格样本与共同合格测试窗口应分开比较。新增窗口接受范围和更少电极不能直接套用原准确率。

既有离线记录：额区cap2准确率81.66%/宏F1 0.7434，cap4为80.70%/0.7450，cap6为78.55%/0.7229；这些是2026-10-04训练报告记录，不是本轮新实验，更不是设备准确率。完整指标/训练细节见 `../../eeg-frontal-model-integration-2026-10-04.md` 和本地报告。原8/16与额区样本不同，不能只按总准确率排名。

## 5. 运行门控与时间

首次完整缓冲通常约42秒，随后6秒更新。当前配置确认次数1和最高分数门槛0.55；不足门槛可显示未确认分数，但不能授权分类驱动生成。质量合格、来源、会话、分类状态、新鲜度等需分别满足。

音乐调度器独立平滑与最短驻留，不把最高类别每次立即映射成换曲。“连续两次有效N2自动结束”由报告观察/ACE状态另行计数；该计数不是训练分期确认，也不验证60秒独立睡眠。

`classification_ms`从update开始计时，包含预处理、模型和报告Welch功率；远端队列/推理时延未被它测量。频带功率是辅助数字证据，不用于修改CNN权重或阈值分类。

## 6. 旧特征与未来风险的保留边界

`preprocess.py/io.py/features.py`对数据做通道规范、滤波、频谱和趋势等；`modeling.py/staging.py/transition_prediction.py`开展受试者独立的预测/分期评估；`streaming.py/inference.py`实现老特征模型与基线推理。未来风险需要事后人工N2定义构造标签，不能把当前N2 softmax当未来五分钟发生概率。

旧 `.joblib`依赖scikit-learn序列化版本（项目声明1.7.2），也要核对可编辑安装指向当前仓库，避免导入别处旧包。

## 7. 验证和限制

EDF离线/实时回放脚本证明数值契约一致，不证明脑电帽域适配；测试可注入predictor，只证明处理/门控行为。没有同步人工分期的现场波形不能直接充当监督真值。需要核查现场接线、参考、增益、幅度、伪迹及独立设备数据，再讨论更短窗口、概率校准或N3/REM扩展。