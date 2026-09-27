import csv
import os
import queue
import threading
import time
from datetime import datetime

import serial


# ============================================================
# 16通道脑电 入眠采集（无界面）
#
# 串口采集 + 实时入眠推理 + 音乐播放
# 状态只在终端打印，Ctrl+C 结束
#
# 输出：
#   eeg_labeled.csv
#   sleep_onset.jsonl
#   session_summary.csv
#
# CH0-CH15 对应真实帽位：
#   C3 C4 Cz FC3 FC4 CP3 CP4 FCz CPz Fz P3 Pz P4 O1 Oz O2
# ============================================================


PORT = "COM5"
BAUD = 921600

ENABLE_SLEEP_INFERENCE = True
ENABLE_MUSIC = True
HARDWARE_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "config.hardware.yaml",
)

SAVE_UV = False

VREF = 2.5
GAIN = 24.0

FRAME_HEADER = b"\xAB\xCD"
FRAME_FOOTER = b"\xDC\xBA"
FRAME_LEN = 52
CHANNEL_COUNT = 16
BYTES_PER_CHANNEL = 3
ADC_SCALE = 2 ** 23
ADC_MIN = -8388608
ADC_MAX = 8388607

HARDWARE_CHANNEL_ORDER = (
    "C3 C4 Cz FC3 FC4 CP3 CP4 FCz CPz Fz P3 Pz P4 O1 Oz O2"
)
STATUS_INTERVAL_SEC = 3.0


class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.phase_id = 1
        self.phase = "sleep"
        self.phase_cn = "入眠"
        self.model_label = "sleep"
        self.target_digit = ""
        self.sleep_hud = "入眠推理: 未启动"

    def set_sleep_hud(self, text):
        with self.lock:
            self.sleep_hud = str(text)

    def get_sleep_hud(self):
        with self.lock:
            return self.sleep_hud

    def get_state(self):
        with self.lock:
            return (
                self.phase_id,
                self.phase,
                self.phase_cn,
                self.model_label,
                self.target_digit,
            )


class SessionFiles:
    def __init__(self):
        self.output_dir = "eeg_sleep_output_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(self.output_dir, exist_ok=True)
        self.eeg_csv = os.path.join(self.output_dir, "eeg_labeled.csv")
        self.sleep_jsonl = os.path.join(self.output_dir, "sleep_onset.jsonl")
        self.summary_csv = os.path.join(self.output_dir, "session_summary.csv")
        with open(self.summary_csv, "w", newline="", encoding="utf-8-sig") as handle:
            csv.writer(handle).writerow(["item", "value"])

    def log_summary(self, rows):
        with open(self.summary_csv, "a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            for item, value in rows:
                writer.writerow([item, value])


def int24_to_signed(data3) -> int:
    return int.from_bytes(data3, "little", signed=True)


def raw_to_uv(raw: int) -> float:
    return raw / ADC_SCALE * VREF / GAIN * 1_000_000


def format_time_ms(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def open_serial_port(port: str, baud: int):
    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=0.001, write_timeout=0)
    except Exception as first_error:
        try:
            ser = serial.Serial(
                port=rf"\\.\{port}",
                baudrate=baud,
                timeout=0.001,
                write_timeout=0,
            )
        except Exception as second_error:
            raise RuntimeError(
                f"串口打开失败：{first_error}\n备用方式也失败：{second_error}"
            )
    try:
        ser.set_buffer_size(rx_size=1024 * 1024, tx_size=4096)
    except Exception:
        pass
    return ser


def probe_serial_stream(ser, seconds: float = 1.0) -> None:
    """Print what the wire actually contains before live parsing starts."""
    raw = bytearray()
    deadline = time.time() + seconds
    while time.time() < deadline:
        chunk = ser.read(65536)
        if chunk:
            raw.extend(chunk)
    valid_at = []
    index = 0
    while True:
        found = raw.find(FRAME_HEADER, index)
        if found < 0 or found + FRAME_LEN > len(raw):
            break
        if raw[found + 50 : found + 52] == FRAME_FOOTER:
            valid_at.append(found)
            index = found + FRAME_LEN
        else:
            index = found + 1
    gaps = [b - a for a, b in zip(valid_at, valid_at[1:])]
    gap = min(gaps) if gaps else 0
    print(
        f"[EEG] 原始流 {seconds:.1f}s：{len(raw)} 字节 "
        f"({len(raw) / seconds:.0f} B/s)，完整帧 {len(valid_at)} "
        f"({len(valid_at) / seconds:.1f} Hz)，"
        f"帧间隔 {gap or '未知'} 字节",
        flush=True,
    )
    if len(valid_at) / seconds < 200:
        print(
            "[EEG] 线上有效帧远低于 250 Hz。这不是写盘慢，是板子实际送出的帧率，"
            "或帧格式/波特率与 52 字节 ABCD…DCBA 不一致。",
            flush=True,
        )


def count_rail_channels(channels) -> int:
    return sum(
        1
        for value in channels
        if value <= ADC_MIN + 5 or value >= ADC_MAX - 5
    )


def get_quality_flag(channels):
    saturation_count = 0
    for value in channels:
        if value <= ADC_MIN + 5 or value >= ADC_MAX - 5:
            saturation_count += 1
    if saturation_count >= 8:
        quality_flag = "invalid"
    elif saturation_count > 0:
        quality_flag = "saturated"
    else:
        quality_flag = "good"
    return saturation_count, quality_flag


class EEGSerialThread:
    def __init__(self, files: SessionFiles, shared_state: SharedState, t0: float, sleep_monitor=None):
        self.files = files
        self.shared_state = shared_state
        self.t0 = t0
        self.sleep_monitor = sleep_monitor
        self.stop_event = threading.Event()
        self.thread = None
        self.writer_thread = None
        self.row_queue: queue.Queue = queue.Queue(maxsize=50_000)
        self.frame_count = 0
        self.bad_frame_count = 0
        self.byte_count = 0
        self.dropped_rows = 0
        self.current_fps = 0.0
        self.bytes_per_sec = 0.0
        self.rail_channels = 0
        self.last_stat_time = time.time()
        self.last_stat_frame = 0
        self.last_byte_count = 0
        self.error_message = ""

    def start(self):
        self.writer_thread = threading.Thread(target=self._write_rows, daemon=True)
        self.writer_thread.start()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        self.row_queue.put(None)
        if self.writer_thread:
            self.writer_thread.join(timeout=2.0)

    def _write_rows(self):
        header = [
            "sample_index",
            "time",
            "t_rel_s",
            "unix_time",
            "phase_id",
            "phase",
            "phase_cn",
            "model_label",
            "target_digit",
            "fps_est",
            "bad_frame_count",
            "saturation_count",
            "quality_flag",
        ]
        for channel in range(CHANNEL_COUNT):
            header.append(f"CH{channel}")
        if SAVE_UV:
            for channel in range(CHANNEL_COUNT):
                header.append(f"CH{channel}_uV")

        phase_id, phase, phase_cn, model_label, target_digit = self.shared_state.get_state()
        with open(self.files.eeg_csv, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            pending = 0
            while True:
                item = self.row_queue.get()
                if item is None:
                    handle.flush()
                    return
                (
                    sample_index,
                    now,
                    t_rel,
                    bad_frame_count,
                    saturation_count,
                    quality_flag,
                    fps,
                    channels,
                ) = item
                row = [
                    sample_index,
                    format_time_ms(now),
                    f"{t_rel:.6f}",
                    f"{now:.6f}",
                    phase_id,
                    phase,
                    phase_cn,
                    model_label,
                    target_digit,
                    f"{fps:.3f}",
                    bad_frame_count,
                    saturation_count,
                    quality_flag,
                    *channels,
                ]
                if SAVE_UV:
                    row.extend(f"{raw_to_uv(value):.6f}" for value in channels)
                writer.writerow(row)
                pending += 1
                if pending >= 250:
                    handle.flush()
                    pending = 0

    def run(self):
        try:
            ser = open_serial_port(PORT, BAUD)
            ser.reset_input_buffer()
            print(f"[EEG] 串口已打开：{PORT}, baud={BAUD}", flush=True)
            probe_serial_stream(ser, seconds=1.0)
            ser.reset_input_buffer()
        except Exception as exc:
            self.error_message = str(exc)
            print("[EEG] 串口打开失败：", flush=True)
            print(exc, flush=True)
            return

        buffer = bytearray()
        try:
            while not self.stop_event.is_set():
                data = ser.read(65536)
                if data:
                    buffer.extend(data)
                    self.byte_count += len(data)
                elif not buffer:
                    continue

                while True:
                    pos = buffer.find(FRAME_HEADER)
                    if pos < 0:
                        if len(buffer) > 1:
                            del buffer[:-1]
                        break
                    if pos > 0:
                        del buffer[:pos]
                    if len(buffer) < FRAME_LEN:
                        break

                    if buffer[50:52] != FRAME_FOOTER:
                        self.bad_frame_count += 1
                        nxt = buffer.find(FRAME_HEADER, 1)
                        if nxt < 0:
                            del buffer[:1]
                            break
                        del buffer[:nxt]
                        continue

                    payload = buffer[2:50]
                    channels = [
                        int24_to_signed(payload[index : index + 3])
                        for index in range(0, 48, 3)
                    ]
                    del buffer[:FRAME_LEN]

                    saturation_count, quality_flag = get_quality_flag(channels)
                    self.rail_channels = count_rail_channels(channels)
                    now = time.time()
                    if now - self.last_stat_time >= 1.0:
                        elapsed = now - self.last_stat_time
                        self.current_fps = (
                            (self.frame_count - self.last_stat_frame) / elapsed
                        )
                        self.bytes_per_sec = (
                            (self.byte_count - self.last_byte_count) / elapsed
                        )
                        self.last_stat_time = now
                        self.last_stat_frame = self.frame_count
                        self.last_byte_count = self.byte_count

                    try:
                        self.row_queue.put_nowait(
                            (
                                self.frame_count,
                                now,
                                now - self.t0,
                                self.bad_frame_count,
                                saturation_count,
                                quality_flag,
                                self.current_fps,
                                channels,
                            )
                        )
                    except queue.Full:
                        self.dropped_rows += 1

                    if self.sleep_monitor is not None:
                        try:
                            outputs = self.sleep_monitor.push_adc_frame(channels)
                            if outputs:
                                self.shared_state.set_sleep_hud(
                                    self.sleep_monitor.hud_text()
                                )
                        except Exception as exc:
                            self.shared_state.set_sleep_hud(f"入眠推理: {exc}")

                    self.frame_count += 1
        except Exception as exc:
            self.error_message = str(exc)
            print("[EEG] 采集线程出错：", flush=True)
            print(exc, flush=True)
        finally:
            try:
                ser.close()
                print("[EEG] 串口已关闭", flush=True)
            except Exception:
                pass


def open_sleep_monitor(files: SessionFiles, shared: SharedState):
    if not ENABLE_SLEEP_INFERENCE:
        shared.set_sleep_hud("入眠推理: 已关闭")
        return None
    try:
        from anphy_sleep.device_bridge import open_live_sleep_monitor

        monitor = open_live_sleep_monitor(
            HARDWARE_CONFIG,
            log_path=files.sleep_jsonl,
            enable_music=ENABLE_MUSIC,
        )
        shared.set_sleep_hud(monitor.hud_text())
        print(f"入眠推理已开启，日志：{files.sleep_jsonl}", flush=True)
        if monitor.music_runtime is not None:
            print("实时音乐已开启，无缓存时会后台向 Suno 要歌", flush=True)
        elif ENABLE_MUSIC:
            print(f"实时音乐未开启：{monitor.hud_text()}", flush=True)
        return monitor
    except Exception as exc:
        shared.set_sleep_hud(f"入眠推理未开启: {exc}")
        print(f"入眠推理未开启：{exc}", flush=True)
        return None


def print_status(elapsed: float, eeg_thread: EEGSerialThread, shared: SharedState) -> None:
    print(
        f"[{elapsed:7.1f}s] "
        f"fps={eeg_thread.current_fps:6.1f}  "
        f"{eeg_thread.bytes_per_sec:6.0f}B/s  "
        f"帧={eeg_thread.frame_count}  "
        f"坏帧={eeg_thread.bad_frame_count}  "
        f"饱和={eeg_thread.rail_channels}/16  "
        f"{shared.get_sleep_hud()}",
        flush=True,
    )


def main():
    files = SessionFiles()
    shared = SharedState()
    sleep_monitor = None
    eeg_thread = None
    t0 = time.time()

    print("=" * 80, flush=True)
    print("16通道脑电 入眠采集（无界面）", flush=True)
    print("=" * 80, flush=True)
    print(f"串口：{PORT}", flush=True)
    print(f"波特率：{BAUD}", flush=True)
    print(f"通道顺序：{HARDWARE_CHANNEL_ORDER}", flush=True)
    print(f"输出文件夹：{files.output_dir}", flush=True)
    print("请关闭 JCom。Ctrl+C 结束采集。", flush=True)
    print("=" * 80, flush=True)

    files.log_summary([
        ("port", PORT),
        ("baud", BAUD),
        ("sample_rate_expected_hz", 250),
        ("sleep_inference_enabled", ENABLE_SLEEP_INFERENCE),
        ("music_enabled", ENABLE_MUSIC),
        ("hardware_channel_order", HARDWARE_CHANNEL_ORDER),
    ])

    try:
        sleep_monitor = open_sleep_monitor(files, shared)
        eeg_thread = EEGSerialThread(files, shared, t0, sleep_monitor=sleep_monitor)
        eeg_thread.start()
        time.sleep(0.5)
        if eeg_thread.error_message:
            print("串口打开失败，请关闭 JCom 并检查端口号。", flush=True)
            return

        last_print = 0.0
        while True:
            if eeg_thread.error_message:
                print(f"[EEG] {eeg_thread.error_message}", flush=True)
                break
            now = time.time()
            if now - last_print >= STATUS_INTERVAL_SEC:
                print_status(now - t0, eeg_thread, shared)
                last_print = now
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在结束采集。", flush=True)
    finally:
        if sleep_monitor is not None:
            try:
                sleep_monitor.close()
            except Exception:
                pass
        if eeg_thread is not None:
            eeg_thread.stop()
            total_time = time.time() - t0
            avg_fps = eeg_thread.frame_count / total_time if total_time > 0 else 0
            files.log_summary([
                ("frame_count", eeg_thread.frame_count),
                ("avg_fps", f"{avg_fps:.3f}"),
                ("bad_frame_count", eeg_thread.bad_frame_count),
                ("dropped_rows", eeg_thread.dropped_rows),
                ("byte_count", eeg_thread.byte_count),
            ])
            print("", flush=True)
            print("=" * 80, flush=True)
            print("采集结束", flush=True)
            print("=" * 80, flush=True)
            print(f"输出文件夹：{files.output_dir}", flush=True)
            print(f"主数据文件：{files.eeg_csv}", flush=True)
            if os.path.exists(files.sleep_jsonl):
                print(f"入眠推理日志：{files.sleep_jsonl}", flush=True)
            print(f"采集时长：{total_time:.3f} 秒", flush=True)
            print(f"有效脑电帧数：{eeg_thread.frame_count}", flush=True)
            print(f"平均帧率：{avg_fps:.3f} Hz", flush=True)
            print(f"坏帧/错位：{eeg_thread.bad_frame_count}", flush=True)
            print(f"写盘丢行：{eeg_thread.dropped_rows}", flush=True)
            print(f"接收字节数：{eeg_thread.byte_count}", flush=True)
            if eeg_thread.error_message:
                print(f"错误信息：{eeg_thread.error_message}", flush=True)
            print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
