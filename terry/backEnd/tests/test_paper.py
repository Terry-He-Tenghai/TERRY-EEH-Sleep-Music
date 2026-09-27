from pathlib import Path

import pandas as pd

from anphy_sleep.config import load_config
from anphy_sleep.paper import build_paper_outputs


def test_build_paper_outputs(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.yaml")
    results = tmp_path / "results"
    processed = tmp_path / "processed"
    results.mkdir()
    processed.mkdir()
    config["data"]["results_dir"] = str(results)
    config["data"]["processed_dir"] = str(processed)

    pd.DataFrame(
        {
            "outcome": [
                "frontal_beta_log",
                "posterior_alpha_log",
                "central_theta_log",
            ],
            "cohen_dz": [-0.9, -0.7, 1.1],
            "cohen_dz_ci95_low": [-1.3, -1.1, 0.7],
            "cohen_dz_ci95_high": [-0.5, -0.3, 1.5],
        }
    ).to_csv(results / "paired_effect_sizes.csv", index=False)
    pd.DataFrame(
        {
            "model": ["logistic_regression", "random_forest", "svm"],
            "auc_mean": [0.81, 0.79, 0.80],
            "balanced_accuracy_mean": [0.72, 0.71, 0.71],
            "f1_mean": [0.65, 0.64, 0.65],
        }
    ).to_csv(results / "model_comparison.csv", index=False)
    pd.DataFrame(
        {
            "subject_id": ["S1", "S2", "S3"],
            "total_windows": [100, 100, 100],
            "clean_windows": [90, 80, 60],
            "mean_signal_quality": [0.9, 0.8, 0.6],
            "clean_window_percent": [90.0, 80.0, 60.0],
        }
    ).to_csv(results / "signal_quality_summary.csv", index=False)
    pd.DataFrame(
        {
            "feature": ["frontal_beta_log", "central_theta_log"],
            "standardized_coefficient": [-0.8, 0.5],
        }
    ).to_csv(results / "logistic_coefficients.csv", index=False)
    pd.DataFrame(
        {
            "outcome": ["frontal_beta_log"],
            "term": ["time_z"],
            "standardized_coefficient": [-0.2],
            "p_value": [0.001],
        }
    ).to_csv(results / "mixed_effects_results.csv", index=False)

    output = build_paper_outputs(config)

    assert output["figure_count"] == 8
    assert output["table_count"] == 6
    assert (results / "paper" / "manifest.json").exists()
    assert (results / "paper" / "figures" / "figure_effect_sizes.pdf").exists()
    assert (results / "paper" / "tables" / "cohort_summary.csv").exists()
