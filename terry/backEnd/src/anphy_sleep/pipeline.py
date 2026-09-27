from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .features import detect_spindles, extract_window_features
from .io import discover_subject_dirs, extract_subject_archive
from .modeling import run_loso_prediction
from .preprocess import prepare_subject_segment
from .staging import run_stage_classification, run_stage_physiology
from .statistics import (
    plot_aligned_trajectories,
    plot_band_topographies,
    run_trajectory_statistics,
    summarize_signal_quality,
)
from .transition_prediction import run_continuous_prediction


def extract_available_archives(config: dict[str, Any]) -> list[Path]:
    """Extract downloaded EPCTL archives that do not yet have an EDF folder."""
    raw_dir = Path(config["data"]["raw_dir"])
    extracted_root = raw_dir / "extracted"
    extracted_root.mkdir(parents=True, exist_ok=True)
    extracted_subjects = []
    for archive in sorted(raw_dir.glob("EPCTL*.zip")):
        subject_id = archive.stem.split("-")[0].upper()
        existing = [
            path
            for path in discover_subject_dirs(extracted_root)
            if subject_id in str(path).upper()
        ]
        if existing:
            extracted_subjects.extend(existing)
            continue
        extracted_subjects.append(
            extract_subject_archive(archive, extracted_root / subject_id)
        )
    return extracted_subjects


def process_subject(
    subject_dir: str | Path,
    config: dict[str, Any],
) -> tuple[Path, Path]:
    """Run preprocessing and feature extraction for one subject."""
    segment = prepare_subject_segment(subject_dir, config)
    processed_root = Path(config["data"]["processed_dir"]) / segment.subject_id
    processed_root.mkdir(parents=True, exist_ok=True)

    features = extract_window_features(segment, config)
    feature_path = processed_root / "features.parquet"
    features.to_parquet(feature_path, index=False)

    spindles = detect_spindles(segment)
    spindle_path = processed_root / "spindles.csv"
    spindles.to_csv(spindle_path, index=False)

    metadata = {
        "subject_id": segment.subject_id,
        "stable_n2_onset_s": segment.stable_n2_onset_s,
        "segment_start_s": segment.segment_start_s,
        "segment_end_s": segment.segment_end_s,
        "sampling_frequency_hz": segment.raw.info["sfreq"],
        "channels": segment.raw.ch_names,
        "auxiliary_channels": (
            segment.auxiliary_raw.ch_names
            if segment.auxiliary_raw is not None
            else []
        ),
        "channel_mapping": segment.channel_mapping,
        "total_windows": int(len(features)),
        "clean_windows": int(features["is_clean"].sum()),
    }
    metadata_path = processed_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return feature_path, spindle_path


def process_continuous_subject(
    subject_dir: str | Path,
    config: dict[str, Any],
) -> Path:
    """Extract record-start-anchored features through ten minutes after stable N2."""
    segment = prepare_subject_segment(
        subject_dir,
        config,
        segment_mode="record_start",
    )
    processed_root = Path(config["data"]["processed_dir"]) / segment.subject_id
    processed_root.mkdir(parents=True, exist_ok=True)
    features = extract_window_features(segment, config)
    feature_path = processed_root / "continuous_features.parquet"
    features.to_parquet(feature_path, index=False)
    metadata = {
        "subject_id": segment.subject_id,
        "anchor": "record_start",
        "stable_n2_onset_s": segment.stable_n2_onset_s,
        "segment_start_s": segment.segment_start_s,
        "segment_end_s": segment.segment_end_s,
        "sampling_frequency_hz": segment.raw.info["sfreq"],
        "channels": segment.raw.ch_names,
        "total_windows": int(len(features)),
        "clean_windows": int(features["is_clean"].sum()),
    }
    (processed_root / "continuous_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return feature_path


def process_all_subjects(
    config: dict[str, Any],
    subject_id: str | None = None,
) -> list[Path]:
    """Process all extracted subjects, optionally restricted to one ID."""
    subject_dirs = discover_subject_dirs(
        Path(config["data"]["raw_dir"]) / "extracted"
    )
    if subject_id:
        subject_dirs = [
            path for path in subject_dirs if subject_id.upper() in str(path).upper()
        ]
    if not subject_dirs:
        raise FileNotFoundError("No extracted ANPHY subject EDF files were found")

    outputs = []
    failures = []
    processed_dir = Path(config["data"]["processed_dir"])
    for subject_dir in subject_dirs:
        current_id = next(
            (
                part.upper().split("-")[0]
                for part in subject_dir.parts
                if part.upper().startswith("EPCTL")
            ),
            subject_dir.name.upper(),
        )
        existing = processed_dir / current_id / "features.parquet"
        if subject_id is None and existing.exists():
            outputs.append(existing)
            continue
        try:
            feature_path, _ = process_subject(subject_dir, config)
            outputs.append(feature_path)
        except Exception as error:
            if subject_id is not None:
                raise
            failures.append(
                {
                    "subject_id": current_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
    failure_path = processed_dir / "processing_failures.csv"
    if failures:
        pd.DataFrame(failures).to_csv(failure_path, index=False)
    elif failure_path.exists():
        failure_path.unlink()
    if not outputs:
        raise RuntimeError("All extracted subjects failed processing")
    return outputs


def process_all_continuous_subjects(
    config: dict[str, Any],
    subject_id: str | None = None,
) -> list[Path]:
    """Build deployment-like record-start streams without future-event anchoring."""
    subject_dirs = discover_subject_dirs(
        Path(config["data"]["raw_dir"]) / "extracted"
    )
    if subject_id:
        subject_dirs = [
            path for path in subject_dirs if subject_id.upper() in str(path).upper()
        ]
    if not subject_dirs:
        raise FileNotFoundError("No extracted ANPHY subject EDF files were found")

    outputs = []
    failures = []
    processed_dir = Path(config["data"]["processed_dir"])
    for subject_dir in subject_dirs:
        current_id = next(
            (
                part.upper().split("-")[0]
                for part in subject_dir.parts
                if part.upper().startswith("EPCTL")
            ),
            subject_dir.name.upper(),
        )
        existing = processed_dir / current_id / "continuous_features.parquet"
        if subject_id is None and existing.exists():
            outputs.append(existing)
            continue
        try:
            outputs.append(process_continuous_subject(subject_dir, config))
        except Exception as error:
            if subject_id is not None:
                raise
            failures.append(
                {
                    "subject_id": current_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
    failure_path = processed_dir / "continuous_processing_failures.csv"
    if failures:
        pd.DataFrame(failures).to_csv(failure_path, index=False)
    elif failure_path.exists():
        failure_path.unlink()
    if not outputs:
        raise RuntimeError("All continuous subjects failed processing")
    return outputs


def load_cohort_features(config: dict[str, Any]) -> pd.DataFrame:
    """Combine all processed subject feature tables."""
    paths = sorted(Path(config["data"]["processed_dir"]).glob("EPCTL*/features.parquet"))
    if not paths:
        raise FileNotFoundError("No processed feature tables found")
    return pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)


def load_continuous_features(config: dict[str, Any]) -> pd.DataFrame:
    """Combine record-start-anchored feature streams."""
    paths = sorted(
        Path(config["data"]["processed_dir"]).glob(
            "EPCTL*/continuous_features.parquet"
        )
    )
    if not paths:
        raise FileNotFoundError(
            "No continuous feature tables found; run process-continuous first"
        )
    return pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)


def run_cohort_analysis(config: dict[str, Any]) -> dict[str, str]:
    """Generate quality, trajectory, topography, and inferential outputs."""
    features = load_cohort_features(config)
    output_dir = Path(config["data"]["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    summarize_signal_quality(features, output_dir)
    trajectory = plot_aligned_trajectories(features, output_dir)
    subject_count = int(features["subject_id"].nunique())
    if subject_count >= 10:
        run_trajectory_statistics(
            features,
            output_dir,
            random_seed=int(config["project"]["random_seed"]),
        )
    else:
        (output_dir / "pilot_status.json").write_text(
            json.dumps(
                {
                    "subject_count": subject_count,
                    "inferential_statistics_run": False,
                    "reason": "Fewer than ten subjects: outputs are restricted to technical and descriptive validation.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    topography = plot_band_topographies(
        features,
        list(config["channels"]["target"]),
        output_dir,
    )
    features.to_parquet(output_dir / "cohort_features.parquet", index=False)
    return {
        "trajectory_figure": str(trajectory),
        "topography_figure": str(topography),
    }


def run_prediction_analysis(config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run LOSO N2 prediction on all processed subjects."""
    features = load_cohort_features(config)
    output_dir = Path(config["data"]["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    return run_loso_prediction(features, config, output_dir)


def run_stage_analysis(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run W/N1/N2 epoch classification and PSD-derived stage contrasts."""
    features = load_cohort_features(config)
    output_dir = Path(config["data"]["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    summary, confusion = run_stage_classification(
        features,
        config,
        output_dir,
    )
    epoch_features = pd.read_parquet(
        output_dir / "stage_epoch_features.parquet"
    )
    run_stage_physiology(
        epoch_features,
        output_dir,
        random_seed=int(config["project"]["random_seed"]),
    )
    return summary, confusion


def run_continuous_prediction_analysis(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate future-N2 prediction on streams anchored at record start."""
    features = load_continuous_features(config)
    output_dir = Path(config["data"]["results_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    features.to_parquet(
        output_dir / "continuous_cohort_features.parquet",
        index=False,
    )
    return run_continuous_prediction(features, config, output_dir)
