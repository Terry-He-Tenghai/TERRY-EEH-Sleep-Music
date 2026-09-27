from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    f1_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler
from sklearn.svm import LinearSVC
from statsmodels.stats.multitest import multipletests

from .modeling import PREDICTION_FEATURES
from .staging import STAGE_STATIC_FEATURES


STAGE_INDICATORS = ["stage_W", "stage_N1", "stage_N2", "stage_other"]
STATIC_EEG_FEATURES = list(STAGE_STATIC_FEATURES)
ABLATION_FEATURES = {
    "time_only": ["elapsed_time_min"],
    "stage_oracle": STAGE_INDICATORS,
    "static_eeg": STATIC_EEG_FEATURES,
    "dynamic_eeg": PREDICTION_FEATURES,
    "dynamic_eeg_plus_time": PREDICTION_FEATURES + ["elapsed_time_min"],
}


def _logistic(random_seed: int) -> Pipeline:
    return Pipeline(
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
    )


def _models(random_seed: int) -> dict[str, tuple[Any, list[str]]]:
    models: dict[str, tuple[Any, list[str]]] = {
        name: (_logistic(random_seed), features)
        for name, features in ABLATION_FEATURES.items()
    }
    models["time_only"] = (
        Pipeline(
            [
                (
                    "spline",
                    SplineTransformer(
                        n_knots=5,
                        degree=3,
                        include_bias=False,
                    ),
                ),
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
        ["elapsed_time_min"],
    )
    models["random_forest_dynamic"] = (
        RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=10,
            class_weight="balanced_subsample",
            n_jobs=1,
            random_state=random_seed,
        ),
        PREDICTION_FEATURES,
    )
    models["svm_dynamic"] = (
        Pipeline(
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
        PREDICTION_FEATURES,
    )
    return models


def _score(model: Any, matrix: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(matrix)[:, 1])
    return expit(np.asarray(model.decision_function(matrix)))


def prepare_continuous_prediction_data(
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Prepare record-start streams without using future N2 to define their start."""
    data = features[
        features["is_clean"] & features["pre_n2_eligible"]
    ].copy()
    data["elapsed_time_min"] = data["window_end_s"] / 60.0
    for stage in ["W", "N1", "N2"]:
        data[f"stage_{stage}"] = (data["stage"] == stage).astype(int)
    data["stage_other"] = (~data["stage"].isin(["W", "N1", "N2"])).astype(int)
    required = list(
        dict.fromkeys(
            PREDICTION_FEATURES
            + ["elapsed_time_min", "n2_within_5m"]
            + STAGE_INDICATORS
        )
    )
    return data.dropna(subset=required).reset_index(drop=True)


def _bootstrap_summary(
    fold_metrics: pd.DataFrame,
    random_seed: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(random_seed)
    rows = []
    for model_name, group in fold_metrics.groupby("model"):
        row: dict[str, float | int | str] = {
            "model": model_name,
            "evaluated_subjects": int(group["subject_id"].nunique()),
        }
        for metric in [
            "auc",
            "average_precision",
            "balanced_accuracy",
            "f1",
        ]:
            values = group[metric].dropna().to_numpy(dtype=float)
            bootstrap = np.asarray(
                [
                    rng.choice(values, size=len(values), replace=True).mean()
                    for _ in range(5_000)
                ]
            )
            row[f"{metric}_mean"] = float(values.mean())
            row[f"{metric}_ci95_low"] = float(
                np.quantile(bootstrap, 0.025)
            )
            row[f"{metric}_ci95_high"] = float(
                np.quantile(bootstrap, 0.975)
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _event_metrics(
    predictions: pd.DataFrame,
    threshold: float,
    sustained_seconds: float,
    step_seconds: float,
) -> pd.DataFrame:
    required = max(1, int(np.ceil(sustained_seconds / step_seconds)))
    rows = []
    for (model_name, subject_id), group in predictions.groupby(
        ["model", "subject_id"]
    ):
        ordered = group.sort_values("window_end_s").reset_index(drop=True)
        active = ordered["score"].to_numpy() >= threshold
        sustained = np.zeros(len(active), dtype=bool)
        for index in range(len(active) - required + 1):
            sustained[index] = bool(active[index : index + required].all())
        starts = np.flatnonzero(sustained & ~np.r_[False, sustained[:-1]])
        lead_times = (
            ordered.loc[starts, "time_to_n2_min"].to_numpy(dtype=float)
            if len(starts)
            else np.asarray([], dtype=float)
        )
        target_alerts = lead_times[
            (lead_times >= 0) & (lead_times <= 5)
        ]
        early_alerts = lead_times[lead_times > 5]
        pretarget_hours = max(
            float((ordered["time_to_n2_min"] > 5).sum())
            * step_seconds
            / 3600,
            step_seconds / 3600,
        )
        rows.append(
            {
                "model": model_name,
                "subject_id": subject_id,
                "target_event_detected": bool(len(target_alerts)),
                "first_target_alert_lead_min": (
                    float(target_alerts[0]) if len(target_alerts) else np.nan
                ),
                "first_alert_lead_min": (
                    float(lead_times[0]) if len(lead_times) else np.nan
                ),
                "early_false_alert_episodes": int(len(early_alerts)),
                "false_alerts_per_pretarget_hour": float(
                    len(early_alerts) / pretarget_hours
                ),
            }
        )
    return pd.DataFrame(rows)


def _paired_auc_comparisons(
    fold_metrics: pd.DataFrame,
    random_seed: int,
) -> pd.DataFrame:
    wide = fold_metrics.pivot(
        index="subject_id",
        columns="model",
        values="auc",
    )
    rng = np.random.default_rng(random_seed)
    rows = []
    for reference in ["static_eeg", "stage_oracle", "time_only"]:
        differences = (wide["dynamic_eeg"] - wide[reference]).dropna().to_numpy()
        bootstrap = np.asarray(
            [
                rng.choice(
                    differences,
                    size=len(differences),
                    replace=True,
                ).mean()
                for _ in range(10_000)
            ]
        )
        rows.append(
            {
                "comparison": f"dynamic_eeg_minus_{reference}",
                "mean_auc_difference": float(differences.mean()),
                "bootstrap_ci95_low": float(
                    np.quantile(bootstrap, 0.025)
                ),
                "bootstrap_ci95_high": float(
                    np.quantile(bootstrap, 0.975)
                ),
                "paired_t_p_value": float(
                    stats.ttest_1samp(differences, 0).pvalue
                ),
                "wilcoxon_p_value": float(
                    stats.wilcoxon(differences).pvalue
                ),
                "n_subjects": int(len(differences)),
            }
        )
    comparisons = pd.DataFrame(rows)
    comparisons["paired_t_p_value_fdr"] = multipletests(
        comparisons["paired_t_p_value"].to_numpy(),
        method="fdr_bh",
    )[1]
    comparisons["wilcoxon_p_value_fdr"] = multipletests(
        comparisons["wilcoxon_p_value"].to_numpy(),
        method="fdr_bh",
    )[1]
    return comparisons


def run_continuous_prediction(
    features: pd.DataFrame,
    config: dict[str, Any],
    output_dir: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run record-start-anchored LOSO prediction and feature-set ablations."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data = prepare_continuous_prediction_data(features)
    subjects = sorted(data["subject_id"].unique())
    if len(subjects) < 3:
        raise ValueError("Continuous LOSO requires at least three subjects")

    random_seed = int(config["project"]["random_seed"])
    models = _models(random_seed)
    metric_rows = []
    prediction_frames = []
    for subject_id in subjects:
        train = data[data["subject_id"] != subject_id]
        test = data[data["subject_id"] == subject_id]
        truth = test["n2_within_5m"].astype(int).to_numpy()
        if len(np.unique(truth)) < 2:
            continue
        for model_name, (template, feature_names) in models.items():
            model = clone(template)
            model.fit(
                train[feature_names],
                train["n2_within_5m"].astype(int),
            )
            prediction = np.asarray(
                model.predict(test[feature_names]),
                dtype=int,
            )
            score = _score(model, test[feature_names])
            metric_rows.append(
                {
                    "model": model_name,
                    "subject_id": subject_id,
                    "auc": float(roc_auc_score(truth, score)),
                    "average_precision": float(
                        average_precision_score(truth, score)
                    ),
                    "balanced_accuracy": float(
                        balanced_accuracy_score(truth, prediction)
                    ),
                    "f1": float(f1_score(truth, prediction, zero_division=0)),
                    "positive_prevalence": float(truth.mean()),
                    "n_windows": int(len(test)),
                }
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
    summary = _bootstrap_summary(fold_metrics, random_seed)
    events = _event_metrics(
        predictions,
        threshold=float(config["prediction"]["probability_threshold"]),
        sustained_seconds=float(
            config["prediction"]["sustained_detection_seconds"]
        ),
        step_seconds=float(config["epoching"]["step_seconds"]),
    )
    event_summary = (
        events.groupby("model", as_index=False)
        .agg(
            target_event_sensitivity=("target_event_detected", "mean"),
            median_target_lead_min=("first_target_alert_lead_min", "median"),
            median_false_alerts_per_hour=(
                "false_alerts_per_pretarget_hour",
                "median",
            ),
            no_alert_subjects=(
                "first_alert_lead_min",
                lambda values: int(values.isna().sum()),
            ),
        )
    )
    summary = summary.merge(event_summary, on="model", how="left")
    comparisons = _paired_auc_comparisons(fold_metrics, random_seed)

    fold_metrics.to_csv(
        output_dir / "continuous_loso_fold_metrics.csv",
        index=False,
    )
    predictions.to_parquet(
        output_dir / "continuous_loso_predictions.parquet",
        index=False,
    )
    events.to_csv(
        output_dir / "continuous_event_metrics.csv",
        index=False,
    )
    summary.to_csv(
        output_dir / "continuous_model_comparison.csv",
        index=False,
    )
    comparisons.to_csv(
        output_dir / "continuous_auc_ablation_comparisons.csv",
        index=False,
    )

    deployment = _logistic(random_seed)
    deployment.fit(
        data[PREDICTION_FEATURES],
        data["n2_within_5m"].astype(int),
    )
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": deployment,
            "features": PREDICTION_FEATURES,
            "target": "n2_within_5m",
            "anchor": "record_start",
            "validation": "leave-one-subject-out",
        },
        model_dir / "future_n2_logistic_continuous.joblib",
    )
    return summary, events
