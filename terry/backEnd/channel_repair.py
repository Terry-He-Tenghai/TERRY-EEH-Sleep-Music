"""Experimental Web-only mean imputation; no validation of sleep accuracy.

Assess complete raw windows in microvolts. Optional model-matched filtering
and linear detrending are used for QC only, not to overwrite measured EEG.
Raw flatline and plateau checks remain independent of filtering.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import detrend, sosfilt


def repair_channels(samples: np.ndarray, names: tuple[str, ...], amplitude_limit: float,
                    minimum_channels: int = 8, *, filter_sos=None,
                    sample_rate_hz: int = 250) -> tuple[np.ndarray | None, dict]:
    if samples.ndim != 2 or samples.shape[0] != len(names) or samples.shape[1] < 2:
        raise ValueError("Invalid channel repair window")
    good = np.zeros(len(names), dtype=bool)
    diagnostics = []
    for i, name in enumerate(names):
        values = samples[i]
        item = {"channel": name, "valid": False, "reason": "nonfinite",
                "raw_peak_to_peak_uv": None, "detrended_range_uv": None,
                "flat_fraction": None, "spike_fraction": None}
        if np.isfinite(values).all():
            centered = detrend(values, type="linear")
            low, high = np.quantile(centered, [.01, .99])
            spread = float(high - low)
            std = float(np.std(values))
            flat = float(np.mean(np.abs(np.diff(values)) <= 1e-6))
            assessed = centered
            if filter_sos is not None:
                # QC only: discard the initial one-second causal-filter transient.
                # Keep original samples for the model's own continuous filter.
                assessed = sosfilt(filter_sos, centered)[sample_rate_hz:]
                if assessed.size < sample_rate_hz:
                    raise ValueError("Filtered QC requires at least two seconds of data")
            filtered_spread = float(np.diff(np.quantile(assessed, [.01, .99]))[0])
            spikes = float(np.mean(np.abs(assessed - np.median(assessed)) > amplitude_limit))
            # A robust range tolerates isolated transients and slow linear drift,
            # while plateau and repeated large-artifact checks remain explicit.
            reason = ("flatline" if std < .1 or flat >= .8 else
                      "repeated_plateau" if filter_sos is not None and flat >= .02 else
                      "excessive_amplitude" if filtered_spread > amplitude_limit else
                      "repeated_artifacts" if spikes > .02 else "valid")
            good[i] = reason == "valid"
            item.update(valid=bool(good[i]), reason=reason,
                        raw_peak_to_peak_uv=float(np.ptp(values)),
                        detrended_range_uv=spread, flat_fraction=flat, spike_fraction=spikes)
            item["assessed_range_uv"] = filtered_spread
        diagnostics.append(item)
    count = int(good.sum())
    details = {
        "method": "available_channel_mean", "experimental": True,
        "quality_method": ("model_filter_1_99_percentile_with_raw_flatline_guard" if filter_sos is not None
                           else "linear_detrend_1_99_percentile_with_flatline_guard"),
        "valid_channels": [name for name, valid in zip(names, good) if valid],
        "imputed_channels": [name for name, valid in zip(names, good) if not valid],
        "valid_fraction": count / len(names), "minimum_channels": minimum_channels,
        "usable": count >= minimum_channels, "channels": diagnostics,
    }
    if count < minimum_channels:
        return None, details
    repaired = samples.copy()
    # Preserve measured signals. Mean imputation is zero after average reference;
    # downstream regional features explicitly exclude these synthetic channels.
    repaired[~good] = samples[good].mean(axis=0)
    return repaired, details
