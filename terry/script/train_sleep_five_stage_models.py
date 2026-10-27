"""Independent W/N1/N2/N3/REM waveform training; legacy artifacts remain read-only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import train_sleep_waveform_models as base
import train_sleep_subset_models as subset
import train_sleep_frontal_models as frontal

VERSION = "cap-waveform-five-stage-v1"
STAGES = ("W", "N1", "N2", "N3", "REM")
SOURCE_TO_STAGE = {"W": "W", "N1": "N1", "N2": "N2", "N3": "N3", "R": "REM", "REM": "REM"}
MONTAGES = {**{f"frontal{c}": names for c, names in frontal.MONTAGES.items()},
            "cap8": base.CAP8, "cap16": base.CAP16}
DEFAULT_MODELS = ("frontal2", "frontal4", "frontal6")
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "results/waveform_five_stage_v1"


def pipeline_for(montage):
    result = frontal.pipeline_for(2)
    names = list(MONTAGES[montage])
    result.update(version=VERSION, channels=names, classes=list(STAGES),
                  scope="Manual W/N1/N2/N3/R labels; R and REM map to REM; L excluded.")
    result["qc"].update(required_clean_channels=names)
    return result


def build_model(torch, montage):
    model = base.build_model(torch, len(MONTAGES[montage]))
    model[-1] = torch.nn.Linear(64, len(STAGES))
    return model


def preprocess_window(samples, rate, montage):
    # Reuse the selected-channel temporal filter without mutating legacy globals.
    count = len(MONTAGES[montage])
    if count in subset.MONTAGES:
        return subset.preprocess_window(samples, rate, count)
    # The original cap filter checks every selected channel, exactly matching cap16.
    if count == 16:
        return base.preprocess_window(samples, rate)
    # cap8 has the same per-channel operations; repeated channels do not affect QC.
    processed, reason = base.preprocess_window(np.concatenate((samples, samples)), rate)
    return (processed[:8] if reason is None else processed), reason


def metrics(truth, probabilities):
    truth, probabilities = np.asarray(truth), np.asarray(probabilities)
    n = len(STAGES)
    if (truth.ndim != 1 or len(truth) == 0 or truth.dtype.kind not in "iu"
            or np.any((truth < 0) | (truth >= n)) or probabilities.shape != (len(truth), n)
            or not np.isfinite(probabilities).all() or np.any(probabilities < 0)
            or not np.allclose(probabilities.sum(axis=1), 1, atol=1e-5)):
        raise ValueError("expected nonempty five-class labels and normalized finite probabilities")
    prediction = probabilities.argmax(axis=1)
    cm = np.zeros((n, n), dtype=np.int64)
    np.add.at(cm, (truth, prediction), 1)
    support, predicted, tp = cm.sum(axis=1), cm.sum(axis=0), np.diag(cm)
    recall = np.divide(tp, support, out=np.zeros(n), where=support > 0)
    precision = np.divide(tp, predicted, out=np.zeros(n), where=predicted > 0)
    f1 = np.divide(2 * tp, support + predicted, out=np.zeros(n), where=support + predicted > 0)
    accuracy = float(tp.sum() / len(truth))
    expected = float(np.dot(support, predicted) / len(truth) ** 2)
    confidence = probabilities.max(axis=1)
    bins = np.minimum((confidence * 10).astype(int), 9)
    ece = sum(float((bins == i).mean() * abs((prediction[bins == i] == truth[bins == i]).mean()
              - confidence[bins == i].mean())) for i in range(10) if np.any(bins == i))
    return {"classes": list(STAGES), "n_epochs": len(truth), "confusion_matrix": cm.tolist(),
            "accuracy": accuracy, "balanced_accuracy": float(recall[support > 0].mean()),
            "macro_f1": float(f1.mean()), "cohen_kappa": (accuracy - expected) / (1 - expected) if expected < 1 else None,
            "recall": dict(zip(STAGES, recall.tolist())), "precision": dict(zip(STAGES, precision.tolist())),
            "f1": dict(zip(STAGES, f1.tolist())), "support": dict(zip(STAGES, support.tolist())),
            "brier_score": float(np.mean(np.sum((probabilities - np.eye(n)[truth]) ** 2, axis=1))),
            "ece_10_bins": ece, "probabilities_calibrated": False}


def validate_split(split, subjects):
    if set(split) != {"train", "validation", "test"} or any(not isinstance(v, list) or not v for v in split.values()):
        raise ValueError("expected nonempty train/validation/test subject lists")
    ids = [sid for part in split.values() for sid in part]
    if len(ids) != len(set(ids)) or set(ids) != set(subjects):
        raise ValueError("subject split overlaps or differs from extracted subjects")


def source_payload(edf, txt, montage, max_epochs):
    return {"edf": str(edf.resolve()), "size": edf.stat().st_size, "mtime_ns": edf.stat().st_mtime_ns,
            "annotation_sha256": hashlib.sha256(txt.read_bytes()).hexdigest(),
            "pipeline": pipeline_for(montage), "max_epochs": max_epochs}


def prepare_subject(sid, edf, txt, cache, montage, max_epochs=None, train_only=False):
    import mne
    payload = source_payload(edf, txt, montage, max_epochs)
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    meta_path, array_path = cache / f"{sid}.json", cache / f"{sid}.npy"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("fingerprint") != fingerprint or not array_path.exists():
            raise ValueError(f"{sid}: incompatible or incomplete cache; choose a new output")
        data = np.load(array_path, mmap_mode="r")
        if list(data.shape) != meta["array_shape"] or data.dtype != np.float32:
            raise ValueError(f"{sid}: corrupt cache")
        return meta
    if train_only:
        raise ValueError(f"{sid}: missing prepared cache")
    cache.mkdir(parents=True, exist_ok=True)
    info = base.header_info(edf)
    selected = []
    for name in MONTAGES[montage]:
        indexes = [i for i, label in enumerate(info["labels"]) if base.canonical(label) == name.upper()]
        if len(indexes) != 1 or info["units"][indexes[0]].lower() not in ("uv", "µv", "μv"):
            raise ValueError(f"{sid}: missing/ambiguous electrode or invalid unit: {name}")
        selected.append(info["labels"][indexes[0]])
    rows = base.read_labels(txt)
    raw = mne.io.read_raw_edf(edf, include=selected, preload=False, infer_types=False, verbose="ERROR")
    try:
        raw.reorder_channels(selected)
        rate = int(round(raw.info["sfreq"]))
        rates = [float(info["samples_per_record"][info["labels"].index(name)]) / info["record_seconds"] for name in selected]
        if rate <= 0 or not np.isclose(rate, raw.info["sfreq"]) or any(not np.isclose(r, rate) for r in rates):
            raise ValueError("mixed or noninteger selected-channel sampling rates")
        rejected = {key: 0 for key in ("no_past_context", "beyond_recording", "flat_signal", "nonfinite", "high_amplitude", "low_variation")}
        candidates = []
        for source, start, _ in rows:
            if source not in SOURCE_TO_STAGE:
                continue
            if start < 10:
                rejected["no_past_context"] += 1
            elif start + 30 > raw.n_times / rate + 1e-9:
                rejected["beyond_recording"] += 1
            else:
                candidates.append((SOURCE_TO_STAGE[source], start))
        if max_epochs is not None:
            candidates = candidates[:max_epochs]
        if not candidates:
            raise ValueError(f"{sid}: no eligible epochs")
        shape = (len(candidates), len(selected), 7500)
        temporary = array_path.with_suffix(".npy.tmp")
        array = np.lib.format.open_memmap(temporary, mode="w+", dtype=np.float32, shape=shape)
        labels, starts = [], []
        for number, (stage, start) in enumerate(candidates, 1):
            first = int(round((start - 10) * rate))
            samples = raw.get_data(start=first, stop=first + 40 * rate) * 1e6
            processed, reason = preprocess_window(samples, rate, montage)
            if reason:
                rejected[reason] += 1
            else:
                array[len(labels)] = processed
                labels.append(STAGES.index(stage))
                starts.append(start)
            if number % 400 == 0:
                base.log(f"{montage} {sid}: checked {number}/{len(candidates)}, kept {len(labels)}")
        array.flush()
        del array
        if not labels:
            raise ValueError(f"{sid}: no clean epochs")
        temporary.replace(array_path)
        meta = {"subject_id": sid, "fingerprint": fingerprint, "source": payload,
                "source_labels": selected, "source_rate_hz": rate, "array_shape": list(shape),
                "labels": labels, "starts_seconds": starts, "counts": np.bincount(labels, minlength=5).tolist(),
                "annotation_counts": {s: sum(SOURCE_TO_STAGE.get(r[0]) == s for r in rows) for s in STAGES},
                "excluded_L": sum(r[0] == "L" for r in rows), "candidate_count": len(candidates), "rejected": rejected}
        base.write_json(meta_path, meta)
        base.log(f"{montage} {sid}: W/N1/N2/N3/REM={meta['counts']}")
        return meta
    finally:
        raw.close()


class EpochDataset:
    def __init__(self, cache, subjects, montage):
        self.montage, self.maps, self.index = montage, {}, []
        count = len(MONTAGES[montage])
        for sid in subjects:
            meta = json.loads((cache / f"{sid}.json").read_text(encoding="utf-8"))
            if meta["source"]["pipeline"] != pipeline_for(montage) or meta["source"].get("max_epochs") is not None:
                raise ValueError("legacy, incompatible, or smoke cache cannot enter five-stage training")
            data = np.load(cache / f"{sid}.npy", mmap_mode="r")
            labels, starts = meta["labels"], meta["starts_seconds"]
            if (list(data.shape) != meta["array_shape"] or data.shape[1:] != (count, 7500)
                    or data.dtype != np.float32 or len(labels) > len(data) or len(labels) != len(starts)
                    or any(type(y) is not int or not 0 <= y < 5 for y in labels)):
                raise ValueError("invalid five-stage cache shape or labels")
            self.maps[sid] = data
            self.index.extend((sid, i, y, starts[i]) for i, y in enumerate(labels))
        self.labels = np.array([r[2] for r in self.index], dtype=np.int64)
        if not len(self.labels) or np.any(np.bincount(self.labels, minlength=5) == 0):
            raise ValueError("split lacks at least one of W/N1/N2/N3/REM")

    def __len__(self):
        return len(self.index)

    def __getitem__(self, i):
        sid, epoch, label, _ = self.index[i]
        x = np.array(self.maps[sid][epoch], dtype=np.float32, copy=True)
        if not np.isfinite(x).all():
            raise ValueError("nonfinite cached waveform")
        x -= x.mean(axis=0, keepdims=True)
        return x / 100.0, label


def validate_checkpoint(checkpoint, montage, split):
    if (checkpoint.get("architecture") != "build_model:" + VERSION
            or checkpoint.get("pipeline") != pipeline_for(montage)
            or checkpoint.get("classes") != list(STAGES)
            or checkpoint.get("channels") != list(MONTAGES[montage])
            or checkpoint.get("split") != split or checkpoint.get("deployment_ready") is not False):
        raise ValueError("incompatible five-stage checkpoint")


def train_one(args, montage, split, fingerprint):
    import torch
    from torch.utils.data import DataLoader
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(4)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    device = "cuda" if torch.cuda.is_available() else "cpu"
    directory = args.output / montage
    settings = {"seed": args.seed, "epochs": args.epochs, "patience": args.patience,
                "batch_size": args.batch_size, "dataset_fingerprint": fingerprint}
    summary_path = directory / "training_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        checkpoint = torch.load(directory / "best.pt", map_location="cpu", weights_only=True)
        validate_checkpoint(checkpoint, montage, split)
        if summary["settings"] != settings or checkpoint["settings"] != settings:
            raise ValueError("completed run settings differ; use a new output")
        return summary
    datasets = {part: EpochDataset(directory / "cache", split[part], montage) for part in ("train", "validation")}
    loaders = {part: DataLoader(ds, batch_size=args.batch_size, shuffle=part == "train", num_workers=0,
                               pin_memory=device == "cuda") for part, ds in datasets.items()}
    counts = np.bincount(datasets["train"].labels, minlength=5)
    model = build_model(torch, montage).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-3)
    loss_fn = torch.nn.CrossEntropyLoss(weight=torch.tensor(counts.sum() / (5 * counts), dtype=torch.float32, device=device))
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=2)
    best_score, best_epoch, history = -1., 0, []
    started = time.monotonic()
    base.log(f"{montage}: training on {device}; train/validation epochs={ {k:len(v) for k,v in datasets.items()} }")
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for x, y in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(x.to(device)), y.to(device))
            if not torch.isfinite(loss):
                raise RuntimeError("nonfinite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        truth, probs = base.evaluate(torch, model, loaders["validation"], device)
        result = metrics(truth, probs)
        score = result["macro_f1"]
        scheduler.step(score)
        history.append({"epoch": epoch, "loss": float(np.mean(losses)), "validation": result})
        base.write_json(directory / "history.json", history)
        if score > best_score:
            best_score, best_epoch = score, epoch
            checkpoint = {"state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                          "architecture": "build_model:" + VERSION, "pipeline": pipeline_for(montage),
                          "channels": list(MONTAGES[montage]), "classes": list(STAGES), "split": split,
                          "epoch": epoch, "settings": settings, "deployment_ready": False}
            temporary = directory / "best.pt.tmp"
            torch.save(checkpoint, temporary)
            temporary.replace(directory / "best.pt")
        base.log(f"{montage} epoch={epoch} loss={history[-1]['loss']:.4f} validation_F1={score:.4f} recalls={result['recall']}")
        if epoch - best_epoch >= args.patience:
            break
    summary = {"settings": settings, "best_epoch": best_epoch, "best_validation_macro_f1": best_score,
               "training_seconds": time.monotonic() - started, "training_class_counts": counts.tolist(),
               "device": device, "epochs_completed": len(history)}
    base.write_json(summary_path, summary)
    base.write_json(directory / "input_contract.json", {"architecture": "build_model:" + VERSION,
                    "classes": list(STAGES), "channels": list(MONTAGES[montage]), "pipeline": pipeline_for(montage),
                    "output_shape": [None, 5], "deployment_ready": False, "hardware_reference_verified": False})
    return summary


def evaluate_all(args, split, summaries):
    import platform
    import torch
    from importlib.metadata import version
    from torch.utils.data import DataLoader
    reports = {}
    for montage, summary in summaries.items():
        directory = args.output / montage
        report_path = directory / "report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report["settings"] != summary["settings"] or report["subject_split"] != split or report["pipeline"] != pipeline_for(montage):
                raise ValueError("existing held-out report differs")
            reports[montage] = report
            continue
        checkpoint = torch.load(directory / "best.pt", map_location="cpu", weights_only=True)
        validate_checkpoint(checkpoint, montage, split)
        model = build_model(torch, montage).cpu().eval()
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        with torch.inference_mode():
            logits = model(torch.zeros(1, len(MONTAGES[montage]), 7500))
        if logits.shape != (1, 5) or not torch.isfinite(logits).all():
            raise ValueError("five-logit CPU checkpoint check failed")
        ds = EpochDataset(directory / "cache", split["test"], montage)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        truth, probs = base.evaluate(torch, model.to(device), DataLoader(ds, batch_size=args.batch_size, num_workers=0), device)
        report = {**summary, "classes": list(STAGES), "channels": list(MONTAGES[montage]),
                  "pipeline": pipeline_for(montage), "subject_split": split, "test": metrics(truth, probs),
                  "per_subject": {}, "cpu_contract_validation": {"output_shape": [1, 5], "finite_logits": True, "strict_state_dict": True},
                  "environment": {"python": platform.python_version(), **{n: version(n) for n in ("torch", "numpy", "scipy", "mne")}}}
        ids = np.array([r[0] for r in ds.index])
        for sid in split["test"]:
            mask = ids == sid
            if mask.any():
                report["per_subject"][sid] = metrics(truth[mask], probs[mask])
        with (directory / "test_predictions.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["subject", "epoch_start_seconds", "truth", "prediction", *[f"p_{s}" for s in STAGES]])
            for (sid, _, label, start), probability in zip(ds.index, probs, strict=True):
                writer.writerow([sid, start, STAGES[label], STAGES[int(probability.argmax())], *probability.tolist()])
        base.write_json(report_path, report)
        reports[montage] = report
        base.log(f"{montage}: held-out test macro-F1={report['test']['macro_f1']:.4f}")
    base.write_json(args.output / "comparison.json", reports)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--split", type=Path, default=Path(__file__).resolve().parents[1] / "results/waveform_cap_v1/split.json")
    parser.add_argument("--models", nargs="+", choices=list(MONTAGES), default=list(DEFAULT_MODELS))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--patience", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--prepare-only", action="store_true")
    group.add_argument("--train-only", action="store_true")
    parser.add_argument("--subject", help="preparation smoke test only")
    parser.add_argument("--max-epochs", type=int, help="preparation smoke test only")
    args = parser.parse_args(argv)
    if min(args.epochs, args.patience, args.batch_size) <= 0 or (args.max_epochs is not None and args.max_epochs <= 0):
        parser.error("training arguments and max-epochs must be positive")
    if (args.subject or args.max_epochs is not None) and not args.prepare_only:
        parser.error("subject/max-epochs require prepare-only and a separate smoke output")
    if len(set(args.models)) != len(args.models):
        parser.error("duplicate models")
    files = base.find_files(args.dataset)
    split = json.loads(args.split.read_text(encoding="utf-8"))
    validate_split(split, [sid for sid, _, _ in files])
    # Refuse every nonempty output lacking our root marker, including legacy roots.
    marker = {"version": VERSION, "classes": list(STAGES)}
    marker_path = args.output / "five_stage_run.json"
    if args.output.exists() and any(args.output.iterdir()):
        if not marker_path.exists() or json.loads(marker_path.read_text(encoding="utf-8")) != marker:
            raise ValueError("output is not an isolated five-stage directory; choose a new output")
    args.output.mkdir(parents=True, exist_ok=True)
    base.write_json(marker_path, marker)
    split_path = args.output / "split.json"
    if split_path.exists() and json.loads(split_path.read_text(encoding="utf-8")) != split:
        raise ValueError("existing subject split differs")
    base.write_json(split_path, split)
    if args.subject:
        files = [row for row in files if row[0] == args.subject.upper()]
        if not files:
            raise ValueError("unknown subject")
    summaries = {}
    for montage in args.models:
        metas = [prepare_subject(sid, edf, txt, args.output / montage / "cache", montage,
                                 args.max_epochs, args.train_only) for sid, edf, txt in files]
        base.write_json(args.output / montage / "manifest.json", {"pipeline": pipeline_for(montage), "split": split,
                        "subjects": [{k:v for k,v in m.items() if k not in ("labels", "starts_seconds")} for m in metas]})
        fingerprint = hashlib.sha256(json.dumps([m["fingerprint"] for m in metas]).encode()).hexdigest()
        if not args.prepare_only:
            summaries[montage] = train_one(args, montage, split, fingerprint)
    if not args.prepare_only:
        evaluate_all(args, split, summaries)
        base.log("All requested five-stage models and held-out evaluations complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
