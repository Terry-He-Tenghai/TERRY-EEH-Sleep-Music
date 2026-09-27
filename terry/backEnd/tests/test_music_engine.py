from pathlib import Path

import numpy as np

from anphy_sleep.contracts import StateUpdate
from anphy_sleep.music_engine import (
    MusicScheduler,
    MusicState,
    WaveformParameters,
    generate_midi_plan,
    mix_layers,
    preset_gains,
    process_waveform,
    quality_report,
    write_midi_file,
)


def _state(time_s: float, n1: float = 0.1, n2: float = 0.02, quality: float = 1.0, status: str = "ok") -> StateUpdate:
    return StateUpdate(
        session_id="music-test",
        window_end_s=time_s,
        signal_quality=quality,
        status=status,
        baseline_ready=True,
        n2_within_5m_probability=0.7 if n1 > 0.5 else 0.1,
        aasm_state_probabilities={"W": 1.0 - n1 - n2, "N1": n1, "N2": n2},
        interpretable_features={"central_theta_z": 1.0 if n1 > 0.5 else 0.0},
    )


def test_midi_plan_is_deterministic_and_constrained() -> None:
    first = generate_midi_plan("M1", seed=7, bars=4)
    second = generate_midi_plan("M1", seed=7, bars=4)
    assert first == second
    report = quality_report(first, bars=4)
    assert report.passes
    assert report.large_intervals == 0
    assert report.note_count > 0


def test_midi_file_is_reproducible(tmp_path: Path) -> None:
    notes = generate_midi_plan("M2", seed=9, bars=2)
    first_path = write_midi_file(notes, tmp_path / "first.mid")
    second_path = write_midi_file(notes, tmp_path / "second.mid")
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first_path.read_bytes()[:4] == b"MThd"


def test_scheduler_waits_for_confirmation_and_phrase_boundary() -> None:
    scheduler = MusicScheduler(confirmations_required=2, minimum_dwell_seconds=0)
    assert scheduler.update(_state(0)).music_state == MusicState.M1
    first_transition = scheduler.update(_state(30, n1=0.7, n2=0.05))
    assert first_transition.music_state == MusicState.M1
    second_transition = scheduler.update(_state(60, n1=0.7, n2=0.05))
    assert second_transition.music_state == MusicState.M2
    assert second_transition.phrase_boundary is True
    assert second_transition.target_state == MusicState.M2


def test_scheduler_freezes_on_invalid_signal() -> None:
    scheduler = MusicScheduler()
    frame = scheduler.update(_state(0, quality=0.1, status="signal_invalid"))
    assert frame.frozen is True
    assert frame.fallback is True
    assert frame.gains == preset_gains(MusicState.M1)


def test_waveform_processing_is_bounded_and_reports_metrics() -> None:
    sample_rate = 8_000
    time = np.arange(sample_rate) / sample_rate
    audio = np.vstack([
        0.8 * np.sin(2 * np.pi * 300 * time),
        0.8 * np.sin(2 * np.pi * 600 * time),
    ])
    rendered, metrics = process_waveform(
        mix_layers({"pad": audio}, preset_gains(MusicState.M1)),
        sample_rate,
        WaveformParameters(brightness=0.2, master_gain=0.8),
    )
    assert rendered.shape == audio.shape
    assert np.max(np.abs(rendered)) <= 1.0
    assert metrics.peak <= 1.0
    assert metrics.spectral_centroid_hz > 0
