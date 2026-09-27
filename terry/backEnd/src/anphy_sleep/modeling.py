from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC


PREDICTION_FEATURES = [
    "frontal_beta_log",
    "posterior_alpha_log",
    "central_theta_log",
    "central_sigma_log",
    "frontocentral_delta_log",
    "posterior_alpha_theta_log_ratio",
    "frontal_beta_log_slope_1m",
    "posterior_alpha_log_slope_1m",
    "central_theta_log_slope_1m",
    "posterior_alpha_theta_log_ratio_slope_1m",
    "signal_quality",
]


def _build_models(random_seed: int) -> dict[str, Any]:
    return {
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=2_000,
                        class_weight="balanced",
                        random_state=random_seed,
                    ),
                ),
            ]
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=10,
            class_weight="balanced_subsample",
            n_jobs=1,
            random_state=random_seed,
        ),
        "svm": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LinearSVC(
                        class_weight="balanced",
                        random_state=random_seed,
                    ),
                ),
            ]
        ),
    }


def _continuous_score(model: Any, matrix: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(matrix)[:, 1])
    return expit(np.asarray(model.decision_function(matrix)))


def _metric_row(
    model_name: str,
    subject_id: str,
    truth: np.ndarray,
    prediction: np.ndarray,
    score: np.ndarray,
) -> dict[str, float | str | int]:
    tn, fp, fn, tp = confusion_matrix(truth, prediction, labels=[0, 1]).ravel()
    return {
        "model": model_name,
        "subject_id": subject_id,
        "auc": float(roc_auc_score(truth, score)),
        "balanced_accuracy": float(balanced_accuracy_score(truth, prediction)),
        "sensitivity": float(tp / (tp + fn)) if tp + fn else np.nan,
        "specificity": float(tn / (tn + fp)) if tn + fp else np.nan,
        "f1": float(f1_score(truth, prediction, zero_division=0)),
        "n_windows": int(len(truth)),
    }


def _lead_time_rows(
    predictions: pd.DataFrame,
    sustained_seconds: float,
    step_seconds: float,
    threshold: float,
) -> pd.DataFrame:
    required = max(1, int(np.ceil(sustained_seconds / step_seconds)))
    rows = []
    for (model_name, subject_id), group in predictions.groupby(
        ["model", "subject_id"]
    ):
        ordered = group.sort_values("window_end_s").reset_index(drop=True)
        active = ordered["score"].to_numpy() >= threshold
        detection_index = None
        for index in range(0, len(active) - required + 1):
            if active[index : index + required].all():
                detection_index = index
                break
        lead_time = (
            float(ordered.loc[detection_index, "time_to_n2_min"])
            if detection_index is not None
            else np.nan
        )
        rows.append(
            {
                "model": model_name,
                "subject_id": subject_id,
                "first_sustained_alert_lead_min": lead_time,
                "alert_detected": detection_index is not None,
                "alert_within_target_5m": bool(
                    np.isfinite(lead_time) and 0 <= lead_time <= 5
                ),
            }
        )
    return pd.DataFrame(rows)


def run_loso_prediction(
    features: pd.DataFrame,
    config: dict[str, Any],
    output_dir: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate future-5-minute N2 prediction with leave-one-subject-out."""
    output_dir = Path(output_dir)
    data = features[
        features["is_clean"] & features["pre_n2_eligible"]
    ].dropna(subset=PREDICTION_FEATURES + ["n2_within_5m"])
    subjects = sorted(data["subject_id"].unique())
    if len(subjects) < 3:
        raise ValueError("LOSO prediction requires at least three subjects")

    models = _build_models(int(config["project"]["random_seed"]))
    metric_rows = []
    prediction_frames = []
    for subject_id in subjects:
        train = data[data["subject_id"] != subject_id]
        test = data[data["subject_id"] == subject_id]
        x_train = train[PREDICTION_FEATURES]
        y_train = train["n2_within_5m"].astype(int).to_numpy()
        x_test = test[PREDICTION_FEATURES]
        y_test = test["n2_within_5m"].astype(int).to_numpy()
        if len(np.unique(y_test)) < 2:
            continue

        for model_name, template in models.items():
            model = clone(template)
            model.fit(x_train, y_train)
            prediction = np.asarray(model.predict(x_test), dtype=int)
            score = _continuous_score(model, x_test)
            metric_rows.append(
                _metric_row(
                    model_name,
                    subject_id,
                    y_test,
                    prediction,
                    score,
                )
            )
            frame = test[
                [
                    "subject_id",
                    "window_start_s",
                    "window_end_s",
                    "time_to_n2_min",
                    "n2_within_5m",
                ]
            ].copy()
            frame["model"] = model_name
            frame["prediction"] = prediction
            frame["score"] = score
            prediction_frames.append(frame)

    fold_metrics = pd.DataFrame(metric_rows)
    predictions = pd.concat(prediction_frames, ignore_index=True)
    fold_metrics.to_csv(output_dir / "loso_fold_metrics.csv", index=False)
    predictions.to_parquet(output_dir / "loso_predictions.parquet", index=False)

    metric_summary = (
        fold_metrics.groupby("model", as_index=False)
        .agg(
            auc_mean=("auc", "mean"),
            auc_ci95_low=("auc", lambda values: values.mean() - 1.96 * values.sem()),
            auc_ci95_high=("auc", lambda values: values.mean() + 1.96 * values.sem()),
            balanced_accuracy_mean=("balanced_accuracy", "mean"),
            sensitivity_mean=("sensitivity", "mean"),
            specificity_mean=("specificity", "mean"),
            f1_mean=("f1", "mean"),
            evaluated_subjects=("subject_id", "nunique"),
        )
    )
    metric_summary.to_csv(output_dir / "model_comparison.csv", index=False)

    lead_times = _lead_time_rows(
        predictions,
        sustained_seconds=float(
            config["prediction"]["sustained_detection_seconds"]
        ),
        step_seconds=float(config["epoching"]["step_seconds"]),
        threshold=float(config["prediction"]["probability_threshold"]),
    )
    lead_times.to_csv(output_dir / "prediction_lead_times.csv", index=False)

    _plot_roc_curves(predictions, output_dir)
    _fit_deployment_models(data, features, models, output_dir)
    return metric_summary, lead_times


def _plot_roc_curves(predictions: pd.DataFrame, output_dir: Path) -> None:
    figure, axis = plt.subplots(figsize=(6.5, 5.5))
    for model_name, group in predictions.groupby("model"):
        false_positive, true_positive, _ = roc_curve(
            group["n2_within_5m"],
            group["score"],
        )
        auc = roc_auc_score(group["n2_within_5m"], group["score"])
        axis.plot(false_positive, true_positive, label=f"{model_name} (AUC={auc:.3f})")
    axis.plot([0, 1], [0, 1], linestyle="--", color="black", linewidth=1)
    axis.set_xlabel("False positive rate")
    axis.set_ylabel("True positive rate")
    axis.set_title("Leave-one-subject-out prediction of N2 within 5 minutes")
    axis.legend(loc="lower right")
    figure.tight_layout()
    figure.savefig(output_dir / "prediction_roc_curves.png", dpi=220)
    figure.savefig(output_dir / "prediction_roc_curves.pdf", bbox_inches="tight")
    plt.close(figure)


def _fit_deployment_models(
    data: pd.DataFrame,
    all_features: pd.DataFrame,
    models: dict[str, Any],
    output_dir: Path,
) -> None:
    x = data[PREDICTION_FEATURES]
    y = data["n2_within_5m"].astype(int)
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    for model_name, model in models.items():
        model.fit(x, y)
        joblib.dump(
            {
                "model": model,
                "features": PREDICTION_FEATURES,
                "target": "n2_within_5m",
            },
            model_dir / f"{model_name}.joblib",
        )

    logistic = models["logistic_regression"]
    coefficients = pd.DataFrame(
        {
            "feature": PREDICTION_FEATURES,
            "standardized_coefficient": logistic.named_steps["model"].coef_[0],
        }
    ).sort_values("standardized_coefficient", key=np.abs, ascending=False)
    coefficients.to_csv(output_dir / "logistic_coefficients.csv", index=False)

    state_data = all_features[
        all_features["is_clean"]
        & all_features["stage"].isin(["W", "N1", "N2"])
    ].dropna(subset=PREDICTION_FEATURES)
    state_model = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    max_iter=2_000,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )
    state_model.fit(
        state_data[PREDICTION_FEATURES],
        state_data["stage"],
    )
    joblib.dump(
        {
            "model": state_model,
            "features": PREDICTION_FEATURES,
            "target": "aasm_state",
            "classes": list(state_model.named_steps["model"].classes_),
        },
        model_dir / "sleep_state_logistic.joblib",
    )
