from pathlib import Path

import numpy as np
import pandas as pd

from anphy_sleep.config import load_config
from anphy_sleep.staging import (
    STAGE_DYNAMIC_FEATURES,
    run_stage_classification,
    run_stage_physiology,
)


def test_stage_loso_and_physiology_outputs(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
    rng = np.random.default_rng(42)
    rows = []
    stage_effect = {"W": 0.0, "N1": 1.0, "N2": 2.0}
    for subject_index in range(3):
        for epoch, stage in enumerate(["W", "W", "N1", "N1", "N2", "N2"]):
            start = epoch * 30.0
            row = {
                feature: float(
                    stage_effect[stage]
                    + rng.normal(0, 0.05)
                    + subject_index * 0.02
                )
                for feature in STAGE_DYNAMIC_FEATURES
            }
            row.update(
                {
                    "subject_id": f"S{subject_index}",
                    "window_start_s": start,
                    "window_end_s": start + 6.0,
                    "stage": stage,
                    "is_clean": True,
                }
            )
            rows.append(row)
    features = pd.DataFrame(rows)

    summary, confusion = run_stage_classification(
        features,
        config,
        tmp_path,
    )
    epochs = pd.read_parquet(tmp_path / "stage_epoch_features.parquet")
    _, contrasts = run_stage_physiology(epochs, tmp_path)

    assert set(summary["model"]) == {
        "logistic_static",
        "logistic_dynamic",
        "random_forest_dynamic",
        "svm_dynamic",
    }
    assert confusion.shape == (3, 3)
    assert len(contrasts) == 10
    assert (tmp_path / "models" / "sleep_state_logistic_30s.joblib").exists()
