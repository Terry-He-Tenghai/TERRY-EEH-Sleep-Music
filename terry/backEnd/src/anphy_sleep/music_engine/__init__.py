"""Deterministic, offline-first music rendering and control primitives.

This package deliberately depends only on local state and audio buffers.  It
never reads raw EEG; callers pass the already-produced :class:`StateUpdate`.
"""

from .layers import LayerGains, MusicLayer, MusicState, mix_layers, preset_gains, render_symbolic_layer
from .midi import (
    MIDIQualityReport,
    MidiNote,
    MotifVariation,
    generate_midi_plan,
    quality_report,
    write_midi_file,
)
from .scheduler import MusicParameterFrame, MusicScheduler
from .waveform import (
    WaveformMetrics,
    WaveformParameters,
    process_waveform,
)

__all__ = [
    "LayerGains",
    "MIDIQualityReport",
    "MidiNote",
    "MotifVariation",
    "MusicLayer",
    "MusicParameterFrame",
    "MusicScheduler",
    "MusicState",
    "WaveformMetrics",
    "WaveformParameters",
    "generate_midi_plan",
    "mix_layers",
    "preset_gains",
    "process_waveform",
    "quality_report",
    "render_symbolic_layer",
    "write_midi_file",
]
