from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CORE_FEATURES = {
    "frontal_beta_log": "frontal_beta",
    "posterior_alpha_log": "posterior_alpha",
    "central_theta_log": "central_theta",
}


def _segment_means(data: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    pre_baseline = data[data["relative_time_min"] < -5].sort_values(
        "relative_time_min"
    )
    if pre_baseline.empty:
        raise ValueError("No clean pre-N2 baseline is available")
    baseline_start = float(pre_baseline["relative_time_min"].min())
    baseline = pre_baseline[
        pre_baseline["relative_time_min"].between(
            baseline_start,
            min(baseline_start + 5, -5),
            inclusive="left",
        )
    ]
    near_n2 = data[
        data["relative_time_min"].between(-5, 0, inclusive="left")
    ]
    post_n2 = data[
        data["relative_time_min"].between(0, 5, inclusive="left")
    ]
    columns = list(CORE_FEATURES)
    return (
        baseline[columns].mean(),
        near_n2[columns].mean(),
        post_n2[columns].mean(),
    )


def generate_pilot_report(
    features_path: str | Path,
    spindles_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Generate descriptive single-subject outputs without inferential claims."""
    features = pd.read_parquet(features_path)
    spindles = pd.read_csv(spindles_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    features["relative_time_min"] = -features["time_to_n2_min"]
    clean = features[
        features["is_clean"] & features["stage"].isin(["W", "N1", "N2"])
    ].copy()
    clean["minute_bin"] = np.floor(clean["relative_time_min"]).astype(int)
    minute_trajectory = (
        clean.groupby("minute_bin", as_index=False)[list(CORE_FEATURES)]
        .mean()
        .rename(columns=CORE_FEATURES)
    )
    minute_trajectory.to_csv(
        output_dir / "pilot_minute_trajectory.csv",
        index=False,
    )

    baseline, near_n2, post_n2 = _segment_means(clean)
    segment_rows = []
    for source, label in (
        (baseline, "early_available_5m"),
        (near_n2, "n2_minus_5_to_0m"),
        (post_n2, "n2_plus_0_to_5m"),
    ):
        row: dict[str, Any] = {"segment": label}
        for feature, short_name in CORE_FEATURES.items():
            row[short_name] = float(source[feature])
        segment_rows.append(row)
    segment_summary = pd.DataFrame(segment_rows)
    segment_summary.to_csv(output_dir / "pilot_segment_means.csv", index=False)

    change_rows = []
    for feature, short_name in CORE_FEATURES.items():
        log_change = float(near_n2[feature] - baseline[feature])
        change_rows.append(
            {
                "feature": short_name,
                "late_minus_early_log10_power": log_change,
                "geometric_power_change_percent": 100 * (10**log_change - 1),
            }
        )
    changes = pd.DataFrame(change_rows)
    changes.to_csv(output_dir / "pilot_early_to_late_changes.csv", index=False)

    pre_minutes = minute_trajectory[minute_trajectory["minute_bin"] < 0]
    slopes = {}
    for feature in CORE_FEATURES.values():
        slopes[f"{feature}_log10_power_per_min"] = float(
            np.polyfit(
                pre_minutes["minute_bin"],
                pre_minutes[feature],
                1,
            )[0]
        )
    alpha_peak = pre_minutes.loc[
        pre_minutes["posterior_alpha"].idxmax(),
        ["minute_bin", "posterior_alpha"],
    ]

    spindle_groups = {
        "all_pre_n2": spindles["time_to_n2_min"] > 0,
        "n2_minus_5_to_0m": spindles["time_to_n2_min"].between(
            0,
            5,
            inclusive="right",
        ),
        "n2_plus_0_to_5m": spindles["time_to_n2_min"].between(
            -5,
            0,
            inclusive="left",
        ),
    }
    spindle_summary = pd.DataFrame(
        [
            {
                "interval": name,
                "count": int(mask.sum()),
                "median_frequency_hz": (
                    float(spindles.loc[mask, "Frequency"].median())
                    if mask.any()
                    else np.nan
                ),
                "median_duration_s": (
                    float(spindles.loc[mask, "Duration"].median())
                    if mask.any()
                    else np.nan
                ),
            }
            for name, mask in spindle_groups.items()
        ]
    )
    spindle_summary.to_csv(output_dir / "pilot_spindle_summary.csv", index=False)

    stage_quality = (
        features.groupby("stage", as_index=False)
        .agg(
            total_windows=("is_clean", "size"),
            clean_windows=("is_clean", "sum"),
            mean_signal_quality=("signal_quality", "mean"),
        )
    )
    stage_quality["clean_percent"] = (
        100 * stage_quality["clean_windows"] / stage_quality["total_windows"]
    )
    stage_quality.to_csv(output_dir / "pilot_quality_by_stage.csv", index=False)

    summary = {
        "subject_id": str(features["subject_id"].iloc[0]),
        "total_windows": int(len(features)),
        "clean_windows": int(features["is_clean"].sum()),
        "clean_percent": float(100 * features["is_clean"].mean()),
        "analysis_stage_windows": int(
            features["stage"].isin(["W", "N1", "N2"]).sum()
        ),
        "analysis_stage_clean_percent": float(
            100
            * features.loc[
                features["stage"].isin(["W", "N1", "N2"]),
                "is_clean",
            ].mean()
        ),
        "light_state_excluded_windows": int((features["stage"] == "L").sum()),
        "stable_n2_onset_s": float(
            np.median(
                (features["window_start_s"] + features["window_end_s"]) / 2
                + features["time_to_n2_min"] * 60
            )
        ),
        "available_pre_n2_minutes": float(
            clean.loc[clean["relative_time_min"] < 0, "relative_time_min"].abs().max()
        ),
        "early_to_late_changes": {
            row["feature"]: round(float(row["geometric_power_change_percent"]), 2)
            for row in change_rows
        },
        "pre_n2_slopes": {key: round(value, 5) for key, value in slopes.items()},
        "alpha_peak_minute": int(alpha_peak["minute_bin"]),
        "alpha_peak_log10_power": float(alpha_peak["posterior_alpha"]),
        "spindle_counts": {
            row["interval"]: int(row["count"])
            for row in spindle_summary.to_dict("records")
        },
        "interpretation_boundary": (
            "Single-subject descriptive pilot only; no population significance "
            "test or LOSO prediction is valid."
        ),
    }
    (output_dir / "pilot_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def generate_multi_subject_pilot(
    processed_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Summarize cross-subject direction consistency for a small technical pilot."""
    processed_dir = Path(processed_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    subject_rows = []

    for feature_path in sorted(processed_dir.glob("EPCTL*/features.parquet")):
        features = pd.read_parquet(feature_path)
        subject_id = str(features["subject_id"].iloc[0])
        features["relative_time_min"] = -features["time_to_n2_min"]
        clean = features[
            features["is_clean"] & features["stage"].isin(["W", "N1", "N2"])
        ].copy()
        baseline, near_n2, _ = _segment_means(clean)
        clean["minute_bin"] = np.floor(clean["relative_time_min"]).astype(int)
        pre_minutes = (
            clean[clean["minute_bin"] < 0]
            .groupby("minute_bin", as_index=False)[list(CORE_FEATURES)]
            .mean()
        )
        alpha_peak_minute = int(
            pre_minutes.loc[
                pre_minutes["posterior_alpha_log"].idxmax(),
                "minute_bin",
            ]
        )

        spindle_path = feature_path.with_name("spindles.csv")
        spindles = pd.read_csv(spindle_path)
        row: dict[str, Any] = {
            "subject_id": subject_id,
            "total_windows": int(len(features)),
            "analysis_windows": int(len(clean)),
            "analysis_clean_percent": float(
                100
                * features.loc[
                    features["stage"].isin(["W", "N1", "N2"]),
                    "is_clean",
                ].mean()
            ),
            "available_pre_n2_min": float(
                clean.loc[
                    clean["relative_time_min"] < 0,
                    "relative_time_min",
                ].abs().max()
            ),
            "alpha_peak_minute": alpha_peak_minute,
            "spindles_n2_minus_5_to_0m": int(
                spindles["time_to_n2_min"].between(
                    0,
                    5,
                    inclusive="right",
                ).sum()
            ),
            "spindles_n2_plus_0_to_5m": int(
                spindles["time_to_n2_min"].between(
                    -5,
                    0,
                    inclusive="left",
                ).sum()
            ),
        }
        for feature, short_name in CORE_FEATURES.items():
            log_change = float(near_n2[feature] - baseline[feature])
            row[f"{short_name}_change_percent"] = 100 * (10**log_change - 1)
        subject_rows.append(row)

    subjects = pd.DataFrame(subject_rows)
    if len(subjects) < 2:
        raise ValueError("Multi-subject pilot requires at least two subjects")
    subjects.to_csv(output_dir / "multi_subject_pilot.csv", index=False)

    direction_rules = {
        "frontal_beta_decreased": subjects["frontal_beta_change_percent"] < 0,
        "posterior_alpha_decreased_near_n2": (
            subjects["posterior_alpha_change_percent"] < 0
        ),
        "central_theta_increased": subjects["central_theta_change_percent"] > 0,
        "spindles_increased_after_n2": (
            subjects["spindles_n2_plus_0_to_5m"]
            > subjects["spindles_n2_minus_5_to_0m"]
        ),
    }
    summary = {
        "subject_count": int(len(subjects)),
        "subject_ids": subjects["subject_id"].tolist(),
        "total_analysis_windows": int(subjects["analysis_windows"].sum()),
        "median_analysis_clean_percent": float(
            subjects["analysis_clean_percent"].median()
        ),
        "median_changes_percent": {
            "frontal_beta": float(subjects["frontal_beta_change_percent"].median()),
            "posterior_alpha": float(
                subjects["posterior_alpha_change_percent"].median()
            ),
            "central_theta": float(subjects["central_theta_change_percent"].median()),
        },
        "direction_consistency": {
            name: f"{int(rule.sum())}/{len(subjects)}"
            for name, rule in direction_rules.items()
        },
        "interpretation_boundary": (
            "Three-subject technical pilot only; no population inference or "
            "competition-grade model performance claim."
        ),
    }
    (output_dir / "multi_subject_pilot_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary
