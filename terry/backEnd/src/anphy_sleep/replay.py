from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def _row_matrix(row: pd.Series, feature_names: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [[row[name] for name in feature_names]],
        columns=feature_names,
    )


def run_offline_replay(
    features: pd.DataFrame,
    prediction_model_path: str | Path,
    state_model_path: str | Path,
    output_path: str | Path,
    subject_id: str,
    speed: float = 0.0,
) -> Path:
    """Replay causal feature windows and emit one JSON state update per step."""
    prediction_bundle = joblib.load(prediction_model_path)
    state_bundle = joblib.load(state_model_path)
    prediction_model = prediction_bundle["model"]
    prediction_features = list(prediction_bundle["features"])
    state_model = state_bundle["model"]
    state_features = list(state_bundle["features"])
    state_classes = list(state_bundle["classes"])

    stream = features[features["subject_id"] == subject_id].sort_values(
        "window_end_s"
    )
    if stream.empty:
        raise ValueError(f"No features found for subject {subject_id}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in stream.itertuples(index=False):
            series = pd.Series(row._asdict())
            required = prediction_features + state_features
            valid = bool(series["is_clean"]) and all(
                np.isfinite(float(series[name])) for name in required
            )
            update: dict[str, object] = {
                "subject_id": subject_id,
                "window_end_s": float(series["window_end_s"]),
                "time_to_reference_n2_min": float(series["time_to_n2_min"]),
                "signal_quality": float(series["signal_quality"]),
                "status": "ok" if valid else "signal_invalid",
            }
            if valid:
                prediction_matrix = _row_matrix(series, prediction_features)
                n2_probability = float(
                    prediction_model.predict_proba(prediction_matrix)[0, 1]
                )
                state_probabilities = state_model.predict_proba(
                    _row_matrix(series, state_features)
                )[0]
                update["n2_within_5m_probability"] = n2_probability
                update["aasm_state_probabilities"] = {
                    stage: float(probability)
                    for stage, probability in zip(
                        state_classes,
                        state_probabilities,
                        strict=True,
                    )
                }
                update["interpretable_features"] = {
                    "frontal_beta_z": float(
                        series["frontal_beta_log_baseline_z"]
                    ),
                    "posterior_alpha_z": float(
                        series["posterior_alpha_log_baseline_z"]
                    ),
                    "central_theta_z": float(
                        series["central_theta_log_baseline_z"]
                    ),
                    "alpha_theta_slope_1m": float(
                        series[
                            "posterior_alpha_theta_log_ratio_slope_1m"
                        ]
                    ),
                }
            handle.write(json.dumps(update, ensure_ascii=False) + "\n")
            handle.flush()
            if speed > 0:
                time.sleep(3.0 / speed)
    return output_path
