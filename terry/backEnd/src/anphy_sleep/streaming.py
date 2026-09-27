from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from scipy.signal import butter, iirnotch, sosfilt, tf2sos

from .contracts import EegChunk, RealtimeOutput, StateUpdate
from .features import (
    CORE_FEATURES,
    _past_slope_per_minute,
    compute_window_signal_features,
)
from .inference import InferenceEngine
from .io import normalize_channel_name
from .music import MusicController, NoOpMusicController


class SignalPipeline:
    """Causal reference, notch/bandpass, and window pipeline for EEG chunks."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.target_channels = tuple(config["channels"]["target"])
        self.sfreq = float(config["signal"]["target_sfreq_hz"])
        self.window_samples = int(
            round(float(config["epoching"]["window_seconds"]) * self.sfreq)
        )
        self.step_samples = int(
            round(float(config["epoching"]["step_seconds"]) * self.sfreq)
        )
        signal_config = config["signal"]
        highpass_hz = float(signal_config["highpass_hz"])
        lowpass_hz = float(signal_config["lowpass_hz"])
        nyquist_hz = self.sfreq / 2.0
        if not 0.0 < highpass_hz < lowpass_hz < nyquist_hz:
            raise ValueError(
                "signal highpass/lowpass must satisfy "
                f"0 < highpass < lowpass < Nyquist ({nyquist_hz:g} Hz)"
            )
        self.sos = butter(
            4,
            [highpass_hz, lowpass_hz],
            btype="bandpass",
            fs=self.sfreq,
            output="sos",
        )
        notch_frequency = float(
            signal_config.get(
                "notch_frequency_hz",
                signal_config.get("line_frequency_hz", 0.0),
            )
        )
        notch_quality = float(signal_config.get("notch_quality_factor", 30.0))
        if notch_frequency > 0.0:
            if not 0.0 < notch_frequency < nyquist_hz:
                raise ValueError("notch frequency must be below Nyquist")
            if not np.isfinite(notch_quality) or notch_quality <= 0.0:
                raise ValueError("notch_quality_factor must be positive")
            notch_b, notch_a = iirnotch(
                notch_frequency,
                notch_quality,
                fs=self.sfreq,
            )
            self.notch_sos = tf2sos(notch_b, notch_a)
        else:
            self.notch_sos = np.empty((0, 6), dtype=float)
        self.filter_sos = np.concatenate([self.notch_sos, self.sos], axis=0)
        self.filter_state = np.zeros(
            (self.filter_sos.shape[0], len(self.target_channels), 2),
            dtype=float,
        )
        self.buffer = np.empty((len(self.target_channels), 0), dtype=float)
        self.buffer_start_sample = 0
        self.total_samples = 0
        self.next_window_end = self.window_samples
        self.origin_timestamp_s: float | None = None
        self.expected_timestamp_s: float | None = None

    def _channel_order(self, names: tuple[str, ...]) -> list[int]:
        aliases = {
            normalize_channel_name(source).upper(): target
            for target, source in self.config["channels"].get("aliases", {}).items()
        }
        target_lookup = {channel.upper(): channel for channel in self.target_channels}
        canonical = []
        for name in names:
            normalized = normalize_channel_name(name).upper()
            canonical.append(aliases.get(normalized, target_lookup.get(normalized)))
        if any(name is None for name in canonical):
            unknown = [
                source for source, target in zip(names, canonical, strict=True)
                if target is None
            ]
            raise ValueError(f"Unknown EEG channels: {unknown}")
        if len(set(canonical)) != len(canonical):
            raise ValueError("EEG chunk contains duplicate canonical channels")
        missing = [channel for channel in self.target_channels if channel not in canonical]
        extra = [channel for channel in canonical if channel not in self.target_channels]
        if missing or extra:
            raise ValueError(f"Expected 16 target channels; missing={missing}, extra={extra}")
        return [canonical.index(channel) for channel in self.target_channels]

    def push(self, chunk: EegChunk) -> list[tuple[float, np.ndarray]]:
        chunk.validate()
        if not np.isclose(chunk.sample_rate_hz, self.sfreq):
            raise ValueError(
                f"Streaming input must be sampled at {self.sfreq:g} Hz; "
                f"received {chunk.sample_rate_hz:g} Hz"
            )
        if self.origin_timestamp_s is None:
            self.origin_timestamp_s = float(chunk.timestamp_s)
            self.expected_timestamp_s = float(chunk.timestamp_s)
        assert self.expected_timestamp_s is not None
        tolerance = 1.5 / self.sfreq
        if abs(float(chunk.timestamp_s) - self.expected_timestamp_s) > tolerance:
            raise ValueError(
                "EEG chunks must be contiguous; "
                f"expected timestamp {self.expected_timestamp_s:.6f}, "
                f"received {chunk.timestamp_s:.6f}"
            )

        order = self._channel_order(chunk.channel_names)
        samples = np.asarray(chunk.samples[order], dtype=float)
        if chunk.unit == "uV":
            samples = samples * 1e-6
        if str(self.config["signal"].get("reference", "average")) != "average":
            raise ValueError("Realtime v1 supports average reference only")
        samples = samples - samples.mean(axis=0, keepdims=True)
        filtered, self.filter_state = sosfilt(
            self.filter_sos,
            samples,
            axis=-1,
            zi=self.filter_state,
        )

        self.buffer = np.concatenate([self.buffer, filtered], axis=1)
        self.total_samples += filtered.shape[1]
        self.expected_timestamp_s = float(chunk.timestamp_s) + (
            filtered.shape[1] / self.sfreq
        )

        windows = []
        while self.next_window_end <= self.total_samples:
            start_sample = self.next_window_end - self.window_samples
            local_start = start_sample - self.buffer_start_sample
            local_stop = self.next_window_end - self.buffer_start_sample
            window = self.buffer[:, local_start:local_stop].copy()
            windows.append((self.next_window_end / self.sfreq, window))
            self.next_window_end += self.step_samples

        retain_from = max(
            self.buffer_start_sample,
            self.next_window_end - self.window_samples,
        )
        discard = retain_from - self.buffer_start_sample
        if discard > 0:
            self.buffer = self.buffer[:, discard:]
            self.buffer_start_sample = retain_from
        return windows


class OnlineFeatureState:
    """Track causal slopes and the first-five-minute robust baseline."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.step_seconds = float(config["epoching"]["step_seconds"])
        history_windows = max(
            3,
            int(
                round(
                    float(config["epoching"]["slope_history_seconds"])
                    / self.step_seconds
                )
            ),
        )
        self.history = {
            feature: deque(maxlen=history_windows) for feature in CORE_FEATURES
        }
        self.baseline_seconds = float(
            config.get("realtime", {}).get("baseline_seconds", 300.0)
        )
        self.baseline_values = {feature: [] for feature in CORE_FEATURES}
        self.baseline_parameters: dict[str, tuple[float, float]] = {}
        self.baseline_ready = False

    def update(
        self,
        features: dict[str, float | bool],
        window_end_s: float,
    ) -> dict[str, float]:
        enriched = {name: float(value) for name, value in features.items()}
        for feature in CORE_FEATURES:
            self.history[feature].append(float(features[feature]))
            enriched[f"{feature}_slope_1m"] = _past_slope_per_minute(
                np.asarray(self.history[feature], dtype=float),
                self.step_seconds,
            )

        if not self.baseline_ready and bool(features["is_clean"]):
            for feature in CORE_FEATURES:
                self.baseline_values[feature].append(float(features[feature]))
        if not self.baseline_ready and window_end_s >= self.baseline_seconds:
            self._freeze_baseline()

        for feature in CORE_FEATURES:
            parameters = self.baseline_parameters.get(feature)
            enriched[f"{feature}_baseline_z"] = (
                (float(features[feature]) - parameters[0]) / parameters[1]
                if parameters is not None
                else np.nan
            )
        return enriched

    def _freeze_baseline(self) -> None:
        for feature, values in self.baseline_values.items():
            array = np.asarray(values, dtype=float)
            if len(array) < 3:
                continue
            center = float(np.median(array))
            scale = float(1.4826 * np.median(np.abs(array - center)))
            if not np.isfinite(scale) or scale < 1e-12:
                scale = float(np.std(array, ddof=0))
            if np.isfinite(scale) and scale > 0:
                self.baseline_parameters[feature] = (center, scale)
        self.baseline_ready = len(self.baseline_parameters) == len(CORE_FEATURES)


class RealtimeSession:
    """Public transport-neutral API: EEG chunks in, state and music decisions out."""

    def __init__(
        self,
        config: dict[str, Any],
        prediction_model_path: str | Path,
        state_model_path: str | Path,
        session_id: str | None = None,
        music_controller: MusicController | None = None,
    ) -> None:
        self.config = config
        self.session_id = session_id or str(uuid4())
        self.signal = SignalPipeline(config)
        self.feature_state = OnlineFeatureState(config)
        self.inference = InferenceEngine(
            prediction_model_path,
            state_model_path,
        )
        state_windows = max(
            1,
            int(
                round(
                    self.inference.state_aggregation_seconds
                    / float(config["epoching"]["step_seconds"])
                )
            ),
        )
        self.state_feature_history: deque[dict[str, float]] = deque(
            maxlen=state_windows
        )
        self.music_controller = music_controller or NoOpMusicController()

    def push(self, chunk: EegChunk) -> list[RealtimeOutput]:
        if chunk.session_id is not None and chunk.session_id != self.session_id:
            raise ValueError(
                f"Chunk session_id {chunk.session_id!r} does not match "
                f"{self.session_id!r}"
            )
        outputs = []
        for window_end_s, window in self.signal.push(chunk):
            base = compute_window_signal_features(
                window,
                self.signal.sfreq,
                self.signal.target_channels,
                self.config,
            )
            features = self.feature_state.update(base, window_end_s)
            self.state_feature_history.append(features)
            is_clean = bool(base["is_clean"])
            prediction_ready = all(
                np.isfinite(features.get(name, np.nan))
                for name in self.inference.prediction_features
            )
            if not is_clean:
                status = "signal_invalid"
            elif not prediction_ready:
                status = "warming_up"
            else:
                status = "ok"

            n2_probability = None
            state_probabilities = None
            if status == "ok":
                n2_probability = self.inference.predict_future_n2(features)
                if len(self.state_feature_history) == self.state_feature_history.maxlen:
                    state_features = {}
                    state_history_valid = True
                    for name in self.inference.state_features:
                        values = np.asarray(
                            [
                                history[name]
                                for history in self.state_feature_history
                            ],
                            dtype=float,
                        )
                        if np.isfinite(values).sum() < 3:
                            state_history_valid = False
                            break
                        state_features[name] = float(np.nanmean(values))
                    if state_history_valid:
                        state_probabilities = self.inference.predict_state(
                            state_features
                        )

            def baseline_value(name: str) -> float | None:
                value = features[f"{name}_baseline_z"]
                return float(value) if np.isfinite(value) else None

            state = StateUpdate(
                session_id=self.session_id,
                window_end_s=float(window_end_s),
                signal_quality=float(base["signal_quality"]),
                status=status,
                baseline_ready=self.feature_state.baseline_ready,
                n2_within_5m_probability=n2_probability,
                aasm_state_probabilities=state_probabilities,
                interpretable_features={
                    "frontal_beta_log": float(features["frontal_beta_log"]),
                    "posterior_alpha_log": float(features["posterior_alpha_log"]),
                    "central_theta_log": float(features["central_theta_log"]),
                    "central_sigma_log": float(features["central_sigma_log"]),
                    "frontocentral_delta_log": float(
                        features["frontocentral_delta_log"]
                    ),
                    "frontal_beta_z": baseline_value("frontal_beta_log"),
                    "posterior_alpha_z": baseline_value("posterior_alpha_log"),
                    "central_theta_z": baseline_value("central_theta_log"),
                    "central_sigma_z": baseline_value("central_sigma_log"),
                    "frontocentral_delta_z": baseline_value(
                        "frontocentral_delta_log"
                    ),
                    "alpha_theta_slope_1m": float(
                        features["posterior_alpha_theta_log_ratio_slope_1m"]
                    )
                    if np.isfinite(
                        features["posterior_alpha_theta_log_ratio_slope_1m"]
                    )
                    else None,
                },
            )
            outputs.append(
                RealtimeOutput(
                    state=state,
                    music=self.music_controller.update(state),
                )
            )
        return outputs
