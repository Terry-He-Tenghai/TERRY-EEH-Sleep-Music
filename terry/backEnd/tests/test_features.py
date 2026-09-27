from pathlib import Path

import mne
import numpy as np

from anphy_sleep.config import load_config
from anphy_sleep.features import extract_window_features
from anphy_sleep.io import read_sleep_annotations
from anphy_sleep.preprocess import SubjectSegment


def test_causal_window_features(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
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
    assert features["window_end_s"].is_monotonic_increasing
