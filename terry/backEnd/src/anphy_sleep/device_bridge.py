from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from .config import load_config
from .contracts import EegChunk, MusicCommand, StateUpdate
from .music_runtime import AdaptiveMusicRuntime, build_music_runtime
from .streaming import RealtimeSession

# CH0-CH15 on the physical cap, matching config.hardware.yaml.
HARDWARE_CHANNEL_NAMES = (
    "C3",
    "C4",
    "Cz",
    "FC3",
    "FC4",
    "CP3",
    "CP4",
    "FCz",
    "CPz",
    "Fz",
    "P3",
    "Pz",
    "P4",
    "O1",
    "Oz",
    "O2",
)

ADC_SCALE = 2 ** 23
ADC_VREF = 2.5
ADC_GAIN = 24.0
TARGET_SFREQ_HZ = 250.0
DEFAULT_CHUNK_SAMPLES = 25


def adc_to_uv(raw: int) -> float:
    """Convert one ADS1299-style 24-bit ADC count to microvolts."""
    return float(raw) / ADC_SCALE * ADC_VREF / ADC_GAIN * 1_000_000


def format_state_hud(
    state: StateUpdate | None,
    error: str | None = None,
    music: MusicCommand | None = None,
    music_error: str | None = None,
    playback_error: str | None = None,
) -> str:
    """One-line overlay text for the acquisition UI."""
    if error:
        return f"入眠推理: {error}"
    if state is None:
        parts = ["入眠推理: 等待6秒窗口"]
    else:
        probabilities = state.aasm_state_probabilities or {}
        wake = probabilities.get("W")
        n1 = probabilities.get("N1")
        n2 = probabilities.get("N2")
        future_n2 = state.n2_within_5m_probability
        parts = [
            f"入眠 {state.status}",
            f"Q{state.signal_quality:.2f}",
        ]
        if wake is not None and n1 is not None and n2 is not None:
            parts.append(f"W{wake:.2f} N1{n1:.2f} N2{n2:.2f}")
        if future_n2 is not None:
            parts.append(f"5分钟N2 {future_n2:.2f}")
        if not state.baseline_ready:
            parts.append("基线未满5分钟")
    if music_error:
        parts.append(f"音乐未开启: {music_error}")
    elif music is not None:
        mode = music.parameters.get("mode")
        label = f"音乐{music.action}"
        if mode:
            label += f":{mode}"
        parts.append(label)
        if playback_error:
            parts.append(f"播放失败: {playback_error}")
    return "  ".join(parts)


class LiveSleepOnsetMonitor:
    """Buffer device frames and push contiguous 250 Hz chunks into RealtimeSession."""

    def __init__(
        self,
        session: RealtimeSession,
        sample_rate_hz: float = TARGET_SFREQ_HZ,
        chunk_samples: int = DEFAULT_CHUNK_SAMPLES,
        log_path: str | Path | None = None,
        on_update: Callable[[StateUpdate], None] | None = None,
        music_runtime: AdaptiveMusicRuntime | None = None,
        music_error: str | None = None,
    ) -> None:
        if chunk_samples <= 0:
            raise ValueError("chunk_samples must be positive")
        self.session = session
        self.sample_rate_hz = float(sample_rate_hz)
        self.chunk_samples = int(chunk_samples)
        self.on_update = on_update
        self.music_runtime = music_runtime
        self._lock = threading.Lock()
        self._pending: list[list[float]] = []
        self._sample_index = 0
        self._latest_state: StateUpdate | None = None
        self._latest_music: MusicCommand | None = None
        self._error: str | None = None
        self._music_error = music_error
        self._log_handle = (
            Path(log_path).open("w", encoding="utf-8") if log_path is not None else None
        )

    @property
    def latest_state(self) -> StateUpdate | None:
        with self._lock:
            return self._latest_state

    @property
    def latest_error(self) -> str | None:
        with self._lock:
            return self._error

    def hud_text(self) -> str:
        playback_error = None
        if self.music_runtime is not None:
            playback_error = self.music_runtime.playback_worker.status().last_error
        with self._lock:
            return format_state_hud(
                self._latest_state,
                self._error,
                self._latest_music,
                self._music_error,
                playback_error,
            )

    def push_adc_frame(self, adc_values: list[int] | tuple[int, ...]) -> list[Any]:
        """Accept one device frame (CH0-CH15 ADC counts) and maybe emit model outputs."""
        if len(adc_values) != len(HARDWARE_CHANNEL_NAMES):
            raise ValueError(
                f"Expected {len(HARDWARE_CHANNEL_NAMES)} ADC channels; "
                f"received {len(adc_values)}"
            )
        uv_values = [adc_to_uv(int(value)) for value in adc_values]
        with self._lock:
            self._pending.append(uv_values)
            if len(self._pending) < self.chunk_samples:
                return []
            chunk = np.asarray(self._pending, dtype=float).T
            timestamp_s = self._sample_index / self.sample_rate_hz
            self._sample_index += chunk.shape[1]
            self._pending = []
        return self._push_chunk(timestamp_s, chunk)

    def flush(self) -> list[Any]:
        """Push any leftover samples when acquisition stops."""
        with self._lock:
            if not self._pending:
                return []
            chunk = np.asarray(self._pending, dtype=float).T
            timestamp_s = self._sample_index / self.sample_rate_hz
            self._sample_index += chunk.shape[1]
            self._pending = []
        return self._push_chunk(timestamp_s, chunk)

    def close(self) -> None:
        try:
            self.flush()
        finally:
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None
            if self.music_runtime is not None:
                try:
                    self.music_runtime.shutdown()
                except Exception:  # noqa: BLE001 - acquisition teardown must finish
                    pass
                self.music_runtime = None

    def _push_chunk(self, timestamp_s: float, samples_uv: np.ndarray) -> list[Any]:
        try:
            outputs = self.session.push(
                EegChunk(
                    timestamp_s=float(timestamp_s),
                    sample_rate_hz=self.sample_rate_hz,
                    channel_names=HARDWARE_CHANNEL_NAMES,
                    samples=samples_uv,
                    unit="uV",
                    session_id=self.session.session_id,
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep the serial thread alive
            with self._lock:
                self._error = str(exc)
            return []

        if outputs:
            latest = outputs[-1]
            with self._lock:
                self._latest_state = latest.state
                self._latest_music = latest.music
                self._error = None
            if self._log_handle is not None:
                for output in outputs:
                    self._log_handle.write(
                        json.dumps(output.to_dict(), ensure_ascii=False) + "\n"
                    )
                self._log_handle.flush()
            if self.on_update is not None:
                self.on_update(latest.state)
        return outputs


def open_live_sleep_monitor(
    config_path: str | Path,
    log_path: str | Path | None = None,
    on_update: Callable[[StateUpdate], None] | None = None,
    enable_music: bool | None = None,
) -> LiveSleepOnsetMonitor:
    """Load the hardware config and trained models for live cap inference."""
    config, _project_root = load_config(config_path)
    model_dir = Path(config["data"]["results_dir"]) / "models"
    prediction_path = model_dir / "future_n2_logistic_continuous.joblib"
    state_path = model_dir / "sleep_state_logistic_30s.joblib"
    missing = [
        str(path)
        for path in (prediction_path, state_path)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "缺少帽位部署模型: " + ", ".join(missing)
        )
    if tuple(config["channels"]["target"]) != HARDWARE_CHANNEL_NAMES:
        raise ValueError(
            "config channels.target must match the physical CH0-CH15 montage"
        )
    music_runtime: AdaptiveMusicRuntime | None = None
    music_error: str | None = None
    music_wanted = (
        bool(config.get("music", {}).get("enabled", False))
        if enable_music is None
        else bool(enable_music)
    )
    if music_wanted:
        try:
            if enable_music is True:
                config.setdefault("music", {})["enabled"] = True
            music_runtime = build_music_runtime(config)
            music_runtime.start(pregenerate=False)
        except Exception as exc:  # noqa: BLE001 - keep EEG inference available
            music_runtime = None
            music_error = str(exc)
    session = RealtimeSession(
        config,
        prediction_path,
        state_path,
        session_id="live-cap",
        music_controller=music_runtime,
    )
    return LiveSleepOnsetMonitor(
        session,
        sample_rate_hz=float(config["signal"]["target_sfreq_hz"]),
        log_path=log_path,
        on_update=on_update,
        music_runtime=music_runtime,
        music_error=music_error,
    )
