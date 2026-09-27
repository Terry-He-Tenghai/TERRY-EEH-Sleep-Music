from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import mne
import numpy as np
import pandas as pd
import seaborn as sns
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.multitest import multipletests


CORE_TRAJECTORIES = {
    "frontal_beta_log": "Frontal beta",
    "posterior_alpha_log": "Posterior alpha",
    "central_theta_log": "Central theta",
}


def _relative_time(features: pd.DataFrame) -> pd.Series:
    return -features["time_to_n2_min"]


def summarize_signal_quality(features: pd.DataFrame, output_dir: str | Path) -> pd.DataFrame:
    """Create subject-level window quality summary."""
    output_dir = Path(output_dir)
    summary = (
        features.groupby("subject_id", as_index=False)
        .agg(
            total_windows=("is_clean", "size"),
            clean_windows=("is_clean", "sum"),
            mean_signal_quality=("signal_quality", "mean"),
        )
    )
    summary["clean_window_percent"] = (
        100 * summary["clean_windows"] / summary["total_windows"]
    )
    summary.to_csv(output_dir / "signal_quality_summary.csv", index=False)
    return summary


def plot_aligned_trajectories(
    features: pd.DataFrame,
    output_dir: str | Path,
) -> Path:
    """Plot subject-balanced beta/alpha/theta trajectories aligned to stable N2."""
    output_dir = Path(output_dir)
    clean = features[features["is_clean"]].copy()
    clean["relative_time_min"] = _relative_time(clean)
    clean["minute_bin"] = np.floor(clean["relative_time_min"]).astype(int)

    subject_minutes = (
        clean.groupby(["subject_id", "minute_bin"], as_index=False)[
            list(CORE_TRAJECTORIES)
        ]
        .mean()
    )
    grouped = subject_minutes.groupby("minute_bin")

    sns.set_theme(style="whitegrid")
    figure, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=True)
    for axis, (column, title) in zip(axes, CORE_TRAJECTORIES.items(), strict=True):
        mean = grouped[column].mean()
        count = grouped[column].count()
        sem = grouped[column].std(ddof=1) / np.sqrt(count)
        ci = 1.96 * sem
        axis.plot(mean.index, mean.values, linewidth=2, label=title)
        axis.fill_between(mean.index, mean - ci, mean + ci, alpha=0.2)
        axis.axvline(0, color="black", linestyle="--", linewidth=1)
        axis.set_ylabel("Log power")
        axis.set_title(f"{title} aligned to first stable N2")
        axis.legend(loc="best")
    axes[-1].set_xlabel("Time relative to stable N2 (min)")
    figure.tight_layout()
    destination = output_dir / "sleep_onset_band_trajectories.png"
    figure.savefig(destination, dpi=220, bbox_inches="tight")
    figure.savefig(
        output_dir / "sleep_onset_band_trajectories.pdf",
        bbox_inches="tight",
    )
    plt.close(figure)
    return destination


def _standardize(values: pd.Series) -> pd.Series:
    standard_deviation = float(values.std(ddof=0))
    if standard_deviation == 0:
        return values * 0
    return (values - values.mean()) / standard_deviation


def _mixed_model_rows(
    data: pd.DataFrame,
    outcome: str,
    formula_terms: str,
) -> list[dict[str, Any]]:
    working = data[["subject_id", "relative_time_min", outcome]].dropna().copy()
    working["minute_bin"] = np.floor(working["relative_time_min"]).astype(int)
    working = (
        working.groupby(["subject_id", "minute_bin"], as_index=False)[outcome]
        .mean()
        .rename(columns={"minute_bin": "relative_time_min"})
    )
    working["outcome_z"] = _standardize(working[outcome])
    working["time_z"] = _standardize(working["relative_time_min"])
    working["time_z_squared"] = working["time_z"] ** 2
    model = smf.mixedlm(
        f"outcome_z ~ {formula_terms}",
        working,
        groups=working["subject_id"],
    ).fit(reml=True, method="lbfgs")
    confidence = model.conf_int()
    rows = []
    for term in model.params.index:
        if term in {"Group Var", "Intercept"}:
            continue
        rows.append(
            {
                "outcome": outcome,
                "term": term,
                "standardized_coefficient": float(model.params[term]),
                "ci95_low": float(confidence.loc[term, 0]),
                "ci95_high": float(confidence.loc[term, 1]),
                "p_value": float(model.pvalues[term]),
                "n_subject_minutes": int(len(working)),
                "n_subjects": int(working["subject_id"].nunique()),
                "model_converged": bool(model.converged),
            }
        )
    return rows


def _paired_effect(
    data: pd.DataFrame,
    outcome: str,
    random_seed: int,
) -> dict[str, float | str]:
    baseline = _early_baseline_means(data, [outcome])[outcome]
    near_n2 = (
        data[data["relative_time_min"].between(-5, 0, inclusive="left")]
        .groupby("subject_id")[outcome]
        .mean()
    )
    paired = pd.concat({"baseline": baseline, "near_n2": near_n2}, axis=1).dropna()
    differences = (paired["near_n2"] - paired["baseline"]).to_numpy()
    dz = float(np.mean(differences) / np.std(differences, ddof=1))

    rng = np.random.default_rng(random_seed)
    bootstrap_dz = []
    for _ in range(5_000):
        sample = rng.choice(differences, size=len(differences), replace=True)
        sample_sd = np.std(sample, ddof=1)
        if sample_sd > 0:
            bootstrap_dz.append(np.mean(sample) / sample_sd)
    ci_low, ci_high = np.quantile(bootstrap_dz, [0.025, 0.975])
    test = stats.ttest_rel(paired["near_n2"], paired["baseline"])
    return {
        "outcome": outcome,
        "contrast": "near_n2_minus_baseline",
        "mean_difference": float(np.mean(differences)),
        "cohen_dz": dz,
        "cohen_dz_ci95_low": float(ci_low),
        "cohen_dz_ci95_high": float(ci_high),
        "paired_t_p_value": float(test.pvalue),
        "n_subjects": int(len(paired)),
    }


def _early_baseline_means(
    data: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    """Average each subject's earliest available five clean pre-N2 minutes."""
    rows = []
    for subject_id, group in data.groupby("subject_id"):
        eligible = group[group["relative_time_min"] < -5].sort_values(
            "relative_time_min"
        )
        if eligible.empty:
            continue
        start = float(eligible["relative_time_min"].min())
        baseline = eligible[
            eligible["relative_time_min"].between(
                start,
                min(start + 5, -5),
                inclusive="left",
            )
        ]
        if baseline.empty:
            continue
        row = baseline[columns].mean()
        row.name = subject_id
        rows.append(row)
    return pd.DataFrame(rows)


def run_trajectory_statistics(
    features: pd.DataFrame,
    output_dir: str | Path,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Test beta/theta trends and the posterior-alpha inverted-U hypothesis."""
    output_dir = Path(output_dir)
    clean = features[
        features["is_clean"] & features["pre_n2_eligible"]
    ].copy()
    clean["relative_time_min"] = _relative_time(clean)
    clean = clean[clean["relative_time_min"].between(-20, 0, inclusive="both")]

    model_rows = []
    model_rows.extend(
        _mixed_model_rows(clean, "frontal_beta_log", "time_z")
    )
    model_rows.extend(
        _mixed_model_rows(clean, "central_theta_log", "time_z")
    )
    model_rows.extend(
        _mixed_model_rows(
            clean,
            "posterior_alpha_log",
            "time_z + time_z_squared",
        )
    )
    model_results = pd.DataFrame(model_rows)
    model_results["p_value_fdr"] = multipletests(
        model_results["p_value"].to_numpy(),
        alpha=0.05,
        method="fdr_bh",
    )[1]
    model_results.to_csv(output_dir / "mixed_effects_results.csv", index=False)

    effect_results = pd.DataFrame(
        [
            _paired_effect(clean, outcome, random_seed)
            for outcome in CORE_TRAJECTORIES
        ]
    )
    effect_results["paired_t_p_value_fdr"] = multipletests(
        effect_results["paired_t_p_value"].to_numpy(),
        alpha=0.05,
        method="fdr_bh",
    )[1]
    effect_results.to_csv(output_dir / "paired_effect_sizes.csv", index=False)
    return model_results, effect_results


def plot_band_topographies(
    features: pd.DataFrame,
    channels: list[str],
    output_dir: str | Path,
) -> Path:
    """Plot 16-channel near-N2 minus early-baseline scalp changes."""
    output_dir = Path(output_dir)
    clean = features[features["is_clean"]].copy()
    clean["relative_time_min"] = _relative_time(clean)
    montage = mne.channels.make_standard_montage("standard_1020")
    info = mne.create_info(channels, sfreq=250, ch_types="eeg")
    info.set_montage(montage)

    figure, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for axis, band in zip(axes, ("beta", "alpha", "theta"), strict=True):
        columns = [f"ch__{channel}__{band}_log" for channel in channels]
        baseline = _early_baseline_means(clean, columns)
        near_n2 = (
            clean[clean["relative_time_min"].between(-5, 0, inclusive="left")]
            .groupby("subject_id")[columns]
            .mean()
        )
        common = baseline.index.intersection(near_n2.index)
        differences = near_n2.loc[common] - baseline.loc[common]
        values = differences.mean(axis=0).to_numpy()
        if len(common) >= 2:
            p_values = np.array(
                [
                    stats.ttest_rel(
                        near_n2.loc[common, column],
                        baseline.loc[common, column],
                    ).pvalue
                    for column in columns
                ]
            )
            p_values = np.nan_to_num(p_values, nan=1.0)
            significant = multipletests(
                p_values,
                alpha=0.05,
                method="fdr_bh",
            )[0]
        else:
            significant = np.zeros(len(columns), dtype=bool)
        limit = max(float(np.nanmax(np.abs(values))), 1e-6)
        image, _ = mne.viz.plot_topomap(
            values,
            info,
            axes=axis,
            show=False,
            contours=6,
            cmap="RdBu_r",
            vlim=(-limit, limit),
            mask=significant,
            mask_params={
                "marker": "o",
                "markerfacecolor": "none",
                "markeredgecolor": "black",
                "linewidth": 1,
                "markersize": 7,
            },
        )
        axis.set_title(f"{band.title()}: near N2 − baseline")
        figure.colorbar(image, ax=axis, shrink=0.75, label="Δ log power")
    figure.tight_layout()
    destination = output_dir / "band_topographies_16ch.png"
    figure.savefig(destination, dpi=220, bbox_inches="tight")
    figure.savefig(
        output_dir / "band_topographies_16ch.pdf",
        bbox_inches="tight",
    )
    plt.close(figure)
    return destination
