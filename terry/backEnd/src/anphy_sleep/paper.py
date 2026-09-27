from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


OUTCOME_LABELS = {
    "frontal_beta_log": "Frontal beta",
    "posterior_alpha_log": "Posterior alpha",
    "central_theta_log": "Central theta",
}
MODEL_LABELS = {
    "logistic_regression": "Logistic regression",
    "random_forest": "Random forest",
    "svm": "Linear SVM",
}


def _paper_style() -> None:
    sns.set_theme(
        context="paper",
        style="ticks",
        font_scale=1.1,
        rc={
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "axes.spines.top": False,
            "axes.spines.right": False,
        },
    )


def _save_figure(figure: plt.Figure, directory: Path, stem: str) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"{stem}.png", directory / f"{stem}.pdf"]
    for path in paths:
        figure.savefig(path, bbox_inches="tight")
    plt.close(figure)
    return paths


def _plot_effect_forest(effects: pd.DataFrame, output_dir: Path) -> list[Path]:
    ordered = effects.set_index("outcome").loc[list(OUTCOME_LABELS)].reset_index()
    y = np.arange(len(ordered))
    values = ordered["cohen_dz"].to_numpy()
    lower = values - ordered["cohen_dz_ci95_low"].to_numpy()
    upper = ordered["cohen_dz_ci95_high"].to_numpy() - values
    figure, axis = plt.subplots(figsize=(7.2, 3.8))
    axis.errorbar(
        values,
        y,
        xerr=np.vstack([lower, upper]),
        fmt="o",
        color="#2C5F8A",
        ecolor="#61788A",
        capsize=4,
    )
    axis.axvline(0, color="black", linewidth=1, linestyle="--")
    axis.set_yticks(y, [OUTCOME_LABELS[name] for name in ordered["outcome"]])
    axis.set_xlabel("Paired effect size, Cohen's dz (95% bootstrap CI)")
    axis.set_title("Change from early pre-N2 baseline to the final 5 minutes")
    axis.invert_yaxis()
    return _save_figure(figure, output_dir, "figure_effect_sizes")


def _plot_model_performance(metrics: pd.DataFrame, output_dir: Path) -> list[Path]:
    ordered = metrics.set_index("model").loc[list(MODEL_LABELS)].reset_index()
    measures = [
        ("auc_mean", "AUC"),
        ("balanced_accuracy_mean", "Balanced accuracy"),
        ("f1_mean", "F1"),
    ]
    x = np.arange(len(ordered))
    width = 0.24
    figure, axis = plt.subplots(figsize=(8.2, 4.6))
    colors = sns.color_palette("colorblind", n_colors=len(measures))
    for index, ((column, label), color) in enumerate(zip(measures, colors, strict=True)):
        axis.bar(
            x + (index - 1) * width,
            ordered[column],
            width,
            label=label,
            color=color,
        )
    axis.set_xticks(x, [MODEL_LABELS[name] for name in ordered["model"]])
    axis.set_ylim(0.5, 0.9)
    axis.set_ylabel("Mean leave-one-subject-out score")
    axis.set_title("Future-5-minute stable-N2 prediction")
    axis.legend(frameon=False, ncol=3, loc="upper center")
    return _save_figure(figure, output_dir, "figure_model_performance")


def _plot_signal_quality(quality: pd.DataFrame, output_dir: Path) -> list[Path]:
    ordered = quality.sort_values("clean_window_percent")
    figure, axis = plt.subplots(figsize=(9, 5.2))
    colors = np.where(
        ordered["clean_window_percent"] >= 70,
        "#4B7F52",
        "#B25B4B",
    )
    axis.bar(
        ordered["subject_id"],
        ordered["clean_window_percent"],
        color=colors,
    )
    axis.axhline(70, color="black", linestyle="--", linewidth=1, label="70% sensitivity threshold")
    axis.set_ylim(0, 105)
    axis.set_ylabel("Clean windows (%)")
    axis.set_xlabel("Participant")
    axis.set_title("Participant-level EEG signal quality")
    axis.tick_params(axis="x", rotation=70)
    axis.legend(frameon=False)
    return _save_figure(figure, output_dir, "figure_signal_quality")


def _plot_logistic_coefficients(
    coefficients: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    ordered = coefficients.sort_values("standardized_coefficient")
    figure, axis = plt.subplots(figsize=(8, 5.4))
    colors = [
        "#B25B4B" if value < 0 else "#4B7F52"
        for value in ordered["standardized_coefficient"]
    ]
    axis.barh(
        ordered["feature"].str.replace("_", " ", regex=False),
        ordered["standardized_coefficient"],
        color=colors,
    )
    axis.axvline(0, color="black", linewidth=1)
    axis.set_xlabel("Standardized coefficient in final logistic model")
    axis.set_title("Interpretable EEG feature contributions")
    return _save_figure(figure, output_dir, "figure_logistic_coefficients")


def _summarize_spindles(processed_dir: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(processed_dir.glob("EPCTL*/spindles.csv")):
        data = pd.read_csv(path)
        if "time_to_n2_min" not in data:
            continue
        rows.append(
            {
                "subject_id": path.parent.name,
                "pre_n2_5m_count": int(
                    data["time_to_n2_min"].between(0, 5, inclusive="right").sum()
                ),
                "post_n2_5m_count": int(
                    data["time_to_n2_min"].between(-5, 0, inclusive="left").sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def _plot_spindle_transition(spindles: pd.DataFrame, output_dir: Path) -> list[Path]:
    figure, axis = plt.subplots(figsize=(5.8, 4.8))
    for row in spindles.itertuples(index=False):
        axis.plot(
            [0, 1],
            [row.pre_n2_5m_count, row.post_n2_5m_count],
            color="#A8B0B5",
            linewidth=0.8,
            alpha=0.7,
        )
    axis.scatter(
        np.zeros(len(spindles)),
        spindles["pre_n2_5m_count"],
        color="#2C5F8A",
        s=24,
        zorder=3,
    )
    axis.scatter(
        np.ones(len(spindles)),
        spindles["post_n2_5m_count"],
        color="#4B7F52",
        s=24,
        zorder=3,
    )
    axis.set_xticks([0, 1], ["5 min before stable N2", "5 min after stable N2"])
    axis.set_ylabel("Detected central spindle count")
    axis.set_title("Within-participant spindle transition")
    return _save_figure(figure, output_dir, "figure_spindle_transition")


def _subject_baseline_trajectories(features: pd.DataFrame) -> pd.DataFrame:
    outcomes = list(OUTCOME_LABELS)
    clean = features[features["is_clean"]].copy()
    clean["relative_time_min"] = -clean["time_to_n2_min"]
    clean["minute_bin"] = np.floor(clean["relative_time_min"]).astype(int)
    subject_minutes = (
        clean.groupby(["subject_id", "minute_bin"], as_index=False)[outcomes]
        .mean()
    )
    baseline_rows = []
    for subject_id, group in subject_minutes.groupby("subject_id"):
        eligible = group[group["minute_bin"] < -5].sort_values("minute_bin")
        if eligible.empty:
            continue
        start = int(eligible["minute_bin"].min())
        baseline = eligible[
            (eligible["minute_bin"] >= start)
            & (eligible["minute_bin"] < min(start + 5, -5))
        ]
        if baseline.empty:
            continue
        row = {"subject_id": subject_id}
        row.update(
            {
                f"{outcome}_baseline": float(baseline[outcome].mean())
                for outcome in outcomes
            }
        )
        baseline_rows.append(row)
    baselines = pd.DataFrame(baseline_rows)
    aligned = subject_minutes.merge(baselines, on="subject_id", how="inner")
    for outcome in outcomes:
        aligned[f"{outcome}_change"] = (
            aligned[outcome] - aligned[f"{outcome}_baseline"]
        )
    return aligned


def _draw_effect_forest(axis: plt.Axes, effects: pd.DataFrame) -> None:
    ordered = effects.set_index("outcome").loc[list(OUTCOME_LABELS)].reset_index()
    y = np.arange(len(ordered))
    values = ordered["cohen_dz"].to_numpy()
    lower = values - ordered["cohen_dz_ci95_low"].to_numpy()
    upper = ordered["cohen_dz_ci95_high"].to_numpy() - values
    axis.errorbar(
        values,
        y,
        xerr=np.vstack([lower, upper]),
        fmt="o",
        markersize=7,
        color="#244E70",
        ecolor="#6E8291",
        capsize=4,
        linewidth=1.6,
    )
    axis.axvline(0, color="#333333", linewidth=1, linestyle="--")
    axis.set_yticks(y, [OUTCOME_LABELS[name] for name in ordered["outcome"]])
    axis.set_xlabel("Cohen's dz (95% bootstrap CI)")
    axis.set_title("B  Within-participant effects", loc="left", fontweight="bold")
    axis.invert_yaxis()


def _plot_main_neurophysiology(
    features: pd.DataFrame,
    effects: pd.DataFrame,
    spindles: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    trajectories = _subject_baseline_trajectories(features)
    colors = {
        "frontal_beta_log": "#2F6690",
        "posterior_alpha_log": "#80558C",
        "central_theta_log": "#C26A32",
    }
    figure = plt.figure(figsize=(11.8, 8.2))
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=[1.15, 1],
        width_ratios=[1.05, 0.95],
        hspace=0.42,
        wspace=0.42,
    )
    trajectory_axis = figure.add_subplot(grid[0, :])
    effect_axis = figure.add_subplot(grid[1, 0])
    spindle_axis = figure.add_subplot(grid[1, 1])

    for outcome, label in OUTCOME_LABELS.items():
        column = f"{outcome}_change"
        summary = trajectories.groupby("minute_bin")[column].agg(
            ["mean", "std", "count"]
        )
        ci = 1.96 * summary["std"] / np.sqrt(summary["count"])
        trajectory_axis.plot(
            summary.index,
            summary["mean"],
            color=colors[outcome],
            linewidth=2.4,
            label=label,
        )
        trajectory_axis.fill_between(
            summary.index,
            summary["mean"] - ci,
            summary["mean"] + ci,
            color=colors[outcome],
            alpha=0.14,
            linewidth=0,
        )
    trajectory_axis.axhline(0, color="#777777", linewidth=0.8)
    trajectory_axis.axvline(0, color="#222222", linestyle="--", linewidth=1.2)
    trajectory_axis.axvspan(-5, 0, color="#D9B44A", alpha=0.08)
    trajectory_axis.text(
        -2.5,
        trajectory_axis.get_ylim()[1],
        "prediction horizon",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#775D16",
    )
    trajectory_axis.set_xlim(-20, 9)
    trajectory_axis.set_xlabel("Time relative to first stable N2 (min)")
    trajectory_axis.set_ylabel("Change from early baseline (log₁₀ power)")
    trajectory_axis.set_title(
        "A  Coordinated spectral transition into stable N2",
        loc="left",
        fontweight="bold",
    )
    trajectory_axis.legend(frameon=False, ncol=3, loc="lower left")

    _draw_effect_forest(effect_axis, effects)

    for row in spindles.itertuples(index=False):
        spindle_axis.plot(
            [0, 1],
            [row.pre_n2_5m_count, row.post_n2_5m_count],
            color="#AAB2B8",
            linewidth=0.7,
            alpha=0.48,
            zorder=1,
        )
    spindle_axis.scatter(
        np.zeros(len(spindles)),
        spindles["pre_n2_5m_count"],
        color="#2F6690",
        alpha=0.75,
        s=25,
        zorder=2,
    )
    spindle_axis.scatter(
        np.ones(len(spindles)),
        spindles["post_n2_5m_count"],
        color="#4C8055",
        alpha=0.75,
        s=25,
        zorder=2,
    )
    medians = [
        float(spindles["pre_n2_5m_count"].median()),
        float(spindles["post_n2_5m_count"].median()),
    ]
    spindle_axis.scatter(
        [0, 1],
        medians,
        marker="D",
        s=70,
        color="#1E252B",
        label="Median",
        zorder=3,
    )
    for x, value in enumerate(medians):
        spindle_axis.text(
            x + 0.05,
            value,
            f"{value:g}",
            va="center",
            fontsize=9,
            fontweight="bold",
        )
    spindle_axis.set_xticks([0, 1], ["Pre-N2\n5 min", "Post-N2\n5 min"])
    spindle_axis.set_ylabel("Central spindle count")
    spindle_axis.set_title(
        "C  Physiological validation of N2 onset",
        loc="left",
        fontweight="bold",
    )
    spindle_axis.legend(frameon=False, loc="upper left")

    figure.suptitle(
        "Interpretable 16-channel EEG markers of sleep onset",
        fontsize=16,
        fontweight="bold",
        y=0.99,
    )
    figure.text(
        0.5,
        0.01,
        "N = 28 healthy adults · lines and intervals in panel A are participant-balanced means and 95% CIs",
        ha="center",
        fontsize=9,
        color="#555555",
    )
    return _save_figure(figure, output_dir, "main_figure_neurophysiology")


def _bootstrap_metric_ci(
    data: pd.DataFrame,
    model: str,
    column: str,
    seed: int = 42,
) -> tuple[float, float, float]:
    values = data.loc[data["model"] == model, column].dropna().to_numpy()
    rng = np.random.default_rng(seed)
    boot = np.asarray(
        [
            rng.choice(values, size=len(values), replace=True).mean()
            for _ in range(2_000)
        ]
    )
    return (
        float(values.mean()),
        float(np.quantile(boot, 0.025)),
        float(np.quantile(boot, 0.975)),
    )


def _plot_main_prediction(
    fold_metrics: pd.DataFrame,
    lead_times: pd.DataFrame,
    coefficients: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    order = list(MODEL_LABELS)
    labels = [MODEL_LABELS[name] for name in order]
    palette = ["#2F6690", "#C27A2C", "#4C8055"]
    figure, axes = plt.subplots(2, 2, figsize=(12, 9))
    auc_axis, operating_axis, lead_axis, coefficient_axis = axes.ravel()

    sns.violinplot(
        data=fold_metrics,
        x="model",
        y="auc",
        hue="model",
        order=order,
        hue_order=order,
        palette=palette,
        inner=None,
        cut=0,
        linewidth=0.8,
        saturation=0.7,
        legend=False,
        ax=auc_axis,
    )
    sns.stripplot(
        data=fold_metrics,
        x="model",
        y="auc",
        order=order,
        color="#27323A",
        alpha=0.55,
        size=3.5,
        jitter=0.18,
        ax=auc_axis,
    )
    auc_axis.axhline(0.5, color="#777777", linestyle="--", linewidth=1)
    auc_axis.set_xticks(range(len(labels)), labels)
    auc_axis.set_xlabel("")
    auc_axis.set_ylabel("Subject-level AUC")
    auc_axis.set_ylim(0.35, 1.02)
    auc_axis.set_title(
        "A  LOSO performance across held-out participants",
        loc="left",
        fontweight="bold",
    )

    metric_specs = [
        ("sensitivity", "Sensitivity", -0.12, "#2F6690"),
        ("specificity", "Specificity", 0.12, "#C26A32"),
    ]
    for column, label, offset, color in metric_specs:
        means, lower, upper = [], [], []
        for model in order:
            mean, low, high = _bootstrap_metric_ci(
                fold_metrics,
                model,
                column,
            )
            means.append(mean)
            lower.append(mean - low)
            upper.append(high - mean)
        x = np.arange(len(order)) + offset
        operating_axis.errorbar(
            x,
            means,
            yerr=np.vstack([lower, upper]),
            fmt="o",
            markersize=7,
            capsize=4,
            linewidth=1.6,
            color=color,
            label=label,
        )
    operating_axis.set_xticks(range(len(labels)), labels)
    operating_axis.set_ylim(0.5, 0.9)
    operating_axis.set_ylabel("Mean score (subject-bootstrap 95% CI)")
    operating_axis.set_title(
        "B  Operating characteristics",
        loc="left",
        fontweight="bold",
    )
    operating_axis.legend(frameon=False, loc="upper center", ncol=2)

    detected = lead_times[lead_times["alert_detected"]].copy()
    sns.stripplot(
        data=detected,
        x="model",
        y="first_sustained_alert_lead_min",
        hue="model",
        order=order,
        hue_order=order,
        palette=palette,
        jitter=0.2,
        alpha=0.72,
        size=5,
        legend=False,
        ax=lead_axis,
    )
    lead_axis.axhspan(0, 5, color="#4C8055", alpha=0.10)
    lead_axis.axhline(5, color="#4C8055", linestyle="--", linewidth=1)
    lead_axis.set_xticks(range(len(labels)), labels)
    lead_axis.set_xlabel("")
    lead_axis.set_ylabel("First sustained alert lead time (min)")
    lead_axis.set_title(
        "C  Alert timing and the target 0–5 min zone",
        loc="left",
        fontweight="bold",
    )
    ordered_coefficients = (
        coefficients.assign(
            magnitude=coefficients["standardized_coefficient"].abs()
        )
        .nlargest(8, "magnitude")
        .sort_values("standardized_coefficient")
    )
    coefficient_colors = [
        "#B75D4A" if value < 0 else "#4C8055"
        for value in ordered_coefficients["standardized_coefficient"]
    ]
    coefficient_axis.barh(
        ordered_coefficients["feature"].str.replace("_", " ", regex=False),
        ordered_coefficients["standardized_coefficient"],
        color=coefficient_colors,
        alpha=0.9,
    )
    coefficient_axis.axvline(0, color="#333333", linewidth=1)
    coefficient_axis.set_xlabel("Standardized coefficient")
    coefficient_axis.set_title(
        "D  Final interpretable logistic model",
        loc="left",
        fontweight="bold",
    )

    figure.suptitle(
        "Subject-independent prediction of stable N2 within five minutes",
        fontsize=16,
        fontweight="bold",
        y=0.99,
    )
    figure.tight_layout(rect=(0, 0.02, 1, 0.96), h_pad=3.0, w_pad=2.5)
    figure.text(
        0.5,
        0.008,
        (
            "Each point in panel A is one held-out participant. Panel C in-target alerts: "
            "logistic 13/28, random forest 16/28, SVM 12/28; each model had 2 no-alert cases."
        ),
        ha="center",
        fontsize=8.5,
        color="#555555",
    )
    return _save_figure(figure, output_dir, "main_figure_prediction")


def _plot_stage_transition_figure(
    epoch_features: pd.DataFrame,
    stage_metrics: pd.DataFrame,
    confusion: pd.DataFrame,
    contrasts: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    stages = ["W", "N1", "N2"]
    feature_order = [
        "frontal_beta_log",
        "posterior_alpha_log",
        "central_theta_log",
        "central_sigma_log",
        "frontocentral_delta_log",
    ]
    feature_labels = [
        "Frontal beta",
        "Posterior alpha",
        "Central theta",
        "Central sigma",
        "Frontocentral delta",
    ]
    subject_stage = (
        epoch_features.groupby(["subject_id", "stage"], as_index=False)[
            feature_order
        ]
        .mean()
    )
    figure, axes = plt.subplots(2, 2, figsize=(12, 9))
    profile_axis, effect_axis, confusion_axis, performance_axis = axes.ravel()

    colors = ["#2F6690", "#80558C", "#C26A32", "#4C8055", "#707B84"]
    for feature, label, color in zip(
        feature_order,
        feature_labels,
        colors,
        strict=True,
    ):
        wide = subject_stage.pivot(
            index="subject_id",
            columns="stage",
            values=feature,
        )[stages].dropna()
        change = wide.subtract(wide["W"], axis=0)
        means = change.mean(axis=0)
        ci = 1.96 * change.std(axis=0, ddof=1) / np.sqrt(len(change))
        x = np.arange(len(stages))
        profile_axis.plot(
            x,
            means,
            marker="o",
            linewidth=2,
            color=color,
            label=label,
        )
        profile_axis.fill_between(
            x,
            means - ci,
            means + ci,
            color=color,
            alpha=0.12,
            linewidth=0,
        )
    profile_axis.axhline(0, color="#777777", linewidth=0.8)
    profile_axis.set_xticks(range(3), stages)
    profile_axis.set_ylabel("Change from W (log₁₀ band power)")
    profile_axis.set_title(
        "A  PSD-derived physiological profiles",
        loc="left",
        fontweight="bold",
    )
    profile_axis.legend(frameon=False, fontsize=8, ncol=2)

    contrast_order = ["N1_minus_W", "N2_minus_N1"]
    effect_matrix = (
        contrasts.pivot(
            index="feature",
            columns="contrast",
            values="cohen_dz",
        )
        .loc[feature_order, contrast_order]
    )
    significance = (
        contrasts.pivot(
            index="feature",
            columns="contrast",
            values="paired_t_p_value_fdr",
        )
        .loc[feature_order, contrast_order]
    )
    annotations = np.empty(effect_matrix.shape, dtype=object)
    for row in range(effect_matrix.shape[0]):
        for column in range(effect_matrix.shape[1]):
            marker = "*" if significance.iloc[row, column] < 0.05 else ""
            annotations[row, column] = (
                f"{effect_matrix.iloc[row, column]:.2f}{marker}"
            )
    sns.heatmap(
        effect_matrix,
        annot=annotations,
        fmt="",
        center=0,
        cmap="vlag",
        vmin=-2.2,
        vmax=2.2,
        linewidths=0.8,
        linecolor="white",
        cbar_kws={"label": "Cohen's dz"},
        yticklabels=feature_labels,
        xticklabels=["W → N1", "N1 → N2"],
        ax=effect_axis,
    )
    effect_axis.set_xlabel("")
    effect_axis.set_ylabel("")
    effect_axis.set_title(
        "B  Stage-transition effect sizes",
        loc="left",
        fontweight="bold",
    )
    effect_axis.text(
        0,
        -0.14,
        "* FDR-adjusted p < 0.05",
        transform=effect_axis.transAxes,
        fontsize=8,
        color="#555555",
    )

    matrix = confusion.loc[
        [f"true_{stage}" for stage in stages],
        [f"pred_{stage}" for stage in stages],
    ]
    sns.heatmap(
        matrix,
        annot=True,
        fmt=".2f",
        cmap="Blues",
        vmin=0,
        vmax=1,
        square=True,
        linewidths=1,
        linecolor="white",
        cbar_kws={"label": "Row-normalized proportion"},
        xticklabels=stages,
        yticklabels=stages,
        ax=confusion_axis,
    )
    confusion_axis.set_xlabel("Predicted state")
    confusion_axis.set_ylabel("AASM reference state")
    confusion_axis.set_title(
        "C  LOSO confusion matrix: dynamic logistic model",
        loc="left",
        fontweight="bold",
    )

    model_order = [
        "logistic_static",
        "logistic_dynamic",
        "random_forest_dynamic",
        "svm_dynamic",
    ]
    model_labels = [
        "Logistic · static",
        "Logistic · + dynamics",
        "Random forest · + dynamics",
        "Linear SVM · + dynamics",
    ]
    ordered = stage_metrics.set_index("model").loc[model_order]
    x = np.arange(len(model_order))
    for metric, label, offset, color in [
        ("balanced_accuracy", "Balanced accuracy", -0.12, "#2F6690"),
        ("macro_f1", "Macro-F1", 0.12, "#C26A32"),
    ]:
        mean = ordered[f"{metric}_mean"].to_numpy()
        lower = mean - ordered[f"{metric}_ci95_low"].to_numpy()
        upper = ordered[f"{metric}_ci95_high"].to_numpy() - mean
        performance_axis.errorbar(
            x + offset,
            mean,
            yerr=np.vstack([lower, upper]),
            fmt="o",
            capsize=4,
            linewidth=1.5,
            color=color,
            label=label,
        )
    performance_axis.set_xticks(x, model_labels, rotation=18, ha="right")
    performance_axis.set_ylim(0.5, 0.9)
    performance_axis.set_ylabel("Mean held-out-participant score")
    performance_axis.set_title(
        "D  30-second W/N1/N2 classification",
        loc="left",
        fontweight="bold",
    )
    performance_axis.legend(frameon=False, loc="upper right")

    figure.suptitle(
        "Interpretable recognition of W–N1–N2 state transitions",
        fontsize=16,
        fontweight="bold",
        y=0.99,
    )
    figure.tight_layout(rect=(0, 0.025, 1, 0.96), h_pad=3, w_pad=2.5)
    figure.text(
        0.5,
        0.008,
        "N = 28; classification and uncertainty are evaluated at the AASM 30-second epoch level with leave-one-subject-out validation.",
        ha="center",
        fontsize=8.5,
        color="#555555",
    )
    return _save_figure(figure, output_dir, "main_figure_stage_transition")


def _plot_continuous_prediction_figure(
    fold_metrics: pd.DataFrame,
    summary: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    model_order = [
        "time_only",
        "stage_oracle",
        "static_eeg",
        "dynamic_eeg",
        "dynamic_eeg_plus_time",
    ]
    labels = [
        "Elapsed time\n(spline)",
        "AASM state\n(oracle)",
        "Static EEG",
        "EEG + dynamics",
        "EEG + dynamics\n+ time",
    ]
    colors = ["#8B949B", "#B78A45", "#5A7D9A", "#2F6690", "#4C8055"]
    selected = fold_metrics[fold_metrics["model"].isin(model_order)].copy()
    figure, axes = plt.subplots(2, 2, figsize=(12, 8.8))
    auc_axis, ap_axis, event_axis, delta_axis = axes.ravel()

    for axis, metric, title, chance in [
        (auc_axis, "auc", "A  Subject-level discrimination", 0.5),
        (
            ap_axis,
            "average_precision",
            "B  Precision–recall performance",
            None,
        ),
    ]:
        sns.boxplot(
            data=selected,
            x="model",
            y=metric,
            order=model_order,
            hue="model",
            hue_order=model_order,
            palette=colors,
            showfliers=False,
            legend=False,
            width=0.58,
            ax=axis,
        )
        sns.stripplot(
            data=selected,
            x="model",
            y=metric,
            order=model_order,
            color="#30383E",
            alpha=0.48,
            jitter=0.16,
            size=3,
            ax=axis,
        )
        if chance is not None:
            axis.axhline(
                chance,
                color="#777777",
                linestyle="--",
                linewidth=1,
            )
        axis.set_xticks(range(len(labels)), labels, rotation=15, ha="right")
        axis.set_xlabel("")
        axis.set_ylabel(
            "Subject-level AUC"
            if metric == "auc"
            else "Subject-level average precision"
        )
        axis.set_title(title, loc="left", fontweight="bold")

    ordered = summary.set_index("model").loc[model_order]
    event_axis.scatter(
        ordered["median_false_alerts_per_hour"],
        ordered["target_event_sensitivity"],
        s=90,
        c=colors,
    )
    for model, label, color in zip(
        model_order,
        labels,
        colors,
        strict=True,
    ):
        row = ordered.loc[model]
        event_axis.annotate(
            label.replace("\n", " "),
            (
                row["median_false_alerts_per_hour"],
                row["target_event_sensitivity"],
            ),
            xytext=(5, 4),
            textcoords="offset points",
            fontsize=8,
            color=color,
        )
    event_axis.set_xlabel("Median early false alerts per pre-target hour")
    event_axis.set_ylabel("Target-event sensitivity")
    event_axis.set_ylim(0, 1.05)
    event_axis.set_title(
        "C  Event-level operating trade-off",
        loc="left",
        fontweight="bold",
    )

    static = (
        fold_metrics[fold_metrics["model"] == "static_eeg"]
        .set_index("subject_id")["auc"]
    )
    dynamic = (
        fold_metrics[fold_metrics["model"] == "dynamic_eeg"]
        .set_index("subject_id")["auc"]
    )
    differences = (dynamic - static).dropna().sort_values()
    rng = np.random.default_rng(42)
    bootstrap = np.asarray(
        [
            rng.choice(
                differences.to_numpy(),
                size=len(differences),
                replace=True,
            ).mean()
            for _ in range(5_000)
        ]
    )
    difference_ci = np.quantile(bootstrap, [0.025, 0.975])
    delta_axis.axhline(0, color="#777777", linestyle="--", linewidth=1)
    delta_axis.scatter(
        np.arange(len(differences)),
        differences,
        c=np.where(differences >= 0, "#4C8055", "#B75D4A"),
        s=30,
        alpha=0.85,
    )
    delta_axis.axhline(
        differences.mean(),
        color="#1E252B",
        linewidth=2,
        label=(
            f"Mean ΔAUC = {differences.mean():.3f} "
            f"[{difference_ci[0]:.3f}, {difference_ci[1]:.3f}]"
        ),
    )
    delta_axis.set_xlabel("Held-out participant, sorted")
    delta_axis.set_ylabel("AUC: dynamic EEG − static EEG")
    delta_axis.set_title(
        "D  Incremental value of one-minute dynamics",
        loc="left",
        fontweight="bold",
    )
    delta_axis.legend(frameon=False)

    figure.suptitle(
        "Record-start evaluation of future stable-N2 prediction",
        fontsize=16,
        fontweight="bold",
        y=0.99,
    )
    figure.tight_layout(rect=(0, 0.025, 1, 0.96), h_pad=3, w_pad=2.5)
    figure.text(
        0.5,
        0.008,
        "Streams begin at recording start rather than a future N2-defined boundary; AASM-state oracle is analytical and not a deployable input.",
        ha="center",
        fontsize=8.5,
        color="#555555",
    )
    return _save_figure(
        figure,
        output_dir,
        "main_figure_continuous_prediction",
    )


def build_paper_outputs(config: dict[str, Any]) -> dict[str, object]:
    """Build publication-ready figures, tables, and a reproducibility manifest."""
    _paper_style()
    results_dir = Path(config["data"]["results_dir"])
    processed_dir = Path(config["data"]["processed_dir"])
    paper_dir = results_dir / "paper"
    figure_dir = paper_dir / "figures"
    table_dir = paper_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)

    required = {
        "effects": results_dir / "paired_effect_sizes.csv",
        "metrics": results_dir / "model_comparison.csv",
        "quality": results_dir / "signal_quality_summary.csv",
        "coefficients": results_dir / "logistic_coefficients.csv",
        "mixed": results_dir / "mixed_effects_results.csv",
    }
    missing = [str(path) for path in required.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Run 'anphy-sleep analyze' and 'anphy-sleep predict' first; "
            f"missing outputs: {missing}"
        )

    effects = pd.read_csv(required["effects"])
    metrics = pd.read_csv(required["metrics"])
    quality = pd.read_csv(required["quality"])
    coefficients = pd.read_csv(required["coefficients"])
    mixed = pd.read_csv(required["mixed"])
    spindles = _summarize_spindles(processed_dir)

    figure_paths = []
    figure_paths += _plot_effect_forest(effects, figure_dir)
    figure_paths += _plot_model_performance(metrics, figure_dir)
    figure_paths += _plot_signal_quality(quality, figure_dir)
    figure_paths += _plot_logistic_coefficients(coefficients, figure_dir)
    if not spindles.empty:
        figure_paths += _plot_spindle_transition(spindles, figure_dir)
        spindles.to_csv(table_dir / "spindle_transition.csv", index=False)

    composite_inputs = {
        "features": results_dir / "cohort_features.parquet",
        "fold_metrics": results_dir / "loso_fold_metrics.csv",
        "lead_times": results_dir / "prediction_lead_times.csv",
    }
    if all(path.exists() for path in composite_inputs.values()) and not spindles.empty:
        cohort_features = pd.read_parquet(composite_inputs["features"])
        fold_metrics = pd.read_csv(composite_inputs["fold_metrics"])
        lead_times = pd.read_csv(composite_inputs["lead_times"])
        figure_paths += _plot_main_neurophysiology(
            cohort_features,
            effects,
            spindles,
            figure_dir,
        )
        figure_paths += _plot_main_prediction(
            fold_metrics,
            lead_times,
            coefficients,
            figure_dir,
        )

    stage_inputs = {
        "epochs": results_dir / "stage_epoch_features.parquet",
        "metrics": results_dir / "stage_model_comparison.csv",
        "confusion": results_dir / "stage_confusion_matrix.csv",
        "contrasts": results_dir / "stage_power_contrasts.csv",
    }
    if all(path.exists() for path in stage_inputs.values()):
        figure_paths += _plot_stage_transition_figure(
            pd.read_parquet(stage_inputs["epochs"]),
            pd.read_csv(stage_inputs["metrics"]),
            pd.read_csv(stage_inputs["confusion"], index_col=0),
            pd.read_csv(stage_inputs["contrasts"]),
            figure_dir,
        )

    continuous_inputs = {
        "fold_metrics": results_dir / "continuous_loso_fold_metrics.csv",
        "summary": results_dir / "continuous_model_comparison.csv",
    }
    if all(path.exists() for path in continuous_inputs.values()):
        figure_paths += _plot_continuous_prediction_figure(
            pd.read_csv(continuous_inputs["fold_metrics"]),
            pd.read_csv(continuous_inputs["summary"]),
            figure_dir,
        )

    effects.to_csv(table_dir / "paired_effect_sizes.csv", index=False)
    mixed.to_csv(table_dir / "mixed_effects_results.csv", index=False)
    metrics.to_csv(table_dir / "model_comparison.csv", index=False)
    quality.to_csv(table_dir / "signal_quality_summary.csv", index=False)
    coefficients.to_csv(table_dir / "logistic_coefficients.csv", index=False)
    for optional_name in [
        "stage_model_comparison.csv",
        "stage_confusion_matrix.csv",
        "stage_power_summary.csv",
        "stage_power_contrasts.csv",
        "continuous_model_comparison.csv",
        "continuous_event_metrics.csv",
        "continuous_auc_ablation_comparisons.csv",
    ]:
        source = results_dir / optional_name
        if source.exists():
            (table_dir / optional_name).write_bytes(source.read_bytes())

    cohort_summary = pd.DataFrame(
        [
            {
                "participants": int(quality["subject_id"].nunique()),
                "total_windows": int(quality["total_windows"].sum()),
                "clean_windows": int(quality["clean_windows"].sum()),
                "overall_clean_percent": float(
                    100 * quality["clean_windows"].sum() / quality["total_windows"].sum()
                ),
                "median_participant_clean_percent": float(
                    quality["clean_window_percent"].median()
                ),
                "participants_below_70_percent": int(
                    (quality["clean_window_percent"] < 70).sum()
                ),
            }
        ]
    )
    cohort_summary.to_csv(table_dir / "cohort_summary.csv", index=False)

    manifest = {
        "participants": int(quality["subject_id"].nunique()),
        "stable_n2_definition_seconds": float(
            config["epoching"]["stable_n2_seconds"]
        ),
        "target_channels": list(config["channels"]["target"]),
        "window_seconds": float(config["epoching"]["window_seconds"]),
        "step_seconds": float(config["epoching"]["step_seconds"]),
        "figures": [str(path) for path in figure_paths],
        "tables": [str(path) for path in sorted(table_dir.glob("*.csv"))],
        "scientific_scope": (
            "Healthy-adult offline validation; not a clinical diagnostic or "
            "validated closed-loop music intervention."
        ),
    }
    manifest_path = paper_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "paper_dir": str(paper_dir),
        "manifest": str(manifest_path),
        "figure_count": len(figure_paths),
        "table_count": len(manifest["tables"]),
    }
