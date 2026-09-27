import time
import numpy as np
import pandas as pd
from datetime import datetime
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds

# ---------------------------------------------------------
# 通道配置命令生成 (16通道支持)
# gain: 1 2 4 6 8 12 24
# ---------------------------------------------------------
def build_channel_config_cmd(channel_index,gain):
    """
    生成单个通道的配置命令字符串
    channel_index: 0-based (0~15)
    返回: "x<ch>paramsX" 字符串
    """
    # 通道号编码 (1-8: '1'-'8', 9-16: 'Q','W','E','R','T','Y','U','I')
    if channel_index < 8:
        ch = str(channel_index + 1)
    else:
        ch = "QWERTYUI"[channel_index - 8]

    # 参数映射：增益值 → GAIN_SET编码
    gain_map = {1: 0, 2: 1, 4: 2, 6: 3, 8: 4, 12: 5, 24: 6}
    gain_val = gain_map.get(gain, 6)  # 默认24倍

    # 参数顺序：POWER_DOWN, GAIN_SET, INPUT_TYPE, BIAS_SET, SRB2_SET, SRB1_SET
    # 使用默认值：POWER_DOWN=0 (ON), INPUT_TYPE=0 (NORMAL),
    # BIAS_SET=1 (包含), SRB2=1 (连接), SRB1=0 (断开)
    params = f"{0}{gain_val}{0}{1}{1}{0}"
    return f"x{ch}{params}X"

def collect_eeg_simple(ip='192.168.4.1', duration=5):
    """
    简化版本：采集 EEG 数据并保存为 CSV
    """
    print(f"连接到 {ip}...")

    # 初始化
    params = BrainFlowInputParams()
    params.ip_address = ip
    params.ip_port = 12345
    params.timeout = 3

    try:
        # 连接
        board = BoardShim(BoardIds.CYTON_DAISY_WIFI_BOARD.value, params)
        board.prepare_session()

        # 配置采样率
        sample_rate = 250
        rate_cmd_map = {250: '~6', 500: '~5', 1000: '~4'}
        rate_cmd = rate_cmd_map.get(sample_rate)
        board.config_board(rate_cmd)
        time.sleep(0.5)

        # 配置放大倍数
        pga_cmd = ""
        for ch in range(16):   # 自动适配实际检测到的通道数
            pga_cmd += build_channel_config_cmd(ch,6)
        board.config_board(pga_cmd)
        time.sleep(0.5)

        # 开始采集
        board.start_stream()

        print(f"采集数据 {duration} 秒...")

        # 等待采集结束
        time.sleep(duration)

        # 获取数据
        data = board.get_board_data()

        # 停止采集
        board.stop_stream()

        #
        board.release_session()

        if data.size == 0:
            print("未采集到数据")
            return

        # 获取 EEG 通道
        eeg_channels = BoardShim.get_eeg_channels(BoardIds.CYTON_DAISY_WIFI_BOARD.value)
        eeg_data_uv = data[eeg_channels, :]

        # 创建 DataFrame
        columns = [f'Ch{i + 1}_uV' for i in range(len(eeg_channels))]
        df = pd.DataFrame(eeg_data_uv.T, columns=columns)

        # 添加时间列
        df.insert(0, 'Time_s', np.arange(len(df)) / sample_rate)

        # 保存
        filename = f"data\eeg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{sample_rate}hz.csv"
        df.to_csv(filename, index=False)

        print(f"  数据已保存到: {filename}")
        print(f"  采样点数: {len(df)}")
        print(f"  通道数: {len(columns)}")
        print(f"  数据预览:\n{df.head()}")

    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    collect_eeg_simple(duration=5)