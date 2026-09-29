"""Raw-waveform ANPHY training for separate cap8 and cap16 W/N1/N2 models.

No PSD, band-power features, or heuristic stage labels. Original data is read-only.
Run --help for preparation, smoke-test and training options.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np

CAP8 = ("Fp1", "Fp2", "C3", "C4", "P7", "P8", "O1", "O2")
CAP16 = CAP8 + ("F7", "F8", "F3", "F4", "T7", "T8", "P3", "P4")
STAGES = ("W", "N1", "N2")
ALIASES = {"T3": "T7", "T4": "T8", "T5": "P7", "T6": "P8"}
RATE = 250
WINDOW_SECONDS = 30
CONTEXT_SECONDS = 10
PIPELINE = {
    "version": "cap-waveform-v1", "channels": list(CAP16), "classes": list(STAGES),
    "sample_rate_hz": RATE, "window_seconds": WINDOW_SECONDS,
    "past_context_seconds": CONTEXT_SECONDS,
    "resampling": "scipy.resample_poly, default Kaiser window; context+epoch buffer only",
    "filter": "causal scipy SOS: iirnotch(50Hz,Q30), butter(4,[0.5,35]Hz)",
    "filter_initialization": "zero-state per 40-second context+epoch buffer; discard first 10 seconds",
    "reference": "selected montage average after temporal filtering",
    "input_unit": "uV", "input_scale_uv": 100.0,
    "normalization": "divide referenced uV by 100; no subject/night fitted statistics",
    "qc": {"maximum_filtered_ptp_uv": 500.0, "minimum_filtered_std_uv": 0.1,
           "flat_second_std_uv": 0.1, "max_flat_seconds": 2,
           "require_all_16_clean": True},
    "scope": "Only manually labelled W/N1/N2. N3/R/L excluded, never relabelled.",
    "deployment": "research_only; real-device reference and domain validation pending",
}


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def canonical(label: str) -> str:
    name = re.sub(r"^(?:EEG|POLY)\s*", "", label.strip(), flags=re.I)
    name = re.sub(r"[-_\s]*(?:REF|AVG|LE|A1|A2|M1|M2)$", "", name, flags=re.I)
    name = name.rstrip("-_ ").upper()
    return ALIASES.get(name, name)


def read_labels(path: Path) -> list[tuple[str, float, float]]:
    """ANPHY TXT: stage, absolute start seconds, duration seconds; retain offsets."""
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        fields = line.strip().split()
        if not fields:
            continue
        stage = fields[0].upper()
        stage = "R" if stage == "REM" else stage
        if stage not in (*STAGES, "N3", "R", "L"):
            raise ValueError(f"{path}:{line_number}: unsupported label row {line!r}")
        if len(fields) != 3:
            raise ValueError(f"{path}:{line_number}: expected stage/start/duration")
        start, duration = map(float, fields[1:])
        if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration != 30:
            raise ValueError(f"{path}:{line_number}: expected non-negative start and 30s duration")
        if rows and start < rows[-1][1] + rows[-1][2] - 1e-6:
            raise ValueError(f"{path}:{line_number}: overlapping/out-of-order labels")
        rows.append((stage, start, duration))
    if not rows:
        raise ValueError(f"No labels in {path}")
    return rows


def find_files(root: Path) -> list[tuple[str, Path, Path]]:
    """Training expects extracted EDF; reject ambiguous records, never extract ZIPs."""
    found = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".edf":
            continue
        match = re.search(r"EPCTL\d+", str(path.relative_to(root)), re.I)
        if not match:
            continue
        sid = match.group().upper()
        if sid in found:
            raise ValueError(f"Duplicate extracted recording for {sid}: {found[sid][0]} and {path}")
        candidates = [p for p in path.parent.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
        if len(candidates) != 1:
            raise ValueError(f"{sid}: expected exactly one annotation TXT beside EDF; found {candidates}")
        found[sid] = (path, candidates[0])
    if not found:
        raise FileNotFoundError(f"No extracted EPCTL EDF found under {root}")
    return [(sid, *paths) for sid, paths in sorted(found.items())]


def header_info(path: Path) -> dict:
    with path.open("rb") as stream:
        header = stream.read(256)
        if len(header) != 256 or header[:8] != b"0       ":
            raise ValueError("invalid EDF header")
        count = int(header[252:256])
        if count <= 0 or count > 4096:
            raise ValueError("invalid EDF channel count")
        reserved = header[192:236].decode("ascii").strip()
        if "EDF+D" in reserved:
            raise ValueError("Discontinuous EDF+D requires explicit TAL time alignment; unsupported in v1")
        remaining = stream.read(256 * count)
    if len(remaining) != 256 * count:
        raise ValueError("truncated EDF signal header")
    offset = 0
    fields = {}
    for name, width in (("labels", 16), ("transducer", 80), ("units", 8),
                        ("physical_min", 8), ("physical_max", 8), ("digital_min", 8),
                        ("digital_max", 8), ("prefilter", 80), ("samples_per_record", 8), ("reserved", 32)):
        fields[name] = [remaining[offset + i * width:offset + (i + 1) * width].decode("latin-1").strip() for i in range(count)]
        offset += count * width
    fields["edf_type"] = reserved
    fields["record_seconds"] = float(header[244:252])
    return fields


def channel_selection(info: dict) -> list[str]:
    selected = []
    for target in CAP16:
        matches = [i for i, label in enumerate(info["labels"]) if canonical(label) == target.upper()]
        if len(matches) != 1:
            raise ValueError(f"{target}: expected exactly one source, found {matches}")
        index = matches[0]
        if info["units"][index].lower() not in ("uv", "µv", "μv"):
            raise ValueError(f"{target}: expected microvolt EDF calibration, found {info['units'][index]!r}")
        selected.append(info["labels"][index])
    return selected


def preprocess_window(context_and_epoch_uv: np.ndarray, input_rate: int) -> tuple[np.ndarray, str | None]:
    """Finite 40s input -> clean 30s unreferenced waveform at 250Hz.

    The exact same function can be used on a 40s live buffer; future windows are
    never used. Average reference is deliberately deferred until montage selection.
    """
    from scipy.signal import butter, iirnotch, resample_poly, sosfilt, tf2sos
    x = np.asarray(context_and_epoch_uv, dtype=np.float64)
    expected = (16, input_rate * (CONTEXT_SECONDS + WINDOW_SECONDS))
    if x.shape != expected:
        raise ValueError(f"expected {expected}, got {x.shape}")
    if not np.isfinite(x).all():
        return np.empty((0,)), "nonfinite"
    raw_epoch = x[:, -WINDOW_SECONDS * input_rate:]
    one_second = raw_epoch.reshape(16, WINDOW_SECONDS, input_rate)
    if np.any((one_second.std(axis=-1) < 0.1).sum(axis=1) > 2):
        return np.empty((0,)), "flat_signal"
    factor = math.gcd(input_rate, RATE)
    if input_rate != RATE:
        x = resample_poly(x, RATE // factor, input_rate // factor, axis=-1)
    b, a = iirnotch(50, 30, fs=RATE)
    sos = np.concatenate((tf2sos(b, a), butter(4, [0.5, 35], btype="bandpass", fs=RATE, output="sos")))
    x = sosfilt(sos, x, axis=-1)[:, -WINDOW_SECONDS * RATE:]
    if np.any(np.ptp(x, axis=1) > 500):
        return np.empty((0,)), "high_amplitude"
    if np.any(np.std(x, axis=1) < 0.1):
        return np.empty((0,)), "low_variation"
    return x.astype(np.float32), None


def prepare_subject(sid: str, edf: Path, txt: Path, cache: Path, max_epochs: int | None = None) -> dict:
    import mne
    cache.mkdir(parents=True, exist_ok=True)
    payload = {"edf": str(edf.resolve()), "size": edf.stat().st_size, "mtime_ns": edf.stat().st_mtime_ns,
               "annotation_sha256": hashlib.sha256(txt.read_bytes()).hexdigest(), "pipeline": PIPELINE,
               "max_epochs": max_epochs}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    metadata_path = cache / f"{sid}.json"
    array_path = cache / f"{sid}.npy"
    if metadata_path.exists() and array_path.exists():
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        if meta.get("fingerprint") == fingerprint:
            data = np.load(array_path, mmap_mode="r")
            if list(data.shape) == meta["array_shape"] and data.dtype == np.float32:
                log(f"{sid}: reuse cache ({len(meta['labels'])} clean epochs)")
                return meta
        raise ValueError(f"{sid}: stale/mismatched cache; use a new --output directory")
    info = header_info(edf)
    selected = channel_selection(info)
    rows = read_labels(txt)
    label_counts = {stage: sum(r[0] == stage for r in rows) for stage in (*STAGES, "N3", "R", "L")}
    raw = mne.io.read_raw_edf(edf, include=selected, preload=False, infer_types=False, verbose="ERROR")
    try:
        raw.reorder_channels(selected)
        input_rate = int(round(raw.info["sfreq"]))
        if not np.isclose(input_rate, raw.info["sfreq"]):
            raise ValueError("non-integer source sampling frequency")
        source_rates = [float(info["samples_per_record"][info["labels"].index(name)]) / info["record_seconds"] for name in selected]
        if any(not np.isclose(rate, input_rate) for rate in source_rates):
            raise ValueError("mixed source sampling rates not supported")
        duration = raw.n_times / input_rate
        rejected = {"no_past_context": 0, "beyond_recording": 0, "flat_signal": 0,
                    "nonfinite": 0, "high_amplitude": 0, "low_variation": 0}
        candidates = []
        for stage, start, _ in rows:
            if stage not in STAGES:
                continue
            if start < CONTEXT_SECONDS:
                rejected["no_past_context"] += 1
            elif start + WINDOW_SECONDS > duration + 1e-9:
                rejected["beyond_recording"] += 1
            else:
                candidates.append((stage, start))
        if max_epochs:
            candidates = candidates[:max_epochs]
        if not candidates:
            raise ValueError(f"{sid}: no eligible 30-second epochs")
        shape = (len(candidates), 16, WINDOW_SECONDS * RATE)
        array = np.lib.format.open_memmap(array_path, mode="w+", dtype=np.float32, shape=shape)
        labels, starts = [], []
        for number, (stage, start) in enumerate(candidates, 1):
            first = int(round((start - CONTEXT_SECONDS) * input_rate))
            last = first + (CONTEXT_SECONDS + WINDOW_SECONDS) * input_rate
            window = raw.get_data(start=first, stop=last) * 1e6
            processed, reason = preprocess_window(window, input_rate)
            if reason:
                rejected[reason] += 1
            else:
                array[len(labels)] = processed
                labels.append(STAGES.index(stage))
                starts.append(start)
            if number % 200 == 0:
                log(f"{sid}: checked {number}/{len(candidates)}, kept {len(labels)}")
        array.flush()
        del array
        if not labels:
            raise ValueError(f"{sid}: no clean epochs; rejections={rejected}")
        meta = {"subject_id": sid, "fingerprint": fingerprint, "source": payload,
                "source_labels": selected, "source_rate_hz": input_rate, "edf_type": info["edf_type"],
                "source_prefilter": {name: info["prefilter"][info["labels"].index(name)] for name in selected},
                "annotation_counts": label_counts, "duration_seconds": duration,
                "array_shape": list(shape), "labels": labels, "starts_seconds": starts,
                "counts": np.bincount(labels, minlength=3).tolist(), "rejected": rejected}
        write_json(metadata_path, meta)
        log(f"{sid}: complete; W/N1/N2={meta['counts']}; rejected={rejected}")
        return meta
    finally:
        raw.close()


def split_subjects(subjects: list[str], seed: int) -> dict[str, list[str]]:
    if len(subjects) != len(set(subjects)) or len(subjects) < 9:
        raise ValueError("Need at least nine unique subjects for independent train/validation/test")
    ids = sorted(subjects)
    random.Random(seed).shuffle(ids)
    holdout = max(2, round(len(ids) * 0.2))
    return {"test": sorted(ids[:holdout]), "validation": sorted(ids[holdout:2 * holdout]), "train": sorted(ids[2 * holdout:])}


def model_input(x: np.ndarray, channels: int) -> np.ndarray:
    if channels not in (8, 16):
        raise ValueError("channels must be 8 or 16")
    selected = np.array(x[:channels], dtype=np.float32, copy=True)
    selected -= selected.mean(axis=0, keepdims=True)
    selected /= 100.0
    return selected


class EpochDataset:
    """Small index plus read-only memory maps; never concatenate entire cohort."""
    def __init__(self, cache: Path, subjects: list[str], channels: int):
        self.channels = channels
        self.maps = {}
        self.index = []
        for sid in subjects:
            meta = json.loads((cache / f"{sid}.json").read_text(encoding="utf-8"))
            if meta["source"]["max_epochs"] is not None:
                raise ValueError("Smoke-test cache cannot be used for cohort training")
            self.maps[sid] = np.load(cache / f"{sid}.npy", mmap_mode="r")
            data = self.maps[sid]
            if (list(data.shape) != meta["array_shape"] or data.shape[1:] != (16, RATE * WINDOW_SECONDS)
                    or data.dtype != np.float32 or len(meta["labels"]) > data.shape[0]
                    or len(meta["labels"]) != len(meta["starts_seconds"])):
                raise ValueError(f"{sid}: invalid cache shape or epoch index")
            self.index.extend((sid, i, y, meta["starts_seconds"][i]) for i, y in enumerate(meta["labels"]))
        self.labels = np.asarray([r[2] for r in self.index], dtype=np.int64)
        if not self.index or np.any(np.bincount(self.labels, minlength=3) == 0):
            raise ValueError(f"split {subjects} lacks at least one class")

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        sid, epoch, label, _ = self.index[index]
        return model_input(self.maps[sid][epoch], self.channels), label


def build_model(torch, channels: int):
    nn = torch.nn
    return nn.Sequential(
        nn.Conv1d(channels, 32, 25, stride=5, padding=12), nn.BatchNorm1d(32), nn.GELU(),
        nn.Conv1d(32, 48, 9, stride=3, padding=4), nn.BatchNorm1d(48), nn.GELU(), nn.Dropout(0.15),
        nn.Conv1d(48, 64, 7, stride=2, padding=3), nn.BatchNorm1d(64), nn.GELU(),
        nn.AdaptiveAvgPool1d(8), nn.Flatten(), nn.Linear(512, 64), nn.GELU(), nn.Dropout(0.3), nn.Linear(64, 3),
    )


def metrics(truth: np.ndarray, probabilities: np.ndarray) -> dict:
    predictions = probabilities.argmax(axis=1)
    cm = np.zeros((3, 3), dtype=np.int64)
    np.add.at(cm, (truth, predictions), 1)
    support, predicted = cm.sum(axis=1), cm.sum(axis=0)
    tp = np.diag(cm)
    recall = np.divide(tp, support, out=np.zeros(3, dtype=float), where=support > 0)
    precision = np.divide(tp, predicted, out=np.zeros(3, dtype=float), where=predicted > 0)
    f1 = np.divide(2 * tp, support + predicted, out=np.zeros(3, dtype=float), where=support + predicted > 0)
    accuracy = float(tp.sum() / len(truth))
    expected = float(np.dot(support / len(truth), predicted / len(truth)))
    confidences = probabilities.max(axis=1)
    ece = 0.0
    bin_ids = np.minimum((confidences * 10).astype(int), 9)
    for bin_id in range(10):
        mask = bin_ids == bin_id
        if mask.any():
            ece += float(mask.mean() * abs((predictions[mask] == truth[mask]).mean() - confidences[mask].mean()))
    return {"accuracy": accuracy, "balanced_accuracy": float(recall[support > 0].mean()),
            "macro_f1": float(f1.mean()), "cohen_kappa": (accuracy - expected) / (1 - expected) if expected < 1 else None,
            "confusion_matrix": cm.tolist(), "classes": list(STAGES), "n_epochs": len(truth),
            "recall": dict(zip(STAGES, recall.tolist())), "precision": dict(zip(STAGES, precision.tolist())),
            "f1": dict(zip(STAGES, f1.tolist())), "support": dict(zip(STAGES, support.tolist())),
            "brier_score": float(np.mean(np.sum((probabilities - np.eye(3)[truth]) ** 2, axis=1))),
            "ece_10_bins": ece, "probabilities_calibrated": False}


def evaluate(torch, model, loader, device):
    model.eval()
    predictions, truth = [], []
    with torch.inference_mode():
        for x, y in loader:
            probabilities = torch.softmax(model(x.to(device)), dim=1)
            predictions.append(probabilities.cpu().numpy())
            truth.append(y.numpy())
    return np.concatenate(truth), np.concatenate(predictions)


def train_one(args, count: int, split: dict, fingerprint: str) -> dict:
    import torch
    import platform
    from importlib.metadata import version
    from torch.utils.data import DataLoader
    environment = {"python": platform.python_version(), **{name: version(name) for name in ("torch", "numpy", "scipy", "mne")}}
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(4)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    device = "cuda" if torch.cuda.is_available() else "cpu"
    directory = args.output / f"cap{count}"
    directory.mkdir(parents=True, exist_ok=True)
    settings = {"seed": args.seed, "epochs": args.epochs, "batch_size": args.batch_size,
                "patience": args.patience, "channels": count, "dataset_fingerprint": fingerprint}
    report_path = directory / "report.json"
    if report_path.exists():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        if old["settings"] != settings or not (directory / "best.pt").is_file():
            raise ValueError("Completed training uses other settings or weights are missing; choose a new output directory")
        log(f"cap{count}: already completed; preserving held-out test report")
        return old
    datasets = {key: EpochDataset(args.output / "cache", ids, count) for key, ids in split.items()}
    loaders = {key: DataLoader(dataset, batch_size=args.batch_size, shuffle=key == "train",
                               num_workers=0, pin_memory=device == "cuda") for key, dataset in datasets.items()}
    counts = np.bincount(datasets["train"].labels, minlength=3)
    weights = counts.sum() / (3 * counts)
    model = build_model(torch, count).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-3)
    loss_fn = torch.nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32, device=device))
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=2)
    best_score, best_epoch = -1.0, 0
    history = []
    log(f"cap{count}: device={device}; split epochs=" + str({k: len(d) for k, d in datasets.items()}))
    started = time.monotonic()
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for x, y in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(x.to(device)), y.to(device))
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        truth, probs = evaluate(torch, model, loaders["validation"], device)
        result = metrics(truth, probs)
        score = result["macro_f1"]
        scheduler.step(score)
        row = {"epoch": epoch, "loss": float(np.mean(losses)), "validation": result}
        history.append(row)
        write_json(directory / "history.json", history)
        if score > best_score:
            best_score, best_epoch = score, epoch
            checkpoint = {"state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                          "architecture": "build_model:cap-waveform-v1", "channels": list(CAP16[:count]),
                          "classes": list(STAGES), "pipeline": PIPELINE, "split": split,
                          "epoch": epoch, "settings": settings, "deployment_ready": False}
            temporary = directory / "best.pt.tmp"
            torch.save(checkpoint, temporary)
            temporary.replace(directory / "best.pt")
        log(f"cap{count}: epoch {epoch}/{args.epochs}, loss={row['loss']:.4f}, val macro-F1={score:.4f}, val recalls={result['recall']}")
        if epoch - best_epoch >= args.patience:
            log(f"cap{count}: early stop; best epoch={best_epoch}")
            break
    checkpoint = torch.load(directory / "best.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    # Held-out test set is evaluated only after validation-based model selection.
    truth, probs = evaluate(torch, model, loaders["test"], device)
    report = {"settings": settings, "device": device, "best_epoch": best_epoch,
              "best_validation_macro_f1": best_score, "training_seconds": time.monotonic() - started,
              "channels": list(CAP16[:count]), "pipeline": PIPELINE, "subject_split": split, "environment": environment,
              "training_class_counts": counts.tolist(), "test": metrics(truth, probs), "per_subject": {}}
    test_ids = np.asarray([row[0] for row in datasets["test"].index])
    for sid in split["test"]:
        mask = test_ids == sid
        report["per_subject"][sid] = metrics(truth[mask], probs[mask])
    with (directory / "test_predictions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["subject", "epoch_start_seconds", "truth", "prediction", "p_W", "p_N1", "p_N2"])
        for (sid, _, label, start), probability in zip(datasets["test"].index, probs, strict=True):
            writer.writerow([sid, start, STAGES[label], STAGES[int(probability.argmax())], *probability.tolist()])
    write_json(report_path, report)
    write_json(directory / "input_contract.json", {"channels": list(CAP16[:count]), "pipeline": PIPELINE,
                                                    "deployment_ready": False, "hardware_reference_verified": False})
    log(f"cap{count}: finished; test metrics={report['test']}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--patience", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--train-only", action="store_true")
    parser.add_argument("--subject", help="Preparation-only smoke test, e.g. EPCTL01")
    parser.add_argument("--max-epochs", type=int, help="Preparation-only smoke test; separate output directory required")
    args = parser.parse_args()
    if min(args.epochs, args.batch_size, args.patience) <= 0:
        parser.error("epochs, batch size and patience must be positive")
    if args.prepare_only and args.train_only:
        parser.error("prepare-only and train-only are mutually exclusive")
    if (args.subject or args.max_epochs is not None) and not args.prepare_only:
        parser.error("subject/max-epochs are restricted to prepare-only")
    if args.max_epochs is not None and args.max_epochs <= 0:
        parser.error("max-epochs must be positive")
    files = find_files(args.dataset)
    split = split_subjects([sid for sid, _, _ in files], args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    split_path = args.output / "split.json"
    if split_path.exists() and json.loads(split_path.read_text(encoding="utf-8")) != split:
        raise ValueError("Existing subject split differs; choose another output directory")
    write_json(split_path, split)
    if args.subject:
        files = [row for row in files if row[0] == args.subject.upper()]
        if not files:
            raise ValueError(f"Unknown subject {args.subject}")
    metadata = []
    for sid, edf, txt in files:
        if args.train_only:
            meta = json.loads((args.output / "cache" / f"{sid}.json").read_text(encoding="utf-8"))
            if meta["source"]["pipeline"] != PIPELINE:
                raise ValueError("Cache preprocessing version does not match")
            source = meta["source"]
            if (source["edf"] != str(edf.resolve()) or source["size"] != edf.stat().st_size
                    or source["mtime_ns"] != edf.stat().st_mtime_ns
                    or source["annotation_sha256"] != hashlib.sha256(txt.read_bytes()).hexdigest()):
                raise ValueError(f"{sid}: source changed since preprocessing; use a fresh output directory")
        else:
            meta = prepare_subject(sid, edf, txt, args.output / "cache", args.max_epochs)
        metadata.append(meta)
    manifest = {"pipeline": PIPELINE, "split": split, "subjects": [{k: v for k, v in m.items() if k not in ("labels", "starts_seconds")} for m in metadata]}
    write_json(args.output / "manifest.json", manifest)
    if args.prepare_only:
        log(f"Preparation finished for {len(metadata)} subjects; no models trained")
        return 0
    fingerprint = hashlib.sha256(json.dumps([m["fingerprint"] for m in metadata]).encode()).hexdigest()
    reports = {f"cap{count}": train_one(args, count, split, fingerprint) for count in (8, 16)}
    write_json(args.output / "comparison.json", {key: {"best_epoch": value["best_epoch"], "test": value["test"],
               "channels": value["channels"]} for key, value in reports.items()})
    log("Both cap8 and cap16 models finished. Research results only; live system unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
