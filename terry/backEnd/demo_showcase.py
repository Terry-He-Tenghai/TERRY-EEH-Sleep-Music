"""Deterministic presentation script, explicitly unrelated to ML inference."""
from __future__ import annotations

import numpy as np

STAGES = ('W', 'N1', 'N2', 'W')
PROBABILITIES = {
    'W': {'W': .94, 'N1': .04, 'N2': .02},
    'N1': {'W': .08, 'N1': .86, 'N2': .06},
    'N2': {'W': .02, 'N1': .08, 'N2': .90},
}
MUSIC_STATES = {'W': 'M1', 'N1': 'M2', 'N2': 'M3'}


def showcase_stage(elapsed_s: float) -> str:
    """Four 24-second segments; each 96-second script starts over."""
    return STAGES[int(elapsed_s // 24) % len(STAGES)]


def showcase_waveform(times: np.ndarray, channel: int, phase: float) -> np.ndarray:
    """Bounded alpha/theta/delta mix on the same sample clock as the script."""
    segment = (times // 24).astype(int) % 4
    alpha = np.asarray([14., 6., 2., 14.])[segment]
    theta = np.asarray([2., 14., 5., 2.])[segment]
    delta = np.asarray([2., 5., 18., 2.])[segment]
    return (alpha * np.sin(2 * np.pi * (8.0 + channel % 4) * times + phase)
            + theta * np.sin(2 * np.pi * 5.5 * times + phase)
            + delta * np.sin(2 * np.pi * 1.2 * times))
