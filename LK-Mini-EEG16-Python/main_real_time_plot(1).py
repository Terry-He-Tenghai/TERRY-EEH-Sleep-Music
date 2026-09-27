import logging
import os
import time
import numpy as np
import pandas as pd
from datetime import datetime
import pyqtgraph as pg
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
from pyqtgraph.Qt import QtWidgets, QtCore
from eeg_filter import EegFilter

# 导入 QFileDialog（PyQt5 已通过 pyqtgraph 间接导入）
from PyQt5.QtWidgets import QFileDialog, QMessageBox


class Graph:
    def __init__(self, board_shim, sample_rate=250):
        self.board_id = board_shim.get_board_id()
        self.board_shim = board_shim
        self.exg_channels = BoardShim.get_exg_channels(self.board_id)
        self.sample_rate = sample_rate
        self.update_speed_ms = 50
        self.window_size = 3
        self.num_points = self.window_size * self.sample_rate

        # 显示缓存：存储滤波后的数据（每个通道）
        self.display_buffer = {ch: [] for ch in self.exg_channels}

        # ---- 保存原始数据的列表（用于导出） ----
        self.all_raw_data = []

        # ---- 为每个通道创建独立的滤波器实例 ----
        self.filters = {}
        for ch in self.exg_channels:
            self.filters[ch] = EegFilter()   # 可根据需要改为 EmgFilter

        # 清空 BrainFlow 缓冲区，丢弃开始前的旧数据
        self.board_shim.get_board_data()

        # 创建 Qt 应用和主窗口
        self.app = QtWidgets.QApplication.instance()  # 使用已有实例，避免重复创建
        if self.app is None:
            self.app = QtWidgets.QApplication([])
        self.win = pg.GraphicsLayoutWidget(title='BrainFlow Plot', size=(800, 600), show=True)
        # ---- 重写关闭事件 ----
        self.win.closeEvent = self.close_event

        self._init_timeseries()

        # 定时器
        timer = QtCore.QTimer()
        timer.timeout.connect(self.update)
        timer.start(self.update_speed_ms)

        # ---- 标记是否已导出，防止重复 ----
        self.exported = False

        # 进入主循环
        QtWidgets.QApplication.instance().exec()

    def _init_timeseries(self):
        self.plots = []
        self.curves = []
        for i in range(len(self.exg_channels)):
            p = self.win.addPlot(row=i, col=0)
            p.showAxis('left', False)
            p.setMenuEnabled('left', False)
            p.showAxis('bottom', False)
            p.setMenuEnabled('bottom', False)
            if i == 0:
                p.setTitle('TimeSeries Plot')
            self.plots.append(p)
            curve = p.plot()
            self.curves.append(curve)

    def update(self):
        # 读取新增原始数据
        data = self.board_shim.get_board_data()
        if data.shape[1] <= 0:
            return

        # ---- 保存原始数据段（用于导出） ----
        self.all_raw_data.append(data)

        # 对每个通道进行滤波并更新显示缓存
        for idx, ch in enumerate(self.exg_channels):
            raw_segment = data[ch].tolist()
            if not raw_segment:
                continue

            # 使用状态保持的滤波器处理
            filtered_segment = self.filters[ch].process_samples(self.sample_rate, raw_segment)
            self.display_buffer[ch].extend(filtered_segment)

            # 截断至窗口长度
            if len(self.display_buffer[ch]) > self.num_points:
                self.display_buffer[ch] = self.display_buffer[ch][-self.num_points:]

            # 更新曲线
            self.curves[idx].setData(self.display_buffer[ch])

        self.app.processEvents()

    def close_event(self, event):
        """窗口关闭事件：导出数据后继续关闭"""
        if not self.exported and self.all_raw_data:
            self.export_data()
        event.accept()

    def export_data(self):
        """导出原始数据为 CSV，弹出保存对话框，列顺序：Time_s, Ch1_uV, Ch2_uV,..."""
        if not self.all_raw_data:
            QMessageBox.information(None, "提示", "没有数据可导出！")
            return

        # 拼接所有原始数据段 (通道数 × 总样本数)
        full_data = np.concatenate(self.all_raw_data, axis=1)

        # 获取 EEG 通道数据（与 self.exg_channels 一致）
        eeg_channels = self.exg_channels
        eeg_data_uv = full_data[eeg_channels, :]  # 形状: (通道数, 样本数)

        # 构建 DataFrame，列名 Ch1_uV, Ch2_uV, ...
        columns = [f'Ch{i + 1}_uV' for i in range(len(eeg_channels))]
        df = pd.DataFrame(eeg_data_uv.T, columns=columns)

        # 添加时间列（秒）作为第一列
        total_samples = df.shape[0]
        df.insert(0, 'Time_s', np.arange(total_samples) / self.sample_rate)

        # 生成默认文件名
        default_name = f"eeg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.sample_rate}hz.csv"

        # 设置默认保存路径为当前目录下的 data/ 文件夹（若不存在则使用当前目录）
        default_dir = os.path.join(os.getcwd(), 'data')
        if not os.path.exists(default_dir):
            default_dir = os.getcwd()
        default_path = os.path.join(default_dir, default_name)

        # 弹出保存对话框
        filepath, _ = QFileDialog.getSaveFileName(
            None, "保存CSV", default_path, "CSV文件 (*.csv);;所有文件 (*)"
        )
        if not filepath:
            return  # 用户取消

        try:
            df.to_csv(filepath, index=False)
            QMessageBox.information(None, "成功", f"保存到: {filepath}\n采样点: {total_samples}")
            self.exported = True
        except Exception as e:
            QMessageBox.critical(None, "错误", f"保存失败: {e}")


# ---------------------------------------------------------
# 通道配置命令生成（16通道支持）
# ---------------------------------------------------------
def build_channel_config_cmd(channel_index, gain):
    if channel_index < 8:
        ch = str(channel_index + 1)
    else:
        ch = "QWERTYUI"[channel_index - 8]

    gain_map = {1: 0, 2: 1, 4: 2, 6: 3, 8: 4, 12: 5, 24: 6}
    gain_val = gain_map.get(gain, 6)
    params = f"{0}{gain_val}{0}{1}{1}{0}"
    return f"x{ch}{params}X"

# ---------------------------------------------------------
# 生成用于配置单个通道阻抗测量的命令字符串
# ---------------------------------------------------------
def build_impedance_cmd(channel_index, p_chan=1, n_chan=0):
    """
    生成用于配置单个通道阻抗测量的命令字符串
    :param channel_index: 0-based 通道索引 (0~15)
    :param p_chan: 是否在 P 输入施加测试信号 (0/1)
    :param n_chan: 是否在 N 输入施加测试信号 (0/1)
    :return: 命令字符串，如 "z410Z"
    """
    if channel_index < 8:
        ch = str(channel_index + 1)
    else:
        ch = "QWERTYUI"[channel_index - 8]
    # 确保 p_chan 和 n_chan 为 0 或 1
    p = int(bool(p_chan))
    n = int(bool(n_chan))
    return f"z{ch}{p}{n}Z"

def main():
    BoardShim.enable_dev_board_logger()
    logging.basicConfig(level=logging.DEBUG)
    params = BrainFlowInputParams()
    params.ip_address = '192.168.4.1'
    params.ip_port = 12345
    params.timeout = 3

    board_shim = BoardShim(BoardIds.CYTON_DAISY_WIFI_BOARD.value, params)

    try:
        board_shim.prepare_session()

        sample_rate = 250
        rate_cmd_map = {250: '~6', 500: '~5', 1000: '~4'}
        rate_cmd = rate_cmd_map.get(sample_rate)
        board_shim.config_board(rate_cmd)
        time.sleep(0.5)

        pga_cmd = ""
        for ch in range(16):
            pga_cmd += build_channel_config_cmd(ch, 6)
        board_shim.config_board(pga_cmd)
        time.sleep(0.5)

        # 发送阻抗配置命令
        imp_cmd = build_impedance_cmd(0, p_chan=0, n_chan=1)  # 通道索引 0 -> 通道1
        board_shim.config_board(imp_cmd)
        time.sleep(0.5)

        board_shim.start_stream()

        Graph(board_shim, sample_rate)

    except BaseException:
        logging.warning('Exception', exc_info=True)
    finally:
        logging.info('End')
        if board_shim.is_prepared():
            logging.info('Releasing session')
            board_shim.release_session()


if __name__ == '__main__':
    main()