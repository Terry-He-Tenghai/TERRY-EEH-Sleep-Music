"""ANPHY-Sleep 16-channel sleep-onset analysis."""

from .contracts import EegChunk, MusicCommand, RealtimeOutput, StateUpdate
from .music import MusicController, NoOpMusicController
from .music_policy import FiveModeMusicController, MusicMode
from .music_runtime import AdaptiveMusicRuntime, build_music_runtime
from .adaptive_music import AdaptiveMusicPolicy, AdaptiveMusicTarget, SunoRole, select_suno_track
from .music_engine import (
    LayerGains,
    MIDIQualityReport,
    MidiNote,
    MotifVariation,
    MusicLayer,
    MusicParameterFrame,
    MusicScheduler,
    MusicState,
    WaveformMetrics,
    WaveformParameters,
    generate_midi_plan,
    mix_layers,
    process_waveform,
    quality_report,
    render_symbolic_layer,
    write_midi_file,
)
from .streaming import RealtimeSession
from .suno import SunoClient, TrackRepository

__version__ = "0.1.0"

__all__ = [
    "EegChunk",
    "MusicCommand",
    "MusicController",
    "MusicMode",
    "NoOpMusicController",
    "FiveModeMusicController",
    "AdaptiveMusicRuntime",
    "AdaptiveMusicPolicy", "AdaptiveMusicTarget", "SunoRole", "select_suno_track",
    "build_music_runtime",
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
    "process_waveform",
    "quality_report",
    "render_symbolic_layer",
    "write_midi_file",
    "RealtimeOutput",
    "RealtimeSession",
    "StateUpdate",
    "SunoClient",
    "TrackRepository",
]
