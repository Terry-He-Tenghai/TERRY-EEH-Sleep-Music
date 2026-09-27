from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mne
import numpy as np
import pandas as pd

from .io import (
    find_stable_n2_onset,
    find_subject_files,
    normalize_channel_name,
    read_artifact_matrix,
    read_sleep_annotations,
    select_target_channels,
)


@dataclass
class SubjectSegment:
    subject_id: str
    raw: mne.io.BaseRaw
    auxiliary_raw: mne.io.BaseRaw | None
    annotations: pd.DataFrame
    stable_n2_onset_s: float
    segment_start_s: float
    segment_end_s: float
    channel_mapping: dict[str, str]
    artifact_matrix: np.ndarray | None
    artifact_channel_indices: list[int] | None


def _find_reference_artifact(reference_dir: str | Path, subject_id: str) -> Path | None:
    subject_id = subject_id.lower()
    for path in Path(reference_dir).rglob("*.mat"):
        if subject_id in path.name.lower():
            return path
    return None


def _artifact_channel_indices(
    original_names: list[str],
    channel_mapping: dict[str, str],
) -> list[int] | None:
    normalized = [normalize_channel_name(name).upper() for name in original_names]
    indices: list[int] = []
    for source in channel_mapping.values():
        source_name = normalize_channel_name(source).upper()
        if source_name not in normalized:
            return None
        indices.append(normalized.index(source_name))
    return indices


def _reference_eeg_names(reference_dir: str | Path) -> list[str] | None:
    """Read the canonical 83-channel ordering used by artifact matrices."""
    position_files = sorted(Path(reference_dir).glob("*.pos"))
    if not position_files:
        return None
    names = []
    for line in position_files[0].read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1])
    return names or None


def prepare_subject_segment(
    subject_dir: str | Path,
    config: dict[str, Any],
    segment_mode: str = "transition",
) -> SubjectSegment:
    """Load, crop, downsample, reference, and causally filter one subject."""
    if segment_mode not in {"transition", "record_start"}:
        raise ValueError(
            "segment_mode must be 'transition' or 'record_start'"
        )
    subject_dir = Path(subject_dir)
    subject_id_match = next(
        (
            part.upper()
            for part in subject_dir.parts
            if part.upper().startswith("EPCTL")
        ),
        subject_dir.name.upper(),
    )
    subject_id = subject_id_match.split("-")[0]
    files = find_subject_files(subject_dir)
    annotations = read_sleep_annotations(files["annotation"])
    stable_n2_onset_s = find_stable_n2_onset(
        annotations,
        float(config["epoching"]["stable_n2_seconds"]),
    )

    target_channels = list(config["channels"]["target"])
    aliases = dict(config["channels"].get("aliases", {}))
    requested_eeg_names = target_channels + list(aliases.values())
    include_pattern = (
        r"(?i)^(?:"
        + "(?:"
        + "|".join(re.escape(name) for name in requested_eeg_names)
        + r")(?:-REF|-)?"
        + r"|.*EOG.*|.*EMG.*)$"
    )
    raw_all = mne.io.read_raw_edf(
        files["edf"],
        preload=False,
        infer_types=False,
        include=include_pattern,
        verbose="ERROR",
    )
    original_names = list(raw_all.ch_names)
    auxiliary_names = [
        name
        for name in original_names
        if "EOG" in name.upper() or "EMG" in name.upper()
    ]
    auxiliary_microvolt_names = [
        name
        for name in auxiliary_names
        if str(raw_all._orig_units.get(name, "")).lower() in {"n/a", "na", ""}
    ]
    auxiliary_raw = (
        raw_all.copy().pick(auxiliary_names)
        if auxiliary_names
        else None
    )
    if auxiliary_raw is not None:
        auxiliary_raw.set_channel_types(
            {
                name: ("eog" if "EOG" in name.upper() else "emg")
                for name in auxiliary_raw.ch_names
            },
            verbose="ERROR",
        )
    raw, mapping = select_target_channels(
        raw_all,
        target_channels,
        aliases,
    )

    requested_start = (
        0.0
        if segment_mode == "record_start"
        else stable_n2_onset_s
        - 60 * float(config["epoching"]["pre_n2_minutes"])
    )
    requested_end = stable_n2_onset_s + 60 * float(config["epoching"]["post_n2_minutes"])
    segment_start = max(0.0, requested_start)
    segment_end = min(float(raw.times[-1]), requested_end)
    raw.crop(tmin=segment_start, tmax=segment_end, include_tmax=False).load_data()
    if auxiliary_raw is not None:
        auxiliary_raw.crop(
            tmin=segment_start,
            tmax=segment_end,
            include_tmax=False,
        ).load_data()
        if auxiliary_microvolt_names:
            auxiliary_raw.apply_function(
                lambda values: values * 1e-6,
                picks=auxiliary_microvolt_names,
                channel_wise=True,
            )

    reference = str(config["signal"].get("reference", "average"))
    if reference == "average":
        raw.set_eeg_reference("average", projection=False, verbose="ERROR")
    else:
        requested_refs = [name.strip() for name in reference.split(",") if name.strip()]
        available_refs = [name for name in requested_refs if name in raw.ch_names]
        if not available_refs:
            raise ValueError(
                f"Configured reference channels {requested_refs} are unavailable"
            )
        raw.set_eeg_reference(available_refs, projection=False, verbose="ERROR")

    target_sfreq = float(config["signal"]["target_sfreq_hz"])
    if not np.isclose(raw.info["sfreq"], target_sfreq):
        raw.resample(target_sfreq, npad="auto", verbose="ERROR")
    if (
        auxiliary_raw is not None
        and not np.isclose(auxiliary_raw.info["sfreq"], target_sfreq)
    ):
        auxiliary_raw.resample(target_sfreq, npad="auto", verbose="ERROR")

    notch_frequency = float(config["signal"].get("notch_frequency_hz", 0.0))
    if notch_frequency > 0.0:
        raw.notch_filter(
            freqs=[notch_frequency],
            method="iir",
            phase="forward",
            iir_params={"order": 2, "ftype": "butter"},
            verbose="ERROR",
        )
        if auxiliary_raw is not None:
            auxiliary_raw.notch_filter(
                freqs=[notch_frequency],
                method="iir",
                phase="forward",
                iir_params={"order": 2, "ftype": "butter"},
                picks="all",
                verbose="ERROR",
            )

    raw.filter(
        l_freq=float(config["signal"]["highpass_hz"]),
        h_freq=float(config["signal"]["lowpass_hz"]),
        method="iir",
        phase="forward",
        iir_params={"order": 4, "ftype": "butter", "output": "sos"},
        verbose="ERROR",
    )
    if auxiliary_raw is not None:
        auxiliary_raw.filter(
            l_freq=float(config["signal"]["highpass_hz"]),
            h_freq=float(config["signal"]["lowpass_hz"]),
            picks="all",
            method="iir",
            phase="forward",
            iir_params={"order": 4, "ftype": "butter", "output": "sos"},
            verbose="ERROR",
        )

    artifact_path = files["artifact"] or _find_reference_artifact(
        config["data"]["reference_dir"],
        subject_id,
    )
    artifact_matrix = None
    artifact_indices = None
    if artifact_path is not None:
        artifact_matrix = read_artifact_matrix(artifact_path)
        artifact_names = _reference_eeg_names(
            config["data"]["reference_dir"]
        )
        artifact_indices = _artifact_channel_indices(
            artifact_names or original_names,
            mapping,
        )
        if (
            artifact_indices is not None
            and max(artifact_indices, default=-1) >= artifact_matrix.shape[0]
        ):
            artifact_indices = None

    return SubjectSegment(
        subject_id=subject_id,
        raw=raw,
        auxiliary_raw=auxiliary_raw,
        annotations=annotations,
        stable_n2_onset_s=stable_n2_onset_s,
        segment_start_s=segment_start,
        segment_end_s=segment_end,
        channel_mapping=mapping,
        artifact_matrix=artifact_matrix,
        artifact_channel_indices=artifact_indices,
    )
