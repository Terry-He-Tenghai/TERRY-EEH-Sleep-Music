from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from ..contracts import StateUpdate
from .layers import LayerGains, MusicState, preset_gains
from .midi import MotifVariation
from .waveform import WaveformParameters


@dataclass(frozen=True)
class MusicParameterFrame:
    """One auditable music-control frame derived from a StateUpdate."""

    music_state: MusicState
    target_state: MusicState
    phrase_index: int
    phrase_boundary: bool
    frozen: bool
    fallback: bool
    gains: LayerGains
    waveform: WaveformParameters
    motif_variation: MotifVariation
    reason: str

    def to_parameters(self) -> dict[str, float | str]:
        values: dict[str, float | str] = {
            "music_state": self.music_state.value,
            "target_music_state": self.target_state.value,
            "phrase_index": float(self.phrase_index),
            "phrase_boundary": float(self.phrase_boundary),
            "frozen": float(self.frozen),
            "fallback": float(self.fallback),
            "motif_variation": self.motif_variation.value,
            "engine_reason": self.reason,
        }
        values.update({f"layer_{key}_gain": value for key, value in self.gains.as_dict().items()})
        values.update(
            {
                "master_gain": self.waveform.master_gain,
                "brightness": self.waveform.brightness,
                "reverb_send": self.waveform.reverb_send,
                "stereo_width": self.waveform.stereo_width,
            }
        )
        return values


class MusicScheduler:
    """Smooth M1/M2/M3 targets and apply them only at phrase boundaries."""

    def __init__(
        self,
        bpm: float = 60.0,
        phrase_beats: int = 16,
        confirmations_required: int = 2,
        minimum_dwell_seconds: float = 20.0,
        smoothing_seconds: float = 30.0,
        minimum_signal_quality: float = 0.75,
    ) -> None:
        if bpm <= 0 or phrase_beats <= 0 or confirmations_required <= 0:
            raise ValueError("bpm, phrase_beats, and confirmations must be positive")
        self.bpm = float(bpm)
        self.phrase_beats = int(phrase_beats)
        self.confirmations_required = int(confirmations_required)
        self.minimum_dwell_seconds = float(minimum_dwell_seconds)
        self.smoothing_seconds = float(smoothing_seconds)
        self.minimum_signal_quality = float(minimum_signal_quality)
        self.current_state = MusicState.M1
        self.pending_state: MusicState | None = None
        self.pending_count = 0
        self.last_change_s = -np.inf
        self.last_phrase_index: int | None = None
        self.history: deque[tuple[float, dict[str, float]]] = deque()

    @staticmethod
    def _target(
        probabilities: dict[str, float],
        future_n2: float,
        theta_z: float | None,
    ) -> MusicState:
        if probabilities.get("N2", 0.0) >= 0.65:
            return MusicState.M3
        if probabilities.get("N1", 0.0) >= 0.55 or (
            future_n2 >= 0.65 and theta_z is not None and theta_z >= 0.5
        ):
            return MusicState.M2
        return MusicState.M1

    def _smooth(self, state: StateUpdate) -> dict[str, float]:
        probabilities = state.aasm_state_probabilities or {}
        self.history.append((state.window_end_s, probabilities))
        cutoff = state.window_end_s - self.smoothing_seconds
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()
        return {
            stage: float(np.mean([values.get(stage, 0.0) for _, values in self.history]))
            for stage in ("W", "N1", "N2")
        }

    def _waveform(self, music_state: MusicState) -> WaveformParameters:
        return {
            MusicState.M1: WaveformParameters(
                master_gain=0.80, brightness=0.50, reverb_send=0.18, stereo_width=0.72
            ),
            MusicState.M2: WaveformParameters(
                master_gain=0.68, brightness=0.30, reverb_send=0.28, stereo_width=0.58
            ),
            MusicState.M3: WaveformParameters(
                master_gain=0.52, brightness=0.14, reverb_send=0.38, stereo_width=0.42
            ),
        }[music_state]

    def update(self, state: StateUpdate) -> MusicParameterFrame:
        phrase_index = int(np.floor(max(0.0, state.window_end_s) * self.bpm / 60.0 / self.phrase_beats))
        phrase_boundary = self.last_phrase_index is None or phrase_index != self.last_phrase_index
        self.last_phrase_index = phrase_index
        invalid = state.status != "ok" or state.signal_quality < self.minimum_signal_quality
        if invalid:
            return MusicParameterFrame(
                music_state=self.current_state,
                target_state=self.current_state,
                phrase_index=phrase_index,
                phrase_boundary=phrase_boundary,
                frozen=True,
                fallback=True,
                gains=preset_gains(self.current_state),
                waveform=self._waveform(self.current_state),
                motif_variation=MotifVariation.REDUCED,
                reason=f"freeze music while EEG state is {state.status}",
            )
        probabilities = self._smooth(state)
        theta = state.interpretable_features.get("central_theta_z")
        theta_z = float(theta) if theta is not None and np.isfinite(theta) else None
        target = self._target(probabilities, state.n2_within_5m_probability or 0.0, theta_z)
        if target == self.current_state:
            self.pending_state = None
            self.pending_count = 0
        elif target != self.pending_state:
            self.pending_state = target
            self.pending_count = 1
        else:
            self.pending_count += 1
        if (
            self.pending_state is not None
            and self.pending_count >= self.confirmations_required
            and phrase_boundary
            and state.window_end_s - self.last_change_s >= self.minimum_dwell_seconds
        ):
            self.current_state = self.pending_state
            self.pending_state = None
            self.pending_count = 0
            self.last_change_s = state.window_end_s
        variation = {
            MusicState.M1: MotifVariation.COMPLETE,
            MusicState.M2: MotifVariation.REDUCED,
            MusicState.M3: MotifVariation.REDUCED,
        }[self.current_state]
        return MusicParameterFrame(
            music_state=self.current_state,
            target_state=target,
            phrase_index=phrase_index,
            phrase_boundary=phrase_boundary,
            frozen=False,
            fallback=False,
            gains=preset_gains(self.current_state),
            waveform=self._waveform(self.current_state),
            motif_variation=variation,
            reason=(
                "apply confirmed target at phrase boundary"
                if self.current_state == target
                else "hold current state until confirmation and phrase boundary"
            ),
        )
