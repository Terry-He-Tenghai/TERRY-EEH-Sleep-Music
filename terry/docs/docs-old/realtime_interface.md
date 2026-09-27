# 连续EEG与音乐控制接口 v1

## 模块边界

系统只规定数据契约，不绑定串口、蓝牙、Socket或消息队列：

`嵌入式采集端 → EegChunk → RealtimeSession → StateUpdate → MusicController`

采集端负责把硬件协议转换为`EegChunk`。模型端每累计一个新的3秒步长，使用最近
6秒信号生成一个`RealtimeOutput`。一个输入数据块可能返回零个、一个或多个输出。

## 输入：EegChunk

- `timestamp_s`：数据块首样本的连续时间戳，秒。
- `sample_rate_hz`：v1固定为250 Hz。
- `channel_names`：16个通道名，可任意顺序；`T3/T4`自动映射到`T7/T8`。
- `samples`：`numpy.ndarray`，形状为`(16, n_samples)`。
- `unit`：`V`或`uV`。
- `session_id`：可选；提供时必须与会话一致。

数据块之间不允许重叠或跳样。时间不连续时接口抛出异常，不使用插值静默修复。

## 输出：RealtimeOutput

`state`字段：

- `schema_version`：当前为`1.0`。
- `session_id`
- `window_end_s`：相对于会话第一块数据的窗口结束时间。
- `signal_quality`：有效通道比例，范围0–1。
- `status`：
  - `warming_up`：不足三个特征窗口，过去1分钟斜率尚不可计算；
  - `ok`：质量和特征有效，概率字段可用；
  - `signal_invalid`：有效通道比例低于75%。
- `baseline_ready`：首5分钟稳健解释基线是否冻结。
- `n2_within_5m_probability`：研究模型估计值；不是已校准的临床概率。
- `aasm_state_probabilities`：W/N1/N2代理概率。
- `interpretable_features`：beta、alpha、theta、alpha/theta斜率及基线Z分数。

`music`字段：

- `action`：`none`、`hold`、`generate`、`play`、`crossfade`、`overlay`、
  `fade_out`或`stop`。
- `parameters`：与具体生成器约定的参数字典。
- `reason`：本次决策原因。

默认`NoOpMusicController`始终返回`none`。

## 自定义音乐适配器

```python
from anphy_sleep import MusicCommand, StateUpdate


class ExternalMusicAdapter:
    def update(self, state: StateUpdate) -> MusicCommand:
        # 当前仅示例接口。真实策略必须经过独立实验验证后再启用。
        return MusicCommand(
            action="none",
            parameters={},
            reason="external music API is not configured",
        )
```

创建会话时注入：

```python
session = RealtimeSession(
    config,
    prediction_model_path,
    state_model_path,
    music_controller=ExternalMusicAdapter(),
)
```

音乐接口不应直接接收原始EEG，也不应修改滤波、特征或模型状态。外部API超时不得
阻塞采集线程，正式接入时应在适配器外增加异步队列。

## 实时状态

- 第6秒产生首个`warming_up`窗口。
- 第12秒起通常可以产生首个未来N2概率。
- 累积过去30秒有效特征后开始输出W/N1/N2状态概率，之后每3秒滚动更新。
- 第300秒完成稳健基线后，`baseline_ready=true`并开始输出基线Z分数。
- 信号无效时不推理，音乐控制器收到`signal_invalid`并默认无操作。

## 当前限制

1. 训练数据来自健康成人且按未来稳定N2对齐，真实连续场景尚未校准。
2. 实时端没有ANPHY伪迹矩阵，信号质量定义与离线训练存在差异。
3. 当前概率不得用于临床诊断或无人监督的刺激控制。
4. 音乐策略为预留接口，项目中没有实现或验证任何干预规则。
