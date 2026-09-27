from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from statsmodels.stats.multitest import multipletests


STAGE_CLASSES = ["W", "N1", "N2"]
STAGE_STATIC_FEATURES = [
    "frontal_beta_log",
    "posterior_alpha_log",
    "central_theta_log",
    "central_sigma_log",
    "frontocentral_delta_log",
    "posterior_alpha_theta_log_ratio",
    "signal_quality",
]
STAGE_DYNAMIC_FEATURES = STAGE_STATIC_FEATURES + [
    "frontal_beta_log_slope_1m",
    "posterior_alpha_log_slope_1m",
    "central_theta_log_slope_1m",
    "posterior_alpha_theta_log_ratio_slope_1m",
]
STAGE_POWER_FEATURES = {
    "frontal_beta_log": "Frontal beta",
    "posterior_alpha_log": "Posterior alpha",
    "central_theta_log": "Central theta",
    "central_sigma_log": "Central sigma",
    "frontocentral_delta_log": "Frontocentral delta",
}


def aggregate_aasm_epochs(
    features: pd.DataFrame,
    minimum_clean_fraction: float = 0.8,
) -> pd.DataFrame:
    """Aggregate causal windows to the 30-second unit used by AASM labels."""
    data = features[features["stage"].isin(STAGE_CLASSES)].copy()
    data["window_midpoint_s"] = (
        data["window_start_s"] + data["window_end_s"]
    ) / 2
    data["aasm_epoch"] = np.floor(data["window_midpoint_s"] / 30).astype(int)
    rows = []
    feature_columns = list(
        dict.fromkeys(STAGE_DYNAMIC_FEATURES)
    )
    for (subject_id, epoch), group in data.groupby(
        ["subject_id", "aasm_epoch"],
        sort=True,
    ):
        clean_fraction = float(group["is_clean"].mean())
        clean = group[group["is_clean"]]
        if clean_fraction < minimum_clean_fraction or clean.empty:
            continue
        stage_counts = group["stage"].value_counts()
        if stage_counts.empty:
            continue
        stage = str(stage_counts.index[0])
        row: dict[str, float | int | str] = {
            "subject_id": subject_id,
            "aasm_epoch": int(epoch),
            "epoch_start_s": float(epoch * 30),
            "epoch_end_s": float((epoch + 1) * 30),
            "stage": stage,
            "clean_window_fraction": clean_fraction,
        }
        for column in feature_columns:
            row[column] = float(clean[column].mean())
        rows.append(row)
    epochs = pd.DataFrame(rows)
    return epochs.dropna(subset=STAGE_DYNAMIC_FEATURES).reset_index(drop=True)


def _stage_models(random_seed: int) -> dict[str, tuple[Any, list[str]]]:
    logistic = lambda: Pipeline(
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
    return {
        "logistic_static": (logistic(), STAGE_STATIC_FEATURES),
        "logistic_dynamic": (logistic(), STAGE_DYNAMIC_FEATURES),
        "random_forest_dynamic": (
            RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=5,
                class_weight="balanced_subsample",
                n_jobs=1,
                random_state=random_seed,
            ),
            STAGE_DYNAMIC_FEATURES,
        ),
        "svm_dynamic": (
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
            STAGE_DYNAMIC_FEATURES,
        ),
    }


def _bootstrap_mean_ci(
    values: pd.Series,
    random_seed: int,
    iterations: int = 5_000,
) -> tuple[float, float]:
    array = values.dropna().to_numpy(dtype=float)
    rng = np.random.default_rng(random_seed)
    bootstrap = np.asarray(
        [
            rng.choice(array, size=len(array), replace=True).mean()
            for _ in range(iterations)
        ]
    )
    low, high = np.quantile(bootstrap, [0.025, 0.975])
    return float(low), float(high)


def run_stage_classification(
    features: pd.DataFrame,
    config: dict[str, Any],
    output_dir: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate W/N1/N2 classification by held-out participant."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    epochs = aggregate_aasm_epochs(
        features,
        minimum_clean_fraction=float(
            config["quality"]["minimum_clean_window_fraction"]
        ),
    )
    subjects = sorted(epochs["subject_id"].unique())
    if len(subjects) < 3:
        raise ValueError("Stage LOSO requires at least three subjects")
    if set(epochs["stage"]) != set(STAGE_CLASSES):
        raise ValueError("Stage data must contain W, N1, and N2")

    random_seed = int(config["project"]["random_seed"])
    models = _stage_models(random_seed)
    metric_rows = []
    prediction_rows = []
    for subject_id in subjects:
        train = epochs[epochs["subject_id"] != subject_id]
        test = epochs[epochs["subject_id"] == subject_id]
        for model_name, (template, feature_names) in models.items():
            model = clone(template)
            model.fit(train[feature_names], train["stage"])
            prediction = np.asarray(model.predict(test[feature_names]))
            truth = test["stage"].to_numpy()
            recalls = recall_score(
                truth,
                prediction,
                labels=STAGE_CLASSES,
                average=None,
                zero_division=0,
            )
            metric_rows.append(
                {
                    "model": model_name,
                    "subject_id": subject_id,
                    "balanced_accuracy": float(
                        balanced_accuracy_score(truth, prediction)
                    ),
                    "macro_f1": float(
                        f1_score(
                            truth,
                            prediction,
                            labels=STAGE_CLASSES,
                            average="macro",
                            zero_division=0,
                        )
                    ),
                    "cohen_kappa": float(cohen_kappa_score(truth, prediction)),
                    **{
                        f"recall_{stage}": float(value)
                        for stage, value in zip(
                            STAGE_CLASSES,
                            recalls,
                            strict=True,
                        )
                    },
                    "n_epochs": int(len(test)),
                }
            )
            frame = test[
                [
                    "subject_id",
                    "aasm_epoch",
                    "epoch_start_s",
                    "epoch_end_s",
                    "stage",
                ]
            ].copy()
            frame["model"] = model_name
            frame["prediction"] = prediction
            prediction_rows.extend(frame.to_dict("records"))

    fold_metrics = pd.DataFrame(metric_rows)
    predictions = pd.DataFrame(prediction_rows)
    summary_rows = []
    for model_name, group in fold_metrics.groupby("model"):
        row: dict[str, float | int | str] = {
            "model": model_name,
            "evaluated_subjects": int(group["subject_id"].nunique()),
        }
        for metric in [
            "balanced_accuracy",
            "macro_f1",
            "cohen_kappa",
            "recall_W",
            "recall_N1",
            "recall_N2",
        ]:
            low, high = _bootstrap_mean_ci(group[metric], random_seed)
            row[f"{metric}_mean"] = float(group[metric].mean())
            row[f"{metric}_ci95_low"] = low
            row[f"{metric}_ci95_high"] = high
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows)

    primary_predictions = predictions[
        predictions["model"] == "logistic_dynamic"
    ]
    matrix = confusion_matrix(
        primary_predictions["stage"],
        primary_predictions["prediction"],
        labels=STAGE_CLASSES,
        normalize="true",
    )
    confusion = pd.DataFrame(
        matrix,
        index=[f"true_{stage}" for stage in STAGE_CLASSES],
        columns=[f"pred_{stage}" for stage in STAGE_CLASSES],
    )

    epochs.to_parquet(output_dir / "stage_epoch_features.parquet", index=False)
    fold_metrics.to_csv(output_dir / "stage_loso_fold_metrics.csv", index=False)
    predictions.to_parquet(
        output_dir / "stage_loso_predictions.parquet",
        index=False,
    )
    summary.to_csv(output_dir / "stage_model_comparison.csv", index=False)
    confusion.to_csv(output_dir / "stage_confusion_matrix.csv")

    deployment = _stage_models(random_seed)["logistic_dynamic"][0]
    deployment.fit(epochs[STAGE_DYNAMIC_FEATURES], epochs["stage"])
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": deployment,
            "features": STAGE_DYNAMIC_FEATURES,
            "target": "aasm_state",
            "classes": list(deployment.named_steps["model"].classes_),
            "aggregation_seconds": 30.0,
            "evaluation_unit": "AASM 30-second epoch",
        },
        model_dir / "sleep_state_logistic_30s.joblib",
    )
    return summary, confusion


def run_stage_physiology(
    epoch_features: pd.DataFrame,
    output_dir: str | Path,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Quantify PSD-derived regional changes across W, N1, and N2."""
    output_dir = Path(output_dir)
    subject_stage = (
        epoch_features.groupby(["subject_id", "stage"], as_index=False)[
            list(STAGE_POWER_FEATURES)
        ]
        .mean()
    )
    summary = (
        subject_stage.groupby("stage", as_index=False)[list(STAGE_POWER_FEATURES)]
        .agg(["mean", "std", "count"])
    )
    summary.columns = [
        "_".join(part for part in column if part)
        for column in summary.columns.to_flat_index()
    ]
    summary = summary.rename(columns={"stage_": "stage"})

    wide = subject_stage.pivot(
        index="subject_id",
        columns="stage",
        values=list(STAGE_POWER_FEATURES),
    )
    rng = np.random.default_rng(random_seed)
    rows = []
    for feature in STAGE_POWER_FEATURES:
        for start, end in [("W", "N1"), ("N1", "N2")]:
            paired = wide[feature][[start, end]].dropna()
            differences = (paired[end] - paired[start]).to_numpy()
            standard_deviation = float(np.std(differences, ddof=1))
            dz = float(np.mean(differences) / standard_deviation)
            boot = []
            for _ in range(5_000):
                sample = rng.choice(
                    differences,
                    size=len(differences),
                    replace=True,
                )
                sample_sd = float(np.std(sample, ddof=1))
                if sample_sd > 0:
                    boot.append(float(np.mean(sample) / sample_sd))
            low, high = np.quantile(boot, [0.025, 0.975])
            test = stats.ttest_rel(paired[end], paired[start])
            rows.append(
                {
                    "feature": feature,
                    "feature_label": STAGE_POWER_FEATURES[feature],
                    "contrast": f"{end}_minus_{start}",
                    "mean_log_power_difference": float(
                        np.mean(differences)
                    ),
                    "cohen_dz": dz,
                    "cohen_dz_ci95_low": float(low),
                    "cohen_dz_ci95_high": float(high),
                    "paired_t_p_value": float(test.pvalue),
                    "n_subjects": int(len(paired)),
                }
            )
    contrasts = pd.DataFrame(rows)
    contrasts["paired_t_p_value_fdr"] = multipletests(
        contrasts["paired_t_p_value"].to_numpy(),
        method="fdr_bh",
    )[1]
    summary.to_csv(output_dir / "stage_power_summary.csv", index=False)
    contrasts.to_csv(output_dir / "stage_power_contrasts.csv", index=False)
    return summary, contrasts
