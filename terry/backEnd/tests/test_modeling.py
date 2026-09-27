from pathlib import Path

import numpy as np
import pandas as pd

from anphy_sleep.config import load_config
from anphy_sleep.modeling import PREDICTION_FEATURES, run_loso_prediction


def test_loso_prediction_outputs(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
    rng = np.random.default_rng(42)
    frames = []
    for subject_index in range(3):
        time_to_n2 = np.linspace(10, -2, 96)
        data = pd.DataFrame(
            {
                feature: rng.normal(size=len(time_to_n2))
                for feature in PREDICTION_FEATURES
            }
        )
        data["central_theta_log"] += (10 - time_to_n2) / 3
        data["frontal_beta_log"] -= (10 - time_to_n2) / 3
        data["subject_id"] = f"S{subject_index}"
        data["window_start_s"] = np.arange(len(data)) * 3
        data["window_end_s"] = data["window_start_s"] + 6
        data["time_to_n2_min"] = time_to_n2
        data["n2_within_5m"] = ((time_to_n2 > 0) & (time_to_n2 <= 5)).astype(int)
        data["pre_n2_eligible"] = time_to_n2 > 0
        data["is_clean"] = True
        data["stage"] = np.select(
            [time_to_n2 > 7, time_to_n2 > 0],
            ["W", "N1"],
            default="N2",
        )
        frames.append(data)

    metrics, lead_times = run_loso_prediction(
        pd.concat(frames, ignore_index=True),
        config,
        tmp_path,
    )
    assert set(metrics["model"]) == {
        "logistic_regression",
        "random_forest",
        "svm",
    }
    assert lead_times["subject_id"].nunique() == 3
    assert (tmp_path / "models" / "logistic_regression.joblib").exists()
    assert (tmp_path / "models" / "sleep_state_logistic.joblib").exists()
