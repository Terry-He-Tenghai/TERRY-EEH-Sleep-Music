from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from .contracts import MusicCommand, StateUpdate
from .music_engine.scheduler import MusicParameterFrame, MusicScheduler


class MusicMode(str, Enum):
    ANTI_HYPERAROUSAL = "anti_hyperarousal"
    ALPHA_STABILIZATION = "alpha_stabilization"
    THETA_TRANSITION = "theta_transition"
    MICRO_AROUSAL_REPAIR = "micro_arousal_repair"
    SLEEP_PROTECTION = "sleep_protection"


@dataclass(frozen=True)
class MusicPipeline:
    mode: MusicMode
    title: str
    style: str
    negative_tags: str
    duration_seconds: int | None
    generate_with_suno: bool
    target_volume: int


MUSIC_PIPELINES = {
    MusicMode.ANTI_HYPERAROUSAL: MusicPipeline(
        mode=MusicMode.ANTI_HYPERAROUSAL,
        title="Low Information Sleep Ambient",
        style=(
            "60 BPM sleep-inducing ambient, instrumental, warm soft pads, "
            "very low melodic complexity, slow attack, long sustain, low "
            "spectral brightness, consonant harmony, minimal changes, gentle "
            "breathing-like dynamics, seamless loop"
        ),
        negative_tags=(
            "vocals, drums, sudden transients, bright leads, complex melody, "
            "abrupt harmony, loud dynamics"
        ),
        duration_seconds=180,
        generate_with_suno=True,
        target_volume=45,
    ),
    MusicMode.ALPHA_STABILIZATION: MusicPipeline(
        mode=MusicMode.ALPHA_STABILIZATION,
        title="Predictable Pre-Sleep Warmth",
        style=(
            "52 BPM calming pre-sleep ambient, instrumental, soft low-register "
            "piano and warm pads, sparse notes, stable tonal center, gentle "
            "consonant harmony, low dynamic range, slow fade in and fade out, "
            "peaceful and predictable"
        ),
        negative_tags=(
            "vocals, percussion, bright timbre, surprise, syncopation, "
            "dramatic build, sudden transitions"
        ),
        duration_seconds=180,
        generate_with_suno=True,
        target_volume=38,
    ),
    MusicMode.THETA_TRANSITION: MusicPipeline(
        mode=MusicMode.THETA_TRANSITION,
        title="Low-Salience Sleep Transition",
        style=(
            "near-beatless sleep onset soundscape with a 40 to 45 BPM implied "
            "pulse, instrumental, no melody, deep warm drone, soft filtered "
            "noise, extremely slow harmonic movement, very low brightness, "
            "long reverb tail, gradual fading"
        ),
        negative_tags=(
            "vocals, percussion, melody, hooks, rhythmic accents, bright sound, "
            "novelty, sudden changes"
        ),
        duration_seconds=180,
        generate_with_suno=True,
        target_volume=28,
    ),
    MusicMode.MICRO_AROUSAL_REPAIR: MusicPipeline(
        mode=MusicMode.MICRO_AROUSAL_REPAIR,
        title="Brief Sleep Recovery Cue",
        style=(
            "very soft 15-second sleep recovery sound cue, instrumental, warm "
            "brown-noise-like texture, ultra-low dynamic range, familiar and "
            "non-intrusive, very slow fade in and fade out"
        ),
        negative_tags=(
            "vocals, melody, rhythm, percussion, transient, bright sound, "
            "volume jump"
        ),
        duration_seconds=15,
        generate_with_suno=True,
        target_volume=18,
    ),
    MusicMode.SLEEP_PROTECTION: MusicPipeline(
        mode=MusicMode.SLEEP_PROTECTION,
        title="Sleep Protection",
        style="silence or stable very-low-volume brown noise",
        negative_tags="tonal changes, rhythm, melody, transients",
        duration_seconds=None,
        generate_with_suno=False,
        target_volume=0,
    ),
}


@dataclass(frozen=True)
class PolicyThresholds:
    decision_interval_seconds: float = 30.0
    confirmations_required: int = 2
    minimum_mode_dwell_seconds: float = 60.0
    minimum_signal_quality: float = 0.75
    ignore_signal_quality: bool = False
    n1_probability: float = 0.55
    n2_probability: float = 0.65
    future_n2_probability: float = 0.65
    relaxed_alpha_z: float = 0.5
    relaxed_beta_z: float = 0.0
    transition_theta_z: float = 0.5
    micro_arousal_beta_z: float = 2.0
    micro_arousal_w_probability: float = 0.45
    micro_arousal_cooldown_seconds: float = 120.0
    crossfade_seconds: float = 25.0
    bpm: float = 60.0
    phrase_beats: int = 16

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "PolicyThresholds":
        music = config.get("music", {})
        values = dict(music.get("policy", {}))
        for key in ("bpm", "phrase_beats"):
            if key in music and key not in values:
                values[key] = music[key]
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})


class FiveModeMusicController:
    """Convert smoothed EEG state updates into sparse event-driven music commands."""

    def __init__(
        self,
        thresholds: PolicyThresholds | None = None,
    ) -> None:
        self.thresholds = thresholds or PolicyThresholds()
        self.current_mode = MusicMode.ANTI_HYPERAROUSAL
        self.pending_mode: MusicMode | None = None
        self.pending_count = 0
        self.last_decision_s = -np.inf
        self.last_mode_change_s = -np.inf
        self.last_micro_arousal_s = -np.inf
        self.initial_play_emitted = False
        self.probability_history: deque[
            tuple[float, dict[str, float]]
        ] = deque()
        self.scheduler = MusicScheduler(
            bpm=self.thresholds.bpm,
            phrase_beats=self.thresholds.phrase_beats,
            confirmations_required=self.thresholds.confirmations_required,
            minimum_dwell_seconds=self.thresholds.minimum_mode_dwell_seconds,
            smoothing_seconds=self.thresholds.decision_interval_seconds,
            minimum_signal_quality=self.thresholds.minimum_signal_quality,
        )
        self.last_parameter_frame: MusicParameterFrame | None = None

    @staticmethod
    def _feature(state: StateUpdate, name: str) -> float | None:
        value = state.interpretable_features.get(name)
        return float(value) if value is not None and np.isfinite(value) else None

    def _smoothed_probabilities(self) -> dict[str, float] | None:
        if not self.probability_history:
            return None
        stages = ("W", "N1", "N2")
        return {
            stage: float(
                np.mean(
                    [
                        probabilities.get(stage, 0.0)
                        for _, probabilities in self.probability_history
                    ]
                )
            )
            for stage in stages
        }

    def _micro_arousal(self, state: StateUpdate) -> bool:
        if self.current_mode not in {
            MusicMode.THETA_TRANSITION,
            MusicMode.SLEEP_PROTECTION,
        }:
            return False
        beta_z = self._feature(state, "frontal_beta_z")
        probabilities = state.aasm_state_probabilities or {}
        return bool(
            beta_z is not None
            and beta_z >= self.thresholds.micro_arousal_beta_z
            and probabilities.get("W", 0.0)
            >= self.thresholds.micro_arousal_w_probability
            and state.window_end_s - self.last_micro_arousal_s
            >= self.thresholds.micro_arousal_cooldown_seconds
        )

    def _candidate_mode(
        self,
        state: StateUpdate,
        probabilities: dict[str, float],
    ) -> MusicMode:
        n2_probability = probabilities.get("N2", 0.0)
        n1_probability = probabilities.get("N1", 0.0)
        w_probability = probabilities.get("W", 0.0)
        future_n2 = state.n2_within_5m_probability or 0.0
        theta_z = self._feature(state, "central_theta_z")
        alpha_z = self._feature(state, "posterior_alpha_z")
        beta_z = self._feature(state, "frontal_beta_z")

        if n2_probability >= self.thresholds.n2_probability:
            return MusicMode.SLEEP_PROTECTION
        if (
            n1_probability >= self.thresholds.n1_probability
            or (
                future_n2 >= self.thresholds.future_n2_probability
                and theta_z is not None
                and theta_z >= self.thresholds.transition_theta_z
            )
        ):
            return MusicMode.THETA_TRANSITION
        if (
            w_probability >= 0.5
            and alpha_z is not None
            and beta_z is not None
            and alpha_z >= self.thresholds.relaxed_alpha_z
            and beta_z <= self.thresholds.relaxed_beta_z
        ):
            return MusicMode.ALPHA_STABILIZATION
        return MusicMode.ANTI_HYPERAROUSAL

    def _mode_command(
        self,
        mode: MusicMode,
        reason: str,
        initial: bool = False,
    ) -> MusicCommand:
        pipeline = MUSIC_PIPELINES[mode]
        if mode == MusicMode.SLEEP_PROTECTION:
            action = "fade_out"
        else:
            action = "play" if initial else "crossfade"
        parameters = {
            "mode": mode.value,
            "target_volume": pipeline.target_volume,
            "crossfade_seconds": self.thresholds.crossfade_seconds,
        }
        if self.last_parameter_frame is not None:
            parameters.update(self.last_parameter_frame.to_parameters())
        return MusicCommand(
            action=action,
            parameters=parameters,
            reason=reason,
        )

    def _hold_command(
        self,
        reason: str,
        candidate_mode: MusicMode | None = None,
    ) -> MusicCommand:
        parameters: dict[str, float | str] = {"mode": self.current_mode.value}
        if candidate_mode is not None:
            parameters["candidate_mode"] = candidate_mode.value
        if self.last_parameter_frame is not None:
            parameters.update(self.last_parameter_frame.to_parameters())
        return MusicCommand(action="hold", parameters=parameters, reason=reason)

    def update(self, state: StateUpdate) -> MusicCommand:
        self.last_parameter_frame = self.scheduler.update(state)
        # TODO: 电极质量恢复后把 ignore_signal_quality 改回 false
        if not self.thresholds.ignore_signal_quality and (
            state.status != "ok"
            or state.signal_quality < self.thresholds.minimum_signal_quality
        ):
            return self._hold_command(
                f"hold while EEG state is {state.status}"
            )
        if state.aasm_state_probabilities is not None:
            self.probability_history.append(
                (state.window_end_s, state.aasm_state_probabilities)
            )
            earliest = (
                state.window_end_s
                - self.thresholds.decision_interval_seconds
            )
            while (
                self.probability_history
                and self.probability_history[0][0] < earliest
            ):
                self.probability_history.popleft()

        if self._micro_arousal(state):
            self.last_micro_arousal_s = state.window_end_s
            pipeline = MUSIC_PIPELINES[MusicMode.MICRO_AROUSAL_REPAIR]
            parameters: dict[str, float | str] = {
                "mode": MusicMode.MICRO_AROUSAL_REPAIR.value,
                "target_volume": pipeline.target_volume,
            }
            if self.last_parameter_frame is not None:
                parameters.update(self.last_parameter_frame.to_parameters())
            return MusicCommand(
                action="overlay",
                parameters=parameters,
                reason="clean frontal-beta burst after sleep transition",
            )

        if not self.initial_play_emitted:
            self.initial_play_emitted = True
            self.last_mode_change_s = state.window_end_s
            return self._mode_command(
                self.current_mode,
                "start with the safe low-information wake track",
                initial=True,
            )

        if (
            state.window_end_s - self.last_decision_s
            < self.thresholds.decision_interval_seconds
        ):
            return self._hold_command(
                "waiting for the next 30-second policy decision"
            )
        self.last_decision_s = state.window_end_s
        probabilities = self._smoothed_probabilities()
        if probabilities is None:
            return self._hold_command(
                "state probabilities are still warming up"
            )

        candidate = self._candidate_mode(state, probabilities)
        if candidate == self.current_mode:
            self.pending_mode = None
            self.pending_count = 0
            return self._hold_command(
                "current control mode remains supported"
            )
        if candidate != self.pending_mode:
            self.pending_mode = candidate
            self.pending_count = 1
        else:
            self.pending_count += 1
        if self.pending_count < self.thresholds.confirmations_required:
            return self._hold_command(
                "candidate mode requires another confirmation",
                candidate_mode=candidate,
            )
        if (
            state.window_end_s - self.last_mode_change_s
            < self.thresholds.minimum_mode_dwell_seconds
        ):
            return self._hold_command(
                "minimum mode dwell time has not elapsed"
            )

        self.current_mode = candidate
        self.pending_mode = None
        self.pending_count = 0
        self.last_mode_change_s = state.window_end_s
        return self._mode_command(
            candidate,
            "smoothed EEG state confirmed a control-mode transition",
        )
