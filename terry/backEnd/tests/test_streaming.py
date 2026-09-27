from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier

from anphy_sleep.config import load_config
from anphy_sleep.contracts import EegChunk
from anphy_sleep.modeling import PREDICTION_FEATURES
from anphy_sleep.features import CORE_FEATURES
from anphy_sleep.streaming import OnlineFeatureState, RealtimeSession


def _model_bundles(tmp_path: Path) -> tuple[Path, Path]:
    matrix = pd.DataFrame(
        np.zeros((3, len(PREDICTION_FEATURES))),
        columns=PREDICTION_FEATURES,
    )
    prediction = DummyClassifier(strategy="prior").fit(matrix.iloc[:2], [0, 1])
    state = DummyClassifier(strategy="prior").fit(matrix, ["W", "N1", "N2"])
    prediction_path = tmp_path / "prediction.joblib"
    state_path = tmp_path / "state.joblib"
    joblib.dump(
        {
            "model": prediction,
            "features": PREDICTION_FEATURES,
            "target": "n2_within_5m",
        },
        prediction_path,
    )
    joblib.dump(
        {
            "model": state,
            "features": PREDICTION_FEATURES,
            "target": "aasm_state",
            "classes": ["N1", "N2", "W"],
        },
        state_path,
    )
    return prediction_path, state_path


def test_realtime_session_emits_causal_states_and_noop_music(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
    prediction_path, state_path = _model_bundles(tmp_path)
    session = RealtimeSession(
        config,
        prediction_path,
        state_path,
        session_id="test-session",
    )
    sfreq = float(config["signal"]["target_sfreq_hz"])
    channels = list(config["channels"]["target"])
    channels[channels.index("T7")] = "T3"
    channels[channels.index("T8")] = "T4"
    rng = np.random.default_rng(42)
    outputs = []
    for second in range(15):
        time_s = second + np.arange(int(sfreq)) / sfreq
        samples = np.vstack(
            [
                10e-6 * np.sin(2 * np.pi * (8 + index % 5) * time_s + index)
                + rng.normal(0, 0.5e-6, size=len(time_s))
                for index in range(len(channels))
            ]
        )
        outputs.extend(
            session.push(
                EegChunk(
                    timestamp_s=float(second),
                    sample_rate_hz=sfreq,
                    channel_names=tuple(channels),
                    samples=samples,
                    session_id="test-session",
                )
            )
        )

    assert [output.state.window_end_s for output in outputs] == [6.0, 9.0, 12.0, 15.0]
    assert [output.state.status for output in outputs[:2]] == [
        "warming_up",
        "warming_up",
    ]
    assert all(output.state.status == "ok" for output in outputs[2:])
    assert all(output.music.action == "none" for output in outputs)
    assert outputs[-1].state.n2_within_5m_probability == pytest.approx(0.5)
    assert outputs[-1].state.baseline_ready is False


def test_realtime_session_rejects_wrong_sample_rate(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
    prediction_path, state_path = _model_bundles(tmp_path)
    session = RealtimeSession(config, prediction_path, state_path)
    channels = tuple(config["channels"]["target"])
    with pytest.raises(ValueError, match="250 Hz"):
        session.push(
            EegChunk(
                timestamp_s=0.0,
                sample_rate_hz=200.0,
                channel_names=channels,
                samples=np.zeros((len(channels), 200)),
            )
        )


def test_online_baseline_freezes_after_five_minutes() -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
    state = OnlineFeatureState(config)
    enriched = {}
    for index, window_end_s in enumerate(np.arange(6.0, 303.0, 3.0)):
        features = {
            name: float(index + feature_index / 10)
            for feature_index, name in enumerate(CORE_FEATURES)
        }
        features.update({"signal_quality": 1.0, "is_clean": True})
        enriched = state.update(features, float(window_end_s))

    assert state.baseline_ready is True
    assert np.isfinite(enriched["frontal_beta_log_baseline_z"])
