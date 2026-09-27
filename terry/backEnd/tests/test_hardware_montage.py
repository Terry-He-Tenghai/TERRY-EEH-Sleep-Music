from pathlib import Path

import mne
import numpy as np

from anphy_sleep.config import load_config
from anphy_sleep.contracts import EegChunk
from anphy_sleep.features import extract_window_features
from anphy_sleep.io import read_sleep_annotations, select_target_channels
from anphy_sleep.preprocess import SubjectSegment
from anphy_sleep.streaming import RealtimeSession

from test_streaming import _model_bundles


HARDWARE_CHANNELS = [
    "C3",
    "C4",
    "Cz",
    "FC3",
    "FC4",
    "CP3",
    "CP4",
    "FCz",
    "CPz",
    "Fz",
    "P3",
    "Pz",
    "P4",
    "O1",
    "Oz",
    "O2",
]


def test_hardware_config_selects_cap_channels() -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.hardware.yaml")
    assert config["channels"]["target"] == HARDWARE_CHANNELS
    assert "Fp1" not in config["channels"]["target"]
    assert "T7" not in config["channels"]["target"]

    raw = mne.io.RawArray(
        np.zeros((len(HARDWARE_CHANNELS) + 2, 500)),
        mne.create_info([*HARDWARE_CHANNELS, "Fp1", "T7"], 250, "eeg"),
        verbose="ERROR",
    )
    selected, mapping = select_target_channels(
        raw,
        list(config["channels"]["target"]),
        dict(config["channels"].get("aliases", {})),
    )
    assert selected.ch_names == HARDWARE_CHANNELS
    assert mapping["FCz"] == "FCz"
    assert mapping["CPz"] == "CPz"


def test_hardware_window_features(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.hardware.yaml")
    channels = list(config["channels"]["target"])
    sfreq = 250
    seconds = 120
    time = np.arange(sfreq * seconds) / sfreq
    signals = np.vstack(
        [
            10e-6 * np.sin(2 * np.pi * (8 + index % 5) * time)
            for index in range(len(channels))
        ]
    )
    raw = mne.io.RawArray(
        signals,
        mne.create_info(channels, sfreq, "eeg"),
        verbose="ERROR",
    )
    annotation = tmp_path / "stages.txt"
    annotation.write_text(
        "W,0,30\nN1,30,30\nN2,60,30\nN2,90,30\n",
        encoding="utf-8",
    )
    segment = SubjectSegment(
        subject_id="EPCTLXX",
        raw=raw,
        auxiliary_raw=None,
        annotations=read_sleep_annotations(annotation),
        stable_n2_onset_s=60.0,
        segment_start_s=0.0,
        segment_end_s=120.0,
        channel_mapping={channel: channel for channel in channels},
        artifact_matrix=None,
        artifact_channel_indices=None,
    )
    features = extract_window_features(segment, config)
    assert not features.empty
    assert set(
        [
            "frontal_beta_log",
            "posterior_alpha_log",
            "central_theta_log",
            "posterior_alpha_theta_log_ratio_slope_1m",
            "n2_within_5m",
        ]
    ).issubset(features.columns)


def test_hardware_realtime_session_accepts_cap_channel_names(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.hardware.yaml")
    prediction_path, state_path = _model_bundles(tmp_path)
    session = RealtimeSession(
        config,
        prediction_path,
        state_path,
        session_id="hardware-session",
    )
    assert session.signal.target_channels == tuple(HARDWARE_CHANNELS)
    sfreq = float(config["signal"]["target_sfreq_hz"])
    rng = np.random.default_rng(0)
    time_s = np.arange(int(sfreq)) / sfreq
    samples = np.vstack(
        [
            10e-6 * np.sin(2 * np.pi * (8 + index % 5) * time_s)
            + rng.normal(0, 0.5e-6, size=len(time_s))
            for index in range(len(HARDWARE_CHANNELS))
        ]
    )
    outputs = session.push(
        EegChunk(
            timestamp_s=0.0,
            sample_rate_hz=sfreq,
            channel_names=tuple(HARDWARE_CHANNELS),
            samples=samples,
            session_id="hardware-session",
        )
    )
    assert outputs == []
