"""Experimental mapping from the physical 16-channel cap to the legacy model."""

import numpy as np


CAP_ORDER = (
    "Fp1", "Fp2", "C3", "C4", "P7", "P8", "O1", "O2",
    "F7", "F8", "F3", "F4", "T7", "T8", "P3", "P4",
)
MODEL_ORDER = (
    "Fp1", "Fp2", "F3", "F4", "F7", "F8", "Fz", "C3",
    "C4", "Cz", "T7", "T8", "P3", "P4", "O1", "O2",
)
ESTIMATED_CHANNELS = ("Fz", "Cz")


def map_cap_to_model(samples: np.ndarray, channels: tuple[str, ...]) -> np.ndarray:
    """Preserve 14 measured sites and interpolate only the two absent midline sites."""
    if channels != CAP_ORDER or samples.ndim != 2 or samples.shape[0] != 16:
        raise ValueError("Expected all 16 physical cap channels in verified device order")
    by_name = dict(zip(channels, samples, strict=True))
    estimates = {"Fz": (by_name["F3"] + by_name["F4"]) / 2,
                 "Cz": (by_name["C3"] + by_name["C4"]) / 2}
    return np.stack([estimates[name] if name in estimates else by_name[name]
                     for name in MODEL_ORDER])
