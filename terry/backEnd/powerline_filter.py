"""
增强型工频陷波滤波器 - 专门用于睡眠 EEG 采集
针对 50Hz 工频干扰进行多级抑制
"""
import numpy as np
from scipy.signal import iirnotch, butter, sosfilt, tf2sos


class PowerlineNoiseFilter:
    """
    多级工频干扰抑制器
    - 50Hz 基频陷波（Q=30，深度陷波）
    - 100Hz 二次谐波陷波
    - 150Hz 三次谐波陷波
    - 带通滤波器 (0.5-35Hz) 保留睡眠相关频段
    """
    
    def __init__(self, sample_rate_hz: int, channels: int = 16):
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        
        # 设计多个陷波滤波器
        notch_freqs = [50, 100, 150]  # 基频和谐波
        self.notch_sos = []
        
        for freq in notch_freqs:
            if freq < sample_rate_hz / 2:  # 避免超过奈奎斯特频率
                # Q=30 提供非常窄但深的陷波
                b, a = iirnotch(freq, Q=30, fs=sample_rate_hz)
                # 直接转换为 SOS 格式
                sos = tf2sos(b, a)
                self.notch_sos.append(sos)
        
        # 带通滤波器：0.5-35 Hz (睡眠 EEG 有效频段)
        # 0.5 Hz 高通：去除基线漂移
        # 35 Hz 低通：保留 delta/theta/alpha/beta，去除高频噪声和肌电
        sos_high = butter(4, 0.5, btype='high', fs=sample_rate_hz, output='sos')
        sos_low = butter(6, 35, btype='low', fs=sample_rate_hz, output='sos')
        
        # 组合所有滤波器
        self.all_sos = [sos_high, sos_low] + self.notch_sos
        
        # 为每个通道初始化状态
        self.states = []
        for sos in self.all_sos:
            self.states.append(np.zeros((sos.shape[0], channels, 2)))
    
    def process(self, samples_uv: np.ndarray) -> np.ndarray:
        """
        处理 EEG 数据块
        
        参数:
            samples_uv: shape (channels, samples) 的 EEG 数据（微伏）
        
        返回:
            filtered: 滤波后的数据，相同形状
        """
        samples = np.asarray(samples_uv, dtype=float)
        if samples.ndim != 2 or samples.shape[0] != self.channels:
            raise ValueError(f"Expected shape ({self.channels}, N), got {samples.shape}")
        
        if samples.shape[1] == 0:
            return samples.copy()
        
        output = np.empty_like(samples)
        
        for ch in range(self.channels):
            values = samples[ch]
            
            # 检查有效性
            if not np.isfinite(values).all():
                # 重置该通道的所有滤波器状态
                for state in self.states:
                    state[:, ch, :] = 0
                output[ch] = 0  # 输出静默
                continue
            
            # 依次通过所有滤波器
            for sos, state in zip(self.all_sos, self.states):
                values, state[:, ch, :] = sosfilt(sos, values, zi=state[:, ch, :])
            
            output[ch] = values
        
        return output
    
    def reset_channel(self, channel: int):
        """重置指定通道的滤波器状态"""
        if 0 <= channel < self.channels:
            for state in self.states:
                state[:, channel, :] = 0
    
    def reset_all(self):
        """重置所有通道的滤波器状态"""
        for state in self.states:
            state.fill(0)


def estimate_powerline_noise(samples_uv: np.ndarray, sample_rate_hz: int, 
                             powerline_freq: float = 50.0) -> float:
    """
    估算 50Hz 工频干扰的强度
    
    返回:
        noise_ratio: 工频能量占总能量的比例 (0-1)
    """
    if samples_uv.shape[1] < 100:
        return 0.0
    
    # 计算每个通道的功率谱密度
    from scipy.signal import welch
    
    noise_ratios = []
    for ch in range(samples_uv.shape[0]):
        signal = samples_uv[ch]
        if not np.isfinite(signal).all():
            continue
        
        freqs, psd = welch(signal, fs=sample_rate_hz, nperseg=min(256, len(signal)))
        
        # 找到 50Hz 附近的能量
        mask_50hz = (freqs >= 48) & (freqs <= 52)
        mask_total = (freqs >= 1) & (freqs <= 40)  # 有效 EEG 频段
        
        energy_50hz = np.sum(psd[mask_50hz])
        energy_total = np.sum(psd[mask_total])
        
        if energy_total > 0:
            noise_ratios.append(energy_50hz / energy_total)
    
    return np.mean(noise_ratios) if noise_ratios else 0.0


if __name__ == "__main__":
    # 测试代码
    print("增强型工频陷波滤波器已加载")
    print("- 50Hz/100Hz/150Hz 多级陷波")
    print("- 0.5-35Hz 带通（保留睡眠频段）")
    print("- 支持实时状态保持")
