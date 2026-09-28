"""Low-dependency EEG fallback classification for live demonstrations.

This is an engineering fallback, not a validated sleep-stage model. It converts
spectral balance from any finite EEG channels into a normalized W/N1/N2
probability vector so downstream music control can keep running while the
trained, montage-specific model is warming up or has insufficient channels.
"""
from typing import Any

import numpy as np
from scipy.signal import welch


STAGES = ("W", "N1", "N2")


def sanitize_channels(samples_uv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Keep every channel containing usable finite samples and fill local gaps."""
    values = np.asarray(samples_uv, dtype=float)
    if values.ndim != 2 or values.shape[1] < 2:
        raise ValueError("fallback EEG window is too short")
    clean = []
    mask = np.zeros(values.shape[0], dtype=bool)
    for index, row in enumerate(values):
        finite = np.isfinite(row)
        # Require actual varying observations, not a handful of points expanded
        # into a window, a disconnected flatline, or constant ADC saturation.
        observed = row[finite]
        if observed.size < max(2, int(np.ceil(row.size * .2))):
            continue
        if np.max(np.abs(observed)) > 1e9:
            continue  # impossible uV values; protect PSD arithmetic
        if np.ptp(observed) <= 1e-6 or np.mean(np.abs(np.diff(observed)) <= 1e-6) >= .98:
            continue
        positions = np.arange(row.size)
        clean.append(np.interp(positions, positions[finite], observed))
        mask[index] = True
    return (np.asarray(clean, dtype=float) if clean else np.empty((0, values.shape[1])), mask)


def classify_window(samples_uv: np.ndarray, sample_rate_hz: float) -> tuple[dict[str, float], dict[str, float]]:
    """Return fallback probabilities and auditable spectral features.

    At least one varying channel with 20% finite observations is required.
    This is an availability check, not validation that a noisy signal is EEG.
    """
    values, _ = sanitize_channels(samples_uv)
    if values.shape[0] == 0:
        raise ValueError("fallback EEG has no usable channels")
    centered = values - np.mean(values, axis=1, keepdims=True)
    frequencies, psd = welch(
        centered,
        fs=float(sample_rate_hz),
        window="hann",
        nperseg=min(int(2 * sample_rate_hz), centered.shape[1]),
        noverlap=min(int(sample_rate_hz), centered.shape[1] // 2),
        detrend="constant",
        axis=-1,
    )

    def power(low: float, high: float) -> float:
        mask = (frequencies >= low) & (frequencies < high)
        if not np.any(mask):
            return 0.0
        return float(np.mean(np.trapezoid(psd[:, mask], frequencies[mask], axis=-1)))

    delta = power(0.5, 4.0)
    theta = power(4.0, 8.0)
    alpha = power(8.0, 12.0)
    sigma = power(12.0, 16.0)
    beta = power(13.0, 30.0)
    total = max(power(0.5, 30.0), np.finfo(float).eps)
    delta_ratio = delta / total
    theta_ratio = theta / total
    alpha_ratio = alpha / total
    sigma_ratio = sigma / total
    beta_ratio = beta / total

    # Soft scores are intentionally broad: the fallback provides a stable
    # control signal, while the event marks it as heuristic/degraded.
    wake_score = 1.4 * beta_ratio + 0.8 * alpha_ratio - 0.7 * delta_ratio
    n2_score = 1.5 * delta_ratio + 1.1 * sigma_ratio + 0.5 * theta_ratio - 0.8 * beta_ratio
    n1_score = 0.8 * theta_ratio + 0.4 * alpha_ratio - 0.2 * abs(delta_ratio - beta_ratio)
    logits = np.asarray([wake_score, n1_score, n2_score], dtype=float)
    logits = (logits - np.mean(logits)) * 5.0
    probabilities = np.exp(logits - np.max(logits))
    probabilities /= max(float(np.sum(probabilities)), np.finfo(float).eps)
    return (
        {stage: float(value) for stage, value in zip(STAGES, probabilities, strict=True)},
        {
            "delta_ratio": float(delta_ratio),
            "theta_ratio": float(theta_ratio),
            "alpha_ratio": float(alpha_ratio),
            "sigma_ratio": float(sigma_ratio),
            "beta_ratio": float(beta_ratio),
            "finite_channel_count": float(values.shape[0]),
        },
    )
