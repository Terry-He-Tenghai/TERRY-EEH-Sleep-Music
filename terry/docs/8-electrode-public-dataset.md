# 八电极公开睡眠数据集核查

核查时间：2026-09-27。此前讨论的拟用八电极为物理 1、2、9–14，对应
`Fp1, Fp2, F7, F8, F3, F4, T7, T8`；实际 `config.hardware.yaml` 仍配置
另一套 16 通道，必须在设备侧确认后才能作为实时输入合同。现在选数据集时允许
训练使用不同位置的至多八路 EEG。这里的公开数据可用于研究性模型训练，
不能替代目标硬件和目标人群的独立验证。

## 低通道候选（按用途）

| 数据集 | 可用 EEG 输入 | 睡眠标签及规模 | 建议用途与限制 |
| --- | --- | --- | --- |
| [BOAS / Bitbrain](https://openneuro.org/datasets/ds005555) | 原生头带 2 路，约 AF7/AF8；同步 PSG 可取 F3/F4/C3/C4/O1/O2 中最多 6 路 | 128 晚、108 人；3 位 PSG 专家评分形成共识（分歧时第 4 人裁决），W/N1/N2/N3/REM | 首选低通道训练基线；以 PSG 的 `stage_hum` 为标签，不把 `stage_ai` 当真值；按唯一参与者而非夜晚划分；头带位置和参考方式与本设备不同 |
| [ISRUC-Sleep](https://sleeptight.isr.uc.pt/) | PSG 含 EEG；可在核查每份文件实际导联后选择不超过 6 路，不能假定所有记录都具有相同六导联 | 官方列出 100 人一晚、8 人两晚、10 名健康人一晚；两位专家评分 | 适合跨数据集验证；[下载页](https://sleeptight.isr.uc.pt/?page_id=48)称供研究使用，未确认产品训练/商业授权，使用前应向维护方核实；[提取通道页](https://sleeptight.isr.uc.pt/?page_id=76)提示末尾 30 epoch 与 hypnogram 长度不同，需对齐 |
| [ANPHY-Sleep](https://osf.io/r26fh/) | 高密度原始 EEG 中抽取拟用的 8 路，不是原生八路设备 | 30 秒 W/N1/N2/N3/R；已检查一名受试者文件头与标注 | 与拟用电极位置重合最好，但只有少量受试者，且数据量大；详见下文 |

BOAS 的[官方 README](https://raw.githubusercontent.com/OpenNeuroDatasets/ds005555/master/README)
说明头带电极约 AF7/AF8、PSG 的六个 EEG 通道和标签形成方法；
[元数据](https://raw.githubusercontent.com/OpenNeuroDatasets/ds005555/master/dataset_description.json)
标记 CC0。ISRUC 官网未在上述页面逐一列出 EDF 内 EEG 导联名，其具体可用通道
仍需下载样本后检查，不将文献中常见的六路配置当成所有记录的保证。
Sleep-EDF Expanded 常被用作两路基线，但本次 PhysioNet 官方页面不可达，
通道、许可和标签格式待核实，暂不列入已验证训练来源。

推荐先用 BOAS 头带两路做研究基线，随后对 BOAS PSG 六路与 ANPHY 所需八路
分别评估跨人泛化；若要上线现有设备，最终必须选择真实接入的电极、参考方式
和一致的预处理，并采集本设备有标签的数据验证或适配。通道数不大于八，
不意味着其他帽位模型可以直接用于本设备。

### BOAS 六路 PSG 下载状态

GitHub 仓库已克隆到 `backEnd/data/raw/ds005555`（约 12 MB），包含 128 晚的
`channels.tsv` 和 `events.tsv` 人工标签；EDF 仅为 git-annex **断开的链接**，
尚无可读取的波形。`sub-1` 的六路 `PSG_F3/F4/C3/C4/O1/O2` 均在通道表中，
采样率标为 256 Hz。OpenNeuro API 返回该晚 PSG EDF 大小为 154652160 字节，
但本机访问官方 S3 对象存储超时，2026-09-27 未能下载任何 EDF。

网络恢复后从项目 `terry/backEnd` 目录运行：

```bash
python3 scripts/download_boas_psg.py --subject sub-1
python3 scripts/download_boas_psg.py
```

下载器从官方 API 查询文件 URL，以仓库 annex 键的大小和 SHA-256 验证完整性，
保留 `.part` 文件用于续传；只下载通道齐全并带 `stage_hum` 的 PSG EDF，
输出在 `data/raw/boas-psg/`，对应人工标签与通道表保留在克隆目录。
整个 EDF 含 PSG 其他生理信号；训练时再只抽取这六路，不可认为下载文件仅有六路。

## 首选：ANPHY-Sleep

- 官方项目：https://osf.io/r26fh/
- 官方说明：https://osf.io/download/jk5wz/
- 官方电极位置：https://osf.io/download/6mhje/
- OSF 项目 API：https://api.osf.io/v2/nodes/r26fh/
- 项目 API 所列许可证：CC0 1.0 Universal。公开下载不等于可以跳过隐私、伦理和产品合规审查。

官方 Readme 说明受试者数据为 EDF 脑电和 TXT 睡眠分期标注，含 W、N1、N2、N3、R
以及灯光状态 L。电极位置表含 `Fp1/Fp2/F3/F4/F7/F8/T3/T4`，其中历史
`T3/T4` 分别映射为 `T7/T8`。对 `EPCTL11.zip` 使用 HTTP Range 仅读取 ZIP
目录、EDF 压缩流开头及 TXT 压缩成员，实测 EDF 为 94 通道，目标八路均存在，
标注为 30 秒一条的 `阶段\t起点秒\t时长秒`，例如 `N1\t870\t30`。
此验证只覆盖 EPCTL11 的文件头和标签，不等于全体受试者质量检查，也未下载 EEG
波形主体、运行训练或测得任何模型性能。EDF 中这些通道的单位标为 `uV`。

OSF 文件目录目前列出 28 个受试者压缩包（缺 EPCTL08），单包大约 2.5–4 GB，
批量下载需预留数十 GB 网络和更多解压空间。项目已有支持 MD5 校验和续传的脚本：

```bash
cd /Users/tenghai/Desktop/Terry_EEG_Project/terry/backEnd
uv run python scripts/download_anphy.py --list
uv run python scripts/download_anphy.py --subject EPCTL11 --output data/raw
```

## 为什么现在不能直接部署

1. `results/` 只有旧模型和汇总输出，没有原始 EDF 或逐窗特征；无法据此重训。
2. `config.hardware.yaml` 当前是另一套 16 电极布局，不能当作八电极实时合同。
3. 旧特征含 posterior alpha、central theta/sigma 等；只保留前额和双颞后，
   必须重新设计离线和实时两侧**同名同算法**的特征，明确参考电极及实际滤波带宽。
   现有 5 Hz 高通会抑制 delta 和部分 theta，尤其需要与训练时一致并验证。
4. 训练集需按受试者划分，报告 N1 少数类召回、混淆矩阵、balanced accuracy 和
   校准情况；单人样本仅用于流程验证，不可作为泛化性能依据。
5. 模型包须绑定八通道顺序、采样率、参考方式、滤波和特征版本，实时加载时强校验；
   完成前应保留 `reduced_montage_requires_retrained_model` 阻断，不能用 16 通道模型
   推断八通道数据。

建议先下载 EPCTL11 并完成波形/标注/特征一致性检查，然后批量下载、按受试者验证、
选择模型，最后用真实帽子录制的独立数据做域迁移和音乐触发联调。公开数据的
参考方式、设备噪声和实验人群与产品设备不一定相同；研究性能不可直接当作真实
设备效果或医学诊断结论。
