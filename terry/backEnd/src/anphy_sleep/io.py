from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

import mne
import numpy as np
import pandas as pd
from scipy.io import loadmat


STAGE_ALIASES = {
    "W": "W",
    "WK": "W",
    "WAKE": "W",
    "N1": "N1",
    "S1": "N1",
    "NREM1": "N1",
    "N2": "N2",
    "S2": "N2",
    "NREM2": "N2",
    "N3": "N3",
    "S3": "N3",
    "S4": "N3",
    "NREM3": "N3",
    "R": "R",
    "REM": "R",
    "L": "L",
    "LIGHT": "L",
    "LIGHTS": "L",
}


def extract_subject_archive(archive: str | Path, destination: str | Path) -> Path:
    """Extract a subject ZIP and return the most likely subject directory."""
    archive = Path(archive)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)

    subject_id = archive.stem.split("-")[0].upper()
    candidates = [
        path
        for path in destination.rglob("*")
        if path.is_dir() and path.name.upper().startswith(subject_id)
    ]
    return min(candidates, key=lambda path: len(path.parts)) if candidates else destination


def discover_subject_dirs(raw_dir: str | Path) -> list[Path]:
    """Find extracted subject folders containing an EDF recording."""
    raw_dir = Path(raw_dir)
    subject_dirs = {
        edf.parent
        for edf in raw_dir.rglob("*")
        if edf.is_file()
        and edf.suffix.lower() == ".edf"
        and re.search(r"EPCTL\d+", str(edf), flags=re.IGNORECASE)
    }
    return sorted(subject_dirs, key=lambda path: path.name.upper())


def find_subject_files(subject_dir: str | Path) -> dict[str, Path | None]:
    """Locate the EDF, sleep-stage text, and optional artifact matrix."""
    subject_dir = Path(subject_dir)
    all_files = [path for path in subject_dir.rglob("*") if path.is_file()]
    edf_files = sorted(path for path in all_files if path.suffix.lower() == ".edf")
    if not edf_files:
        raise FileNotFoundError(f"No EDF recording found under {subject_dir}")

    text_files = sorted(path for path in all_files if path.suffix.lower() == ".txt")
    annotation = next(
        (path for path in text_files if _text_contains_stages(path)),
        None,
    )
    if annotation is None:
        raise FileNotFoundError(f"No sleep-stage annotation found under {subject_dir}")

    mat_files = sorted(path for path in all_files if path.suffix.lower() == ".mat")
    artifact = next(
        (path for path in mat_files if "art" in path.name.lower()),
        None,
    )
    return {"edf": edf_files[0], "annotation": annotation, "artifact": artifact}


def _text_contains_stages(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:20_000].upper()
    except OSError:
        return False
    return bool(re.search(r"(^|[\s,;\t])(N1|N2|N3|REM|WAKE|W)([\s,;\t]|$)", text))


def _parse_time_value(value: str) -> float | None:
    value = value.strip().strip("\"'")
    try:
        return float(value)
    except ValueError:
        pass

    match = re.fullmatch(
        r"(?:(\d+)\s+days?\s+)?(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    days = float(match.group(1) or 0)
    hours = float(match.group(2))
    minutes = float(match.group(3))
    seconds = float(match.group(4))
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


def read_sleep_annotations(path: str | Path) -> pd.DataFrame:
    """Parse ANPHY stage annotations into start/duration intervals."""
    rows: list[tuple[str, float, float | None]] = []
    path = Path(path)
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw_tokens = [token.strip() for token in re.split(r"[,;\t]+", line) if token.strip()]
        if len(raw_tokens) == 1:
            raw_tokens = [token for token in re.split(r"\s+", line.strip()) if token]

        stage_index = None
        stage = None
        for index, token in enumerate(raw_tokens):
            normalized = re.sub(r"[^A-Z0-9]", "", token.upper())
            if normalized in STAGE_ALIASES:
                stage_index = index
                stage = STAGE_ALIASES[normalized]
                break
        if stage is None:
            continue

        values = [
            parsed
            for index, token in enumerate(raw_tokens)
            if index != stage_index and (parsed := _parse_time_value(token)) is not None
        ]
        if not values:
            continue
        rows.append((stage, values[0], values[1] if len(values) > 1 else None))

    if not rows:
        raise ValueError(f"Could not parse any stage rows from {path}")

    annotations = pd.DataFrame(rows, columns=["stage", "start_s", "duration_s"])
    starts = annotations["start_s"].to_numpy(dtype=float)
    for index in range(1, len(starts)):
        while starts[index] < starts[index - 1]:
            starts[index] += 86_400
    if starts[0] > 3_600:
        starts -= starts[0]
    annotations["start_s"] = starts

    inferred = annotations["start_s"].shift(-1) - annotations["start_s"]
    annotations["duration_s"] = annotations["duration_s"].fillna(inferred).fillna(30.0)
    annotations = annotations[annotations["duration_s"].between(0.1, 3_600)].copy()
    annotations["end_s"] = annotations["start_s"] + annotations["duration_s"]
    return annotations.sort_values("start_s").reset_index(drop=True)


def find_stable_n2_onset(annotations: pd.DataFrame, minimum_seconds: float = 60.0) -> float:
    """Return the first N2 run lasting at least ``minimum_seconds``."""
    accumulated = 0.0
    run_start = None
    previous_end = None
    for row in annotations[annotations["stage"] != "L"].itertuples(index=False):
        if row.stage == "N2" and (
            previous_end is None or abs(float(row.start_s) - previous_end) <= 1.0
        ):
            run_start = float(row.start_s) if run_start is None else run_start
            accumulated += float(row.duration_s)
        elif row.stage == "N2":
            run_start = float(row.start_s)
            accumulated = float(row.duration_s)
        else:
            run_start = None
            accumulated = 0.0

        previous_end = float(row.end_s)
        if accumulated >= minimum_seconds and run_start is not None:
            return run_start
    raise ValueError("No continuous N2 run satisfies the requested duration")


def stage_at(annotations: pd.DataFrame, timestamp_s: float) -> str:
    """Get the sleep or light-state annotation covering one timestamp."""
    rows = annotations[
        (annotations["start_s"] <= timestamp_s)
        & (annotations["end_s"] > timestamp_s)
    ]
    return str(rows.iloc[-1]["stage"]) if not rows.empty else "UNKNOWN"


def normalize_channel_name(name: str) -> str:
    """Normalize common EDF channel labels without changing electrode identity."""
    normalized = name.strip()
    normalized = re.sub(r"^(EEG|POLY)\s*", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"[-_\s]*(REF|AVG|LE|A1|A2|M1|M2)$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"[-_\s]+$", "", normalized)
    return normalized.strip()


def select_target_channels(
    raw: mne.io.BaseRaw,
    target_channels: list[str],
    aliases: dict[str, str],
) -> tuple[mne.io.BaseRaw, dict[str, str]]:
    """Select and canonically rename the configured 16 EEG channels."""
    normalized_to_original: dict[str, str] = {}
    for original in raw.ch_names:
        normalized_to_original.setdefault(normalize_channel_name(original).upper(), original)

    selected: list[str] = []
    rename: dict[str, str] = {}
    mapping: dict[str, str] = {}
    missing: list[str] = []
    for target in target_channels:
        source = normalized_to_original.get(target.upper())
        if source is None and target in aliases:
            source = normalized_to_original.get(aliases[target].upper())
        if source is None:
            missing.append(target)
            continue
        selected.append(source)
        rename[source] = target
        mapping[target] = source

    if missing:
        raise ValueError(
            f"Missing target channels: {missing}. Available: {raw.ch_names}"
        )
    picked = raw.copy().pick(selected)
    picked.rename_channels(rename)
    picked.set_channel_types({channel: "eeg" for channel in picked.ch_names})
    return picked, mapping


def read_artifact_matrix(path: str | Path) -> np.ndarray:
    """Read the largest numeric 2-D array from an ANPHY artifact MAT file."""
    try:
        payload: dict[str, Any] = loadmat(path)
        arrays = [
            value
            for key, value in payload.items()
            if not key.startswith("__")
            and isinstance(value, np.ndarray)
            and value.ndim == 2
            and np.issubdtype(value.dtype, np.number)
        ]
    except NotImplementedError:
        import h5py

        arrays = []
        with h5py.File(path, "r") as handle:
            def collect(_: str, item: Any) -> None:
                if (
                    isinstance(item, h5py.Dataset)
                    and item.ndim == 2
                    and np.issubdtype(item.dtype, np.number)
                ):
                    arrays.append(np.asarray(item))

            handle.visititems(collect)
    if not arrays:
        raise ValueError(f"No 2-D numeric artifact matrix found in {path}")
    matrix = max(arrays, key=lambda value: value.size)
    if matrix.shape[0] > matrix.shape[1]:
        matrix = matrix.T
    return matrix.astype(bool)
