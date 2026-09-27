from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import numpy as np


class MusicLayer(str, Enum):
    PAD = "pad"
    MELODY = "melody"
    BASS = "bass"
    TEXTURE = "texture"


class MusicState(str, Enum):
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"


@dataclass(frozen=True)
class LayerGains:
    """Linear gains for the four controllable music layers."""

    pad: float
    melody: float
    bass: float
    texture: float

    def as_dict(self) -> dict[str, float]:
        return {
            MusicLayer.PAD.value: self.pad,
            MusicLayer.MELODY.value: self.melody,
            MusicLayer.BASS.value: self.bass,
            MusicLayer.TEXTURE.value: self.texture,
        }

    def clamped(self) -> "LayerGains":
        values = {name: float(np.clip(value, 0.0, 1.0)) for name, value in self.as_dict().items()}
        return LayerGains(**values)


_PRESETS: dict[MusicState, LayerGains] = {
    MusicState.M1: LayerGains(pad=0.72, melody=0.34, bass=0.26, texture=0.16),
    MusicState.M2: LayerGains(pad=0.68, melody=0.16, bass=0.18, texture=0.11),
    MusicState.M3: LayerGains(pad=0.58, melody=0.0, bass=0.08, texture=0.08),
}


def preset_gains(state: MusicState | str) -> LayerGains:
    """Return a copyable, deterministic gain preset for M1/M2/M3."""
    return _PRESETS[MusicState(state)]


def mix_layers(
    layers: Mapping[MusicLayer | str, np.ndarray],
    gains: LayerGains,
) -> np.ndarray:
    """Mix mono or stereo layers, padding shorter layers with silence.

    All arrays must have shape ``(samples,)`` or ``(2, samples)``.  Mono and
    stereo inputs may be combined; mono is duplicated to both output channels.
    """
    if not layers:
        return np.zeros((2, 0), dtype=np.float32)
    prepared: dict[str, np.ndarray] = {}
    max_samples = 0
    for raw_name, raw_audio in layers.items():
        name = MusicLayer(raw_name).value
        audio = np.asarray(raw_audio, dtype=np.float64)
        if audio.ndim == 1:
            audio = np.vstack([audio, audio])
        if audio.ndim != 2 or audio.shape[0] != 2:
            raise ValueError("each music layer must have shape (samples,) or (2, samples)")
        prepared[name] = audio
        max_samples = max(max_samples, audio.shape[1])
    output = np.zeros((2, max_samples), dtype=np.float64)
    gain_map = gains.clamped().as_dict()
    for name, audio in prepared.items():
        output[:, : audio.shape[1]] += audio * gain_map[name]
    return np.asarray(np.clip(output, -1.0, 1.0), dtype=np.float32)


def render_symbolic_layer(
    notes: list[object],
    sample_rate_hz: int,
    duration_seconds: float,
    voice: str,
    bpm: float = 60.0,
) -> np.ndarray:
    """Render a deliberately simple local sine-based preview of MIDI notes.

    This is a dependency-free preview renderer for repeatability tests and
    experiments.  It is not intended to replace a production-quality synth.
    """
    if sample_rate_hz <= 0 or duration_seconds <= 0 or bpm <= 0:
        raise ValueError("sample rate, duration, and bpm must be positive")
    total = int(round(sample_rate_hz * duration_seconds))
    result = np.zeros(total, dtype=np.float64)
    voice_offset = {"melody": 0.0, "bass": -12.0, "pad": -24.0}.get(voice, 0.0)
    for note in notes:
        if getattr(note, "voice", voice) != voice:
            continue
        start = max(0, int(round(float(note.start_beat) * 60.0 / bpm * sample_rate_hz)))
        length = max(1, int(round(float(note.duration_beats) * 60.0 / bpm * sample_rate_hz)))
        end = min(total, start + length)
        if end <= start:
            continue
        frequency = 440.0 * 2.0 ** ((float(note.midi_note) + voice_offset - 69.0) / 12.0)
        time_axis = np.arange(end - start, dtype=np.float64) / sample_rate_hz
        attack = min(len(time_axis), max(1, int(0.04 * sample_rate_hz)))
        release = min(len(time_axis), max(1, int(0.12 * sample_rate_hz)))
        envelope = np.ones(len(time_axis), dtype=np.float64)
        envelope[:attack] *= np.linspace(0.0, 1.0, attack)
        envelope[-release:] *= np.linspace(1.0, 0.0, release)
        amplitude = (float(note.velocity) / 127.0) * (0.18 if voice != "pad" else 0.10)
        result[start:end] += amplitude * envelope * np.sin(2.0 * np.pi * frequency * time_axis)
    return np.vstack([result, result]).astype(np.float32)
