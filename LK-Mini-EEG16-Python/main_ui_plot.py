# -*- coding: utf-8 -*-
"""
实时脑电/肌电信号采集与显示程序
使用 PyQt5 构建 GUI，通过 BrainFlow 连接 LK-Mini-EEG16 (适配 OpenBCI Cyton+Daisy 板通信协议) (Wi-Fi)
"""

import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QGroupBox, QCheckBox, QGridLayout,
    QSpacerItem, QSizePolicy, QFileDialog, QMessageBox
)
import pyqtgraph as pg
from pyqtgraph import PlotWidget

# 导入 BrainFlow 相关模块
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds

# 导入自定义滤波器
from eeg_filter import EegFilter      # EEG 专用滤波器 (5–50Hz 带通 + 50Hz 陷波)
from emg_filter import EmgFilter      # EMG 专用滤波器 (18Hz HP + 50Hz Comb Notch)

# -------------------------------------------------------------
# 数据采集线程（使用 get_board_data 清空缓冲区，保证数据不丢失）
# -------------------------------------------------------------
class BrainFlowWorker(QThread):
    """
    工作线程：负责从 BrainFlow 缓冲区读取数据（读取全部并清空缓冲区）
    通过 data_received 信号将新原始数据发送给主线程。
    """
    data_received = pyqtSignal(object)   # 发送 numpy 数组，形状 (通道数, 样本数)

    def __init__(self, board, eeg_channels, sample_rate=250):
        """
        初始化工作线程
        :param board: BoardShim 实例
        :param eeg_channels: EEG 通道索引列表
        :param sample_rate: 采样率 (Hz)
        """
        super().__init__()
        self.board = board
        self.eeg_channels = eeg_channels
        self.sample_rate = sample_rate
        self.running = False

    def run(self):
        """
        线程主循环：持续读取缓冲区中的全部未读数据（清空），发射信号。
        """
        self.running = True
        # 丢弃启动前可能残留的数据（确保缓冲区为空）
        self.board.get_board_data()

        while self.running:
            try:
                # 读取全部未读数据并清空缓冲区（保证数据不丢失）
                data = self.board.get_board_data()
                if data.shape[1] > 0:
                    # 提取 EEG 通道数据 (形状: 通道数 x 样本数)
                    eeg_data = data[self.eeg_channels, :]
                    # 发射信号，将数据发送给主线程
                    self.data_received.emit(eeg_data)
                else:
                    # 无新数据，短暂休眠
                    self.msleep(5)
            except Exception as e:
                print(f"数据读取错误: {e}")
                self.msleep(10)

    def stop(self):
        """安全停止线程"""
        self.running = False
        self.wait(1000)


# -------------------------------------------------------------
# 主窗口类
# -------------------------------------------------------------
class EEGMainWindow(QMainWindow):
    """
    主窗口：管理 UI、设备连接、数据接收、滤波、绘图及导出功能。
    采用增量读取方式，数据只读不消费，保留缓冲区完整性。
    """

    def __init__(self, ip='192.168.4.1'):
        """
        初始化窗口，连接设备，构建 UI，准备滤波器和缓存。
        :param ip: OpenBCI Wi-Fi 模块的 IP 地址
        """
        super().__init__()
        # ---- 设备相关 ----
        self.ip = ip
        self.board = None                  # BoardShim 对象
        self.eeg_channels = None           # EEG 通道索引列表
        self.num_channels = 0              # 有效通道数
        self.worker = None                 # 数据采集线程
        self.is_collecting = False         # 是否正在采集
        self.paused = False                # 是否暂停显示（仍采集但不更新图形）
        self._updating = False             # 防止递归更新全选状态

        # ---- 采样与显示参数 ----
        self.sample_rate = 250             # 采样率 (Hz)
        self.display_seconds = 3           # 显示窗口时长 (秒)
        self.display_length = self.sample_rate * self.display_seconds   # 窗口内样本点数

        # ---- 增益配置 ----
        self.gain = 24                     # 硬件增益 (1,2,4,6,8,12,24)

        # ---- 数据缓存 ----
        self.eeg_data_buffer = []          # 存储滤波后的 μV 数据，用于绘图 (每个通道一个列表)
        self.all_raw_data = []             # 存储原始数据（分段拼接，用于导出）
        self.channel_states = [True] * 16  # 通道显示开关

        # ---- 全局样本计数器（用于 X 轴持续滚动） ----
        self.total_samples = 0             # 累计接收到的样本总数（每个通道）

        # ---- 滤波器 ----
        self.channel_filters = []          # 每个通道一个滤波器实例
        self.signal_type = 'EEG'           # 当前信号类型：'EEG' 或 'EMG'
        self.filter_enabled = True         # 全局滤波开关

        # ---- 绘图颜色 ----
        self.channel_colors = [
            (0, 114, 189), (217, 83, 25), (237, 177, 32), (126, 47, 142),
            (119, 172, 48), (77, 190, 238), (162, 20, 47), (128, 128, 128),
            (255, 127, 0), (0, 158, 115), (214, 39, 40), (140, 86, 75),
            (44, 160, 44), (255, 152, 213), (148, 103, 189), (31, 119, 180)
        ]

        # ---- 初始化 UI ----
        self.initUI()
        # ---- 连接 BrainFlow ----
        self.connect_brainflow()
        # ---- 更新界面状态 ----
        self.update_ui_after_connect()
        # ---- 初始化滤波器 ----
        self.init_filters()

    # ---------------------------------------------------------
    # 连接 BrainFlow
    # ---------------------------------------------------------
    def connect_brainflow(self):
        """
        创建 BoardShim 实例，准备会话，获取 EEG 通道索引。
        若失败则弹出错误并退出。
        """
        try:
            params = BrainFlowInputParams()
            params.ip_address = self.ip
            params.ip_port = 12345
            params.timeout = 3
            # 创建板卡对象 (Cyton+Daisy 通过 Wi-Fi)
            self.board = BoardShim(BoardIds.CYTON_DAISY_WIFI_BOARD.value, params)
            # 准备会话（连接硬件）
            self.board.prepare_session()
            # 获取 EEG 通道索引（通常为 1-8 或 1-16）
            self.eeg_channels = BoardShim.get_eeg_channels(BoardIds.CYTON_DAISY_WIFI_BOARD.value)
            self.num_channels = len(self.eeg_channels)
            # 初始化显示缓存
            self.eeg_data_buffer = [[] for _ in range(self.num_channels)]
            print(f"成功连接 {self.ip}, 通道数 {self.num_channels}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接 BrainFlow 失败: {e}")
            sys.exit(1)

    # ---------------------------------------------------------
    # 更新 UI 状态
    # ---------------------------------------------------------
    def update_ui_after_connect(self):
        """连接成功后启用相关控件，更新状态标签"""
        self.label_conn_state.setText("连接状态: 已连接")
        self.label_conn_state.setStyleSheet("color: green; font-weight: bold;")
        self.btn_start.setEnabled(True)
        # 启用实际通道对应的复选框
        for i in range(min(16, self.num_channels)):
            self.channel_buttons[i].setEnabled(True)
            self.channel_buttons[i].setChecked(True)

        # 启用全选复选框，并设置初始状态
        self.chk_select_all.setEnabled(True)
        enabled_checks = [chk for chk in self.channel_buttons if chk.isEnabled()]
        if enabled_checks:
            all_checked = all(chk.isChecked() for chk in enabled_checks)
            self.chk_select_all.setChecked(all_checked)

        # 设置初始 Y 轴范围
        if self.num_channels > 0:
            self.graph_widget.setYRange(0, 100 * self.num_channels + 100)
        self.status_label.setText(f"就绪 | {self.num_channels}通道 | {self.sample_rate}Hz | 增益x{self.gain}")

    # ---------------------------------------------------------
    # 通道配置命令生成 (16通道支持)
    # ---------------------------------------------------------
    def build_ch_config_cmd(self, channel_index, gain, power_down=0):
        """
        生成单个通道的增益配置命令字符串 (OpenBCI 寄存器配置)
        :param channel_index: 0-based 通道索引 (0~15)
        :param gain: 增益值 (1,2,4,6,8,12,24)
        :param power_down: 0=开启通道，1=关闭通道（省电）
        :return: 命令字符串，如 "x1paramsX"
        """
        # 通道号编码：1-8 -> '1'-'8'，9-16 -> 'Q','W','E','R','T','Y','U','I'
        if channel_index < 8:
            ch = str(channel_index + 1)
        else:
            ch = "QWERTYUI"[channel_index - 8]

        # 增益映射：硬件增益值 -> GAIN_SET 编码
        gain_map = {1: 0, 2: 1, 4: 2, 6: 3, 8: 4, 12: 5, 24: 6}
        gain_val = gain_map.get(gain, 6)  # 默认 24 倍

        # 参数顺序：POWER_DOWN, GAIN_SET, INPUT_TYPE, BIAS_SET, SRB2_SET, SRB1_SET
        # 其他参数使用常用默认值：INPUT_TYPE=0 (NORMAL), BIAS_SET=1, SRB2=1, SRB1=0
        params = f"{power_down}{gain_val}{0}{1}{1}{0}"
        return f"x{ch}{params}X"

    # 发送通道配置指令
    def send_ch_config_cmd(self):
        """
        为所有通道发送增益配置命令，并依据复选框状态开启/关闭通道。
        :return: 成功返回 True，否则 False
        """
        if not self.board:
            return False

        cmd_str = ""
        for ch in range(self.num_channels):
            # 判断该通道的复选框是否存在且被勾选（默认勾选）
            if ch < len(self.channel_buttons):
                checked = self.channel_buttons[ch].isChecked()
            else:
                checked = True
            power_down = 0 if checked else 1
            cmd_str += self.build_ch_config_cmd(ch, self.gain, power_down)

        if cmd_str:
            try:
                self.board.config_board(cmd_str)
                print(f"已发送通道增益配置: {cmd_str}")
                return True
            except Exception as e:
                print(f"通道配置失败: {e}")
                return False
        return False

    # ---------------------------------------------------------
    # 初始化滤波器
    # ---------------------------------------------------------
    def init_filters(self):
        """
        根据当前 signal_type 和采样率为每个通道创建独立的滤波器实例。
        滤波器状态独立，保证连续滤波。
        """
        self.channel_filters = []
        if self.num_channels == 0:
            return

        # 选择滤波器类
        if self.signal_type == 'EEG':
            FilterClass = EegFilter
        elif self.signal_type == 'EMG':
            FilterClass = EmgFilter
        else:
            FilterClass = EegFilter

        # 为每个通道创建一个滤波器实例（内部状态独立）
        for _ in range(self.num_channels):
            self.channel_filters.append(FilterClass())

        print(f"初始化 {len(self.channel_filters)} 个 {self.signal_type} 滤波器 (采样率 {self.sample_rate}Hz)")

    # ---------------------------------------------------------
    # UI 构建
    # ---------------------------------------------------------
    def initUI(self):
        """构建主界面布局和控件"""
        self.setWindowTitle('LK-Mini-EEG16 示例软件')
        self.setGeometry(100, 100, 1400, 800)

        # 左侧控制面板 (垂直布局)
        left_vbox = QVBoxLayout()
        left_vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        left_vbox.setSpacing(15)

        # ---- 状态信息 ----
        self.label_conn_state = QLabel("连接状态: 连接中...")
        self.label_conn_state.setStyleSheet("color: orange; font-weight: bold;")
        self.label_ip = QLabel(f"IP: {self.ip}")

        # ---- 配置组 ----
        group_config = QGroupBox("信号与滤波配置")
        layout_config = QVBoxLayout()

        # 采样率下拉框
        hbox_rate = QHBoxLayout()
        hbox_rate.addWidget(QLabel("采样率:"))
        self.sample_combo = QComboBox()
        self.sample_combo.addItems(["250Hz", "500Hz", "1000Hz"])
        self.sample_combo.setCurrentText("250Hz")
        hbox_rate.addWidget(self.sample_combo)
        layout_config.addLayout(hbox_rate)

        # 增益下拉框
        hbox_gain = QHBoxLayout()
        hbox_gain.addWidget(QLabel("增益:"))
        self.gain_combo = QComboBox()
        self.gain_combo.addItems(["1", "2", "4", "6", "8", "12", "24"])
        self.gain_combo.setCurrentText("24")
        hbox_gain.addWidget(self.gain_combo)
        layout_config.addLayout(hbox_gain)

        # 信号类型下拉框
        hbox_type = QHBoxLayout()
        hbox_type.addWidget(QLabel("信号类型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["EEG", "EMG"])
        self.type_combo.setCurrentText("EEG")
        self.type_combo.currentTextChanged.connect(self.on_signal_type_changed)
        hbox_type.addWidget(self.type_combo)
        layout_config.addLayout(hbox_type)

        # 滤波启用复选框
        self.chk_filter_enable = QCheckBox("启用滤波 (高通+低通+陷波)")
        self.chk_filter_enable.setChecked(True)
        self.chk_filter_enable.stateChanged.connect(self.on_filter_enable_changed)
        layout_config.addWidget(self.chk_filter_enable)
        group_config.setLayout(layout_config)

        # ---- 控制按钮 ----
        self.btn_start = QPushButton('开始采集')
        self.btn_start.clicked.connect(self.toggle_collection)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")

        self.btn_pause = QPushButton('暂停显示')
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setEnabled(False)

        self.btn_auto_scale = QPushButton('自动缩放')
        self.btn_auto_scale.clicked.connect(self.auto_scale)

        self.btn_export_csv = QPushButton('导出数据')
        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_csv.setEnabled(False)

        # ---- 显示时长选择 ----
        hbox_display = QHBoxLayout()
        hbox_display.addWidget(QLabel("显示时长:"))
        self.display_combo = QComboBox()
        self.display_combo.addItems(["1秒", "3秒", "5秒", "10秒"])
        self.display_combo.setCurrentText("3秒")
        self.display_combo.currentTextChanged.connect(self.on_display_changed)
        hbox_display.addWidget(self.display_combo)

        # ---- 通道选择 (16个复选框) ----
        group_channel = QGroupBox("通道选择")
        layout_channel = QVBoxLayout()
        layout_channel.setContentsMargins(10, 10, 10, 10)

        # 全选复选框
        self.chk_select_all = QCheckBox("全选")
        self.chk_select_all.setChecked(True)
        self.chk_select_all.setEnabled(False)  # 连接后启用
        self.chk_select_all.stateChanged.connect(self.on_select_all)
        layout_channel.addWidget(self.chk_select_all)

        # 通道网格
        grid_channel = QGridLayout()
        self.channel_buttons = []
        for i in range(16):
            row = i // 4
            col = i % 4
            chk = QCheckBox(f"CH{i + 1}")
            chk.setChecked(True)
            chk.setEnabled(False)
            chk.toggled.connect(lambda state, idx=i: self.toggle_channel(state, idx))
            grid_channel.addWidget(chk, row, col)
            self.channel_buttons.append(chk)
        grid_channel.setContentsMargins(0, 0, 0, 0)
        layout_channel.addLayout(grid_channel)

        group_channel.setLayout(layout_channel)

        # 将左侧所有控件添加到垂直布局
        left_vbox.addWidget(self.label_conn_state)
        left_vbox.addWidget(self.label_ip)
        left_vbox.addWidget(group_config)
        left_vbox.addWidget(group_channel)
        left_vbox.addLayout(hbox_display)
        left_vbox.addWidget(self.btn_start)
        left_vbox.addWidget(self.btn_pause)
        left_vbox.addWidget(self.btn_auto_scale)
        left_vbox.addWidget(self.btn_export_csv)
        left_vbox.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # 左侧容器
        left_container = QWidget()
        left_container.setLayout(left_vbox)

        # ---- 右侧图形区域 ----
        right_vbox = QVBoxLayout()
        self.graph_widget = PlotWidget()
        self.graph_widget.setBackground('w')
        self.graph_widget.showGrid(x=True, y=True, alpha=0.3)
        self.graph_widget.setLabel('left', '电压', units='μV')
        self.graph_widget.setLabel('bottom', '时间', units='s')
        self.graph_widget.setTitle('时域信号')
        self.graph_widget.setYRange(0, 100 * 16 + 100)
        self.graph_widget.addLegend()

        # 为每个通道创建一条曲线 (最多16)
        self.plots = []
        for i in range(16):
            color = self.channel_colors[i % len(self.channel_colors)]
            pen = pg.mkPen(color=color, width=1.5)
            plot = self.graph_widget.plot([], [], pen=pen, name=f'CH{i+1}', antialias=True)
            self.plots.append(plot)

        right_vbox.addWidget(self.graph_widget)

        # 底部状态栏
        self.status_label = QLabel("正在连接...")
        right_vbox.addWidget(self.status_label)

        # 主布局：左侧面板 + 右侧图形
        hbox_main = QHBoxLayout()
        hbox_main.addWidget(left_container)
        hbox_main.addLayout(right_vbox, 1)

        central_widget = QWidget()
        central_widget.setLayout(hbox_main)
        self.setCentralWidget(central_widget)

        # 定时器：每 100ms 更新一次图形（从缓存中取数据绘图）
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_plot)
        self.update_timer.start(100)

    # ---------------------------------------------------------
    # 控件槽函数
    # ---------------------------------------------------------
    def on_select_all(self, state):
        if self._updating or not self.chk_select_all.isEnabled():
            return
        self._updating = True
        checked = (state == Qt.Checked)
        for chk in self.channel_buttons:
            if chk.isEnabled():
                chk.setChecked(checked)
        self._updating = False

    def toggle_channel(self, state, idx):
        if idx < len(self.channel_states):
            self.channel_states[idx] = bool(state)
        if idx < len(self.plots):
            self.plots[idx].setVisible(state)

        # 更新全选复选框状态（避免递归）
        if not self._updating and self.chk_select_all.isEnabled():
            enabled_checks = [chk for chk in self.channel_buttons if chk.isEnabled()]
            if enabled_checks:
                all_checked = all(chk.isChecked() for chk in enabled_checks)
                self._updating = True
                self.chk_select_all.setChecked(all_checked)
                self._updating = False

    def on_filter_enable_changed(self, state):
        """滤波启用复选框状态变化槽"""
        self.filter_enabled = (state == Qt.Checked)
        print(f"滤波启用状态: {self.filter_enabled}")
        if self.is_collecting:
            self.status_label.setText(f"滤波{'已启用' if self.filter_enabled else '已禁用'} (实时生效)")

    def on_signal_type_changed(self, text):
        """信号类型下拉框变化槽"""
        if text != self.signal_type:
            self.signal_type = text
            if self.is_collecting:
                QMessageBox.information(self, "提示", "信号类型更改将在下次采集时生效。请停止后重新开始。")
            else:
                self.init_filters()   # 重新创建对应类型的滤波器
            self.status_label.setText(f"信号类型: {text}")

    def on_display_changed(self, text):
        """显示时长下拉框变化槽"""
        sec = int(text.replace("秒", ""))
        self.display_seconds = sec
        self.display_length = self.sample_rate * sec

    # ---------------------------------------------------------
    # 采集控制
    # ---------------------------------------------------------
    def toggle_collection(self):
        """开始/停止采集按钮点击槽"""
        if not self.is_collecting:

            # 更新放大倍数
            self.gain = int(self.gain_combo.currentText())

            # 更新采样率
            self.sample_rate = int(self.sample_combo.currentText().replace("Hz", ""))

            # 更新绘图长度
            self.display_length = self.sample_rate * self.display_seconds

            # 更新滤波器 (重新创建)
            self.init_filters()

            # 更新状态栏
            self.status_label.setText(f"采样率: {self.sample_rate}Hz | {self.num_channels}通道 | 增益x{self.gain}")

            # ===== 开始采集前的硬件配置 =====
            try:
                # 1. 配置采样率
                rate_cmd_map = {250: '~6', 500: '~5', 1000: '~4'}
                cmd = rate_cmd_map.get(self.sample_rate)
                if cmd:
                    self.board.config_board(cmd)
                    print(f"已配置采样率为 {self.sample_rate} Hz (命令: {cmd})")
                else:
                    print(f"警告：采样率 {self.sample_rate} 无对应命令，使用默认")

                # 2. 配置通道增益 (支持16通道)
                if not self.send_ch_config_cmd():
                    QMessageBox.warning(self, "警告", "通道增益配置失败，请检查连接。")
                    return

            except Exception as e:
                QMessageBox.critical(self, "错误", f"配置设备失败: {e}")
                return

            # ===== 开始数据流 =====
            try:
                self.board.start_stream()
                # 丢弃启动时可能残留的数据（确保 worker 读取从新数据开始）
                self.board.get_board_data()

                self.is_collecting = True
                self.btn_start.setText("停止采集")
                self.btn_start.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")
                self.btn_pause.setEnabled(True)
                self.btn_export_csv.setEnabled(False)

                # 采集期间禁用配置控件
                self.sample_combo.setEnabled(False)
                self.gain_combo.setEnabled(False)
                self.type_combo.setEnabled(False)
                for chk in self.channel_buttons:
                    chk.setEnabled(False)
                self.chk_select_all.setEnabled(False)

                # 清空数据缓存和计数器
                self.eeg_data_buffer = [[] for _ in range(self.num_channels)]
                self.all_raw_data = []
                self.total_samples = 0

                # 重新初始化滤波器（确保使用最新参数）
                self.init_filters()

                # 启动工作线程
                self.worker = BrainFlowWorker(self.board, self.eeg_channels, self.sample_rate)
                self.worker.data_received.connect(self.on_data_received)
                self.worker.start()

                self.status_label.setText(f"采集运行中 | {self.signal_type} | {self.sample_rate}Hz | 增益x{self.gain}")
                print(f"开始采集, 信号类型: {self.signal_type}, 采样率: {self.sample_rate}Hz, 增益: {self.gain}")

            except Exception as e:
                QMessageBox.critical(self, "错误", f"开始采集失败: {e}")

        else:
            # ===== 停止采集 =====
            self.is_collecting = False
            if self.worker:
                self.worker.stop()
                self.worker = None
            try:
                self.board.stop_stream()
            except:
                pass

            self.btn_start.setText("开始采集")
            self.btn_start.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
            self.btn_pause.setEnabled(False)
            self.btn_export_csv.setEnabled(True)

            # 恢复配置控件
            self.sample_combo.setEnabled(True)
            self.gain_combo.setEnabled(True)
            self.type_combo.setEnabled(True)
            for chk in self.channel_buttons:
                chk.setEnabled(True)
            self.chk_select_all.setEnabled(True)

            self.paused = False
            self.btn_pause.setText("暂停显示")
            self.status_label.setText(f"采集已停止 | {self.num_channels}通道")
            print("停止采集")

    # ---------------------------------------------------------
    # 数据接收与滤波
    # ---------------------------------------------------------
    def on_data_received(self, eeg_data_uv):
        """
        处理工作线程发来的新数据段。
        """
        num_ch = min(eeg_data_uv.shape[0], self.num_channels)
        num_samples = eeg_data_uv.shape[1]
        self.total_samples += num_samples   # 更新全局样本计数器（用于 X 轴滚动）

        # 判断是否启用滤波
        if self.filter_enabled and len(self.channel_filters) >= num_ch:
            # 需要滤波：逐通道处理
            filtered_data = eeg_data_uv.copy()
            for ch in range(num_ch):
                filt = self.channel_filters[ch]
                channel_data = filtered_data[ch, :]   # 一维数组
                # process_samples 返回滤波后的列表
                filtered_ch = filt.process_samples(self.sample_rate, channel_data.tolist())
                filtered_data[ch, :] = np.array(filtered_ch)
            data_to_display = filtered_data
        else:
            # 滤波关闭，直接使用原始数据
            data_to_display = eeg_data_uv

        # 如果未暂停，更新显示缓存
        if not self.paused:
            for i in range(num_ch):
                if i < len(self.eeg_data_buffer):
                    # 将新数据追加到对应通道的缓存
                    self.eeg_data_buffer[i].extend(data_to_display[i, :].tolist())
                    # 限制缓存大小，防止无限增长 (保留 display_length*2 个点)
                    max_buf = self.display_length * 2
                    if len(self.eeg_data_buffer[i]) > max_buf:
                        self.eeg_data_buffer[i] = self.eeg_data_buffer[i][-max_buf:]

        # 保存原始数据（用于导出），此处保存的是接收到的原始数据段（未经过滤波和缩放）
        self.all_raw_data.append(eeg_data_uv)

    # ---------------------------------------------------------
    # 图形更新
    # ---------------------------------------------------------
    def update_plot(self):
        """
        由定时器调用，从显示缓存中取出最近 display_length 个点并绘制到图形。
        每个通道添加垂直偏移以便分开显示。
        X 轴使用全局总样本数 self.total_samples 保证持续滚动。
        """
        if not self.is_collecting or self.paused:
            return
        if len(self.eeg_data_buffer) == 0 or len(self.eeg_data_buffer[0]) == 0:
            return

        max_channels = min(self.num_channels, 16)
        for ch in range(max_channels):
            if self.channel_states[ch] and len(self.eeg_data_buffer[ch]) > 0:
                data_len = len(self.eeg_data_buffer[ch])
                # 计算该通道缓存数据在全局时间轴上的起始索引
                cache_start = self.total_samples - data_len
                # 取最近 display_length 个点
                start_idx = max(0, data_len - self.display_length)
                display_data = self.eeg_data_buffer[ch][start_idx:]
                # 添加垂直偏移
                offset = 100 + ch * 100
                y = np.array(display_data) + offset
                # 全局时间轴坐标
                x = (np.arange(len(y)) + cache_start + start_idx) / self.sample_rate
                self.plots[ch].setData(x, y, clear=True)
                self.plots[ch].setVisible(True)

        # 隐藏超过实际通道数的曲线
        for ch in range(max_channels, 16):
            self.plots[ch].setVisible(False)

        # 设置 X 轴范围（使用全局累计样本数）
        if self.total_samples > 0:
            x_min = max(0, (self.total_samples - self.display_length)) / self.sample_rate
            x_max = self.total_samples / self.sample_rate
            self.graph_widget.setXRange(x_min, x_max)

    # ---------------------------------------------------------
    # 辅助功能
    # ---------------------------------------------------------
    def toggle_pause(self):
        """暂停/继续显示切换"""
        self.paused = not self.paused
        self.btn_pause.setText("继续显示" if self.paused else "暂停显示")

    def auto_scale(self):
        """自动调整 Y 轴范围"""
        self.graph_widget.autoRange()

    def export_csv(self):
        """
        导出所有采集到的原始数据为 CSV 文件。
        数据为分段存储的原始 LSB，拼接后按通道列输出。
        """
        if not self.all_raw_data:
            QMessageBox.information(self, "提示", "没有数据可导出！")
            return

        # 将分段数据按列拼接 (axis=1 表示水平拼接)
        full_data = np.concatenate(self.all_raw_data, axis=1)
        default_name = f"eeg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.sample_rate}hz.csv"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存CSV", default_name, "CSV文件 (*.csv);;所有文件 (*)"
        )
        if not filepath:
            return
        try:
            max_ch = min(self.num_channels, 16)
            cols = [f'CH{i+1}_uV' for i in range(max_ch)]   # 列名标注为μV
            df = pd.DataFrame(full_data[:max_ch, :].T, columns=cols)
            df.insert(0, 'Time_s', np.arange(len(df)) / self.sample_rate)
            df.to_csv(filepath, index=False)
            QMessageBox.information(self, "成功", f"保存到: {filepath}\n采样点: {len(df)} (原始LSB)")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def closeEvent(self, event):
        """窗口关闭事件：安全停止采集和释放资源"""
        if self.is_collecting:
            self.toggle_collection()   # 停止采集
        self.update_timer.stop()
        try:
            if self.board:
                self.board.release_session()
        except:
            pass
        event.accept()


# -------------------------------------------------------------
# 主函数
# -------------------------------------------------------------
def main():
    """应用程序入口：设置高DPI，创建主窗口并运行"""
    # 启用高DPI缩放支持
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    # 可修改 IP 地址以匹配实际设备
    window = EEGMainWindow(ip='192.168.4.1')
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()