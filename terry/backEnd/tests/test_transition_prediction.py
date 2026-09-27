from pathlib import Path

import numpy as np
import pandas as pd

from anphy_sleep.config import load_config
from anphy_sleep.modeling import PREDICTION_FEATURES
from anphy_sleep.transition_prediction import run_continuous_prediction


def test_record_start_prediction_and_ablation_outputs(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
    rng = np.random.default_rng(42)
    frames = []
    for subject_index in range(3):
        time_to_n2 = np.linspace(12, 0.1, 120)
        data = pd.DataFrame(
            {
                feature: rng.normal(size=len(time_to_n2))
                for feature in PREDICTION_FEATURES
            }
        )
        progress = (12 - time_to_n2) / 3
        data["central_theta_log"] += progress
        data["central_sigma_log"] += progress
        data["frontal_beta_log"] -= progress
        data["posterior_alpha_log"] -= progress
        data["subject_id"] = f"S{subject_index}"
        data["window_start_s"] = np.arange(len(data)) * 6.0
        data["window_end_s"] = data["window_start_s"] + 6.0
        data["time_to_n2_min"] = time_to_n2
        data["n2_within_5m"] = (time_to_n2 <= 5).astype(int)
        data["pre_n2_eligible"] = True
        data["is_clean"] = True
        data["stage"] = np.where(
            time_to_n2 > 7,
            "W",
            np.where(time_to_n2 > 2, "N1", "N2"),
        )
        frames.append(data)

    summary, events = run_continuous_prediction(
        pd.concat(frames, ignore_index=True),
        config,
        tmp_path,
    )

    assert {
        "time_only",
        "stage_oracle",
        "static_eeg",
        "dynamic_eeg",
        "dynamic_eeg_plus_time",
        "random_forest_dynamic",
        "svm_dynamic",
    } == set(summary["model"])
    assert events["subject_id"].nunique() == 3
    assert (
        tmp_path / "models" / "future_n2_logistic_continuous.joblib"
    ).exists()
