from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import welch

from .io import stage_at
from .preprocess import SubjectSegment


CORE_FEATURES = [
    "frontal_beta_log",
    "frontal_high_beta_log",
    "posterior_alpha_log",
    "central_theta_log",
    "central_sigma_log",
    "frontocentral_delta_log",
    "posterior_alpha_theta_log_ratio",
]


def _band_power(
    psd: np.ndarray,
    frequencies: np.ndarray,
    low: float,
    high: float,
) -> np.ndarray:
    mask = (frequencies >= low) & (frequencies < high)
    return np.trapezoid(psd[:, mask], frequencies[mask], axis=-1)


def _past_slope_per_minute(values: np.ndarray, step_seconds: float) -> float:
    if len(values) < 3 or not np.isfinite(values).all():
        return np.nan
    x_minutes = np.arange(len(values), dtype=float) * step_seconds / 60.0
    return float(np.polyfit(x_minutes, values, 1)[0])


def compute_window_signal_features(
    window: np.ndarray,
    sfreq: float,
    channel_names: list[str] | tuple[str, ...],
    config: dict[str, Any],
) -> dict[str, float | bool]:
    """Compute one causal window of spectral, regional, and amplitude-QC features."""
    channel_names = list(channel_names)
    if window.ndim != 2 or window.shape[0] != len(channel_names):
        raise ValueError("window must have shape (channels, samples)")
    if window.shape[1] < 2:
        raise ValueError("window is too short for spectral analysis")

    channel_index = {name: index for index, name in enumerate(channel_names)}
    missing = [
        channel
        for channels in config["channels"]["regions"].values()
        for channel in channels
        if channel not in channel_index
    ]
    if missing:
        raise ValueError(f"Missing configured regional channels: {sorted(set(missing))}")
    region_indices = {
        name: [channel_index[channel] for channel in channels]
        for name, channels in config["channels"]["regions"].items()
    }
    # Optional Web-only missing-channel mode. Average measured spectral features
    # instead of treating the zero average-referenced imputation as real power.
    # Entire missing regions use a global measured mean, explicitly experimental.
    excluded = set(config.get("realtime", {}).get("mean_imputed_channels", []))
    if excluded:
        available = [i for name, i in channel_index.items() if name not in excluded]
        if not available:
            raise ValueError("No measured channels available for regional means")
        region_indices = {
            name: [i for i in indices if channel_names[i] not in excluded] or available
            for name, indices in region_indices.items()
        }
    frontocentral = region_indices["frontal"] + region_indices["central"]
    bands = {
        name: (float(bounds[0]), float(bounds[1]))
        for name, bounds in config["bands"].items()
    }

    frequencies, psd = welch(
        window,
        fs=sfreq,
        window="hann",
        nperseg=min(int(2 * sfreq), window.shape[1]),
        noverlap=min(int(sfreq), window.shape[1] // 2),
        detrend="constant",
        axis=-1,
    )
    total_mask = (frequencies >= 0.5) & (frequencies <= 30.0)
    total_power = np.trapezoid(
        psd[:, total_mask],
        frequencies[total_mask],
        axis=-1,
    )
    epsilon = np.finfo(float).eps
    band_log_power: dict[str, np.ndarray] = {}
    band_relative_power: dict[str, np.ndarray] = {}
    for band, (low, high) in bands.items():
        absolute = _band_power(psd, frequencies, low, high)
        band_log_power[band] = np.log10(absolute + epsilon)
        band_relative_power[band] = absolute / (total_power + epsilon)

    peak_to_peak_uv = np.ptp(window, axis=-1) * 1e6
    standard_deviation_uv = np.std(window, axis=-1) * 1e6
    amplitude_clean = (
        peak_to_peak_uv <= float(config["signal"]["amplitude_reject_uv"])
    ) & (standard_deviation_uv >= 0.1)
    clean_fraction = float(np.mean(amplitude_clean))
    row: dict[str, float | bool] = {
        "signal_quality": clean_fraction,
        "is_clean": clean_fraction
        >= float(config["quality"]["minimum_clean_channel_fraction"]),
    }
    for band in bands:
        for channel, index in channel_index.items():
            row[f"ch__{channel}__{band}_log"] = float(
                band_log_power[band][index]
            )
            row[f"ch__{channel}__{band}_relative"] = float(
                band_relative_power[band][index]
            )
    row.update(
        {
            "frontal_beta_log": float(
                np.mean(band_log_power["beta"][region_indices["frontal"]])
            ),
            "frontal_high_beta_log": float(
                np.mean(band_log_power["high_beta"][region_indices["frontal"]])
            ),
            "posterior_alpha_log": float(
                np.mean(band_log_power["alpha"][region_indices["posterior"]])
            ),
            "central_theta_log": float(
                np.mean(band_log_power["theta"][region_indices["central"]])
            ),
            "central_sigma_log": float(
                np.mean(band_log_power["sigma"][region_indices["central"]])
            ),
            "frontocentral_delta_log": float(
                np.mean(band_log_power["delta"][frontocentral])
            ),
        }
    )
    row["posterior_alpha_theta_log_ratio"] = float(
        row["posterior_alpha_log"]
    ) - float(row["central_theta_log"])
    return row


def extract_window_features(
    segment: SubjectSegment,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Extract causal, interpretable features from overlapping 16-channel windows."""
    raw = segment.raw
    data = raw.get_data()
    auxiliary_data = (
        segment.auxiliary_raw.get_data()
        if segment.auxiliary_raw is not None
        else None
    )
    auxiliary_names = (
        list(segment.auxiliary_raw.ch_names)
        if segment.auxiliary_raw is not None
        else []
    )
    eog_indices = [
        index for index, name in enumerate(auxiliary_names) if "EOG" in name.upper()
    ]
    emg_indices = [
        index for index, name in enumerate(auxiliary_names) if "EMG" in name.upper()
    ]
    sfreq = float(raw.info["sfreq"])
    channel_names = list(raw.ch_names)
    window_seconds = float(config["epoching"]["window_seconds"])
    step_seconds = float(config["epoching"]["step_seconds"])
    window_samples = int(round(window_seconds * sfreq))
    step_samples = int(round(step_seconds * sfreq))
    if data.shape[1] < window_samples:
        raise ValueError(f"{segment.subject_id} is shorter than one analysis window")

    minimum_clean_channel_fraction = float(
        config["quality"]["minimum_clean_channel_fraction"]
    )
    rows: list[dict[str, float | int | str | bool]] = []

    for start in range(0, data.shape[1] - window_samples + 1, step_samples):
        stop = start + window_samples
        window = data[:, start:stop]
        start_relative_s = start / sfreq
        end_relative_s = stop / sfreq
        midpoint_absolute_s = (
            segment.segment_start_s + (start_relative_s + end_relative_s) / 2
        )

        signal_features = compute_window_signal_features(
            window,
            sfreq,
            channel_names,
            config,
        )
        artifact_clean_fraction = 1.0
        if (
            segment.artifact_matrix is not None
            and segment.artifact_channel_indices is not None
        ):
            epoch_index = int(midpoint_absolute_s // 30)
            if epoch_index < segment.artifact_matrix.shape[1]:
                artifact_clean = segment.artifact_matrix[
                    segment.artifact_channel_indices,
                    epoch_index,
                ]
                artifact_clean_fraction = float(np.mean(artifact_clean))

        clean_fraction = min(
            float(signal_features["signal_quality"]),
            artifact_clean_fraction,
        )
        is_clean = clean_fraction >= minimum_clean_channel_fraction
        time_to_n2_s = segment.stable_n2_onset_s - midpoint_absolute_s

        row: dict[str, float | int | str | bool] = {
            "subject_id": segment.subject_id,
            "window_start_s": segment.segment_start_s + start_relative_s,
            "window_end_s": segment.segment_start_s + end_relative_s,
            "time_to_n2_min": time_to_n2_s / 60.0,
            "stage": stage_at(segment.annotations, midpoint_absolute_s),
            "signal_quality": clean_fraction,
            "is_clean": is_clean,
            "n2_within_5m": int(
                0 < time_to_n2_s
                <= float(config["epoching"]["prediction_horizon_seconds"])
            ),
            "pre_n2_eligible": bool(time_to_n2_s > 0),
        }
        row.update(signal_features)
        row["signal_quality"] = clean_fraction
        row["is_clean"] = is_clean
        if auxiliary_data is not None:
            auxiliary_window = auxiliary_data[:, start:stop]
            row["eog_peak_to_peak_uv"] = (
                float(
                    np.median(
                        np.ptp(auxiliary_window[eog_indices], axis=-1) * 1e6
                    )
                )
                if eog_indices and auxiliary_window.shape[1] > 0
                else np.nan
            )
            row["chin_emg_rms_uv"] = (
                float(
                    np.median(
                        np.sqrt(
                            np.mean(
                                auxiliary_window[emg_indices] ** 2,
                                axis=-1,
                            )
                        )
                        * 1e6
                    )
                )
                if emg_indices and auxiliary_window.shape[1] > 0
                else np.nan
            )

        rows.append(row)

    features = pd.DataFrame(rows)
    history_windows = max(
        3,
        int(
            round(
                float(config["epoching"]["slope_history_seconds"])
                / step_seconds
            )
        ),
    )
    for column in CORE_FEATURES:
        features[f"{column}_slope_1m"] = (
            features[column]
            .rolling(history_windows, min_periods=3)
            .apply(
                lambda values: _past_slope_per_minute(
                    np.asarray(values),
                    step_seconds,
                ),
                raw=False,
            )
        )

    baseline_end = features["window_start_s"].min() + 5 * 60
    baseline_mask = (
        (features["window_start_s"] <= baseline_end)
        & features["is_clean"]
    )
    for column in CORE_FEATURES:
        center = float(features.loc[baseline_mask, column].median())
        mad = float(
            np.median(np.abs(features.loc[baseline_mask, column] - center))
        )
        scale = 1.4826 * mad
        if not np.isfinite(scale) or scale < 1e-12:
            scale = float(features.loc[baseline_mask, column].std(ddof=0))
        features[f"{column}_baseline_z"] = (
            (features[column] - center) / scale if scale > 0 else 0.0
        )
    return features


def detect_spindles(
    segment: SubjectSegment,
) -> pd.DataFrame:
    """Detect central sleep spindles for descriptive N2 validation only."""
    import yasa

    central = [channel for channel in ("C3", "C4", "Cz") if channel in segment.raw.ch_names]
    if not central:
        return pd.DataFrame()
    data_uv = segment.raw.copy().pick(central).get_data() * 1e6
    detector = yasa.spindles_detect(
        data_uv,
        sf=float(segment.raw.info["sfreq"]),
        ch_names=central,
        freq_sp=(12, 16),
        remove_outliers=True,
        verbose=False,
    )
    if detector is None:
        return pd.DataFrame()
    summary = detector.summary()
    summary["subject_id"] = segment.subject_id
    summary["absolute_start_s"] = summary["Start"] + segment.segment_start_s
    summary["time_to_n2_min"] = (
        segment.stable_n2_onset_s - summary["absolute_start_s"]
    ) / 60.0
    return summary
