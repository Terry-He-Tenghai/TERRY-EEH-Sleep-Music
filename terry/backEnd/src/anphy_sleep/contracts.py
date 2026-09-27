from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class EegChunk:
    """One contiguous block of device EEG samples."""

    timestamp_s: float
    sample_rate_hz: float
    channel_names: tuple[str, ...]
    samples: np.ndarray
    unit: Literal["V", "uV"] = "V"
    session_id: str | None = None

    def validate(self) -> None:
        if self.samples.ndim != 2:
            raise ValueError("samples must have shape (channels, samples)")
        if self.samples.shape[0] != len(self.channel_names):
            raise ValueError("channel_names length does not match samples")
        if self.samples.shape[1] == 0:
            raise ValueError("EEG chunk cannot be empty")
        if not np.isfinite(self.samples).all():
            raise ValueError("EEG chunk contains non-finite samples")
        if not np.isfinite(self.timestamp_s):
            raise ValueError("timestamp_s must be finite")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.unit not in {"V", "uV"}:
            raise ValueError("unit must be 'V' or 'uV'")


@dataclass(frozen=True)
class StateUpdate:
    """Model output emitted for one causal analysis window."""

    session_id: str
    window_end_s: float
    signal_quality: float
    status: Literal["warming_up", "ok", "signal_invalid"]
    baseline_ready: bool
    n2_within_5m_probability: float | None
    aasm_state_probabilities: dict[str, float] | None
    interpretable_features: dict[str, float | None]
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MusicCommand:
    """Transport-neutral command returned by a music controller."""

    action: Literal[
        "none",
        "hold",
        "generate",
        "play",
        "crossfade",
        "overlay",
        "fade_out",
        "stop",
    ]
    parameters: dict[str, float | str]
    reason: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RealtimeOutput:
    """One state update paired with the downstream music decision."""

    state: StateUpdate
    music: MusicCommand

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.to_dict(),
            "music": self.music.to_dict(),
        }
