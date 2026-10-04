"""Independent selected-electrode CAP waveform training. Original EDFs are read-only."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import random
import time
from pathlib import Path
import numpy as np
import train_sleep_waveform_models as base

MONTAGES = {2: ("C3", "C4"), 4: ("Fp1", "Fp2", "C3", "C4"),
            6: ("Fp1", "Fp2", "C3", "C4", "F3", "F4")}
STAGES = base.STAGES
RATE = 250
WINDOW_SECONDS = 30
CONTEXT_SECONDS = 10


def pipeline_for(count):
    channels = MONTAGES[count]
    result = json.loads(json.dumps(base.PIPELINE))
    result.update(version="cap-waveform-subset-v1", channels=list(channels))
    result["qc"]["require_all_16_clean"] = False
    result["qc"]["required_clean_channels"] = list(channels)
    result["qc"]["scope"] = "selected electrodes only, before average reference"
    return result


def quality_details(samples_uv, input_rate, count):
    from scipy.signal import butter, iirnotch, resample_poly, sosfilt, tf2sos
    if isinstance(input_rate, bool) or int(input_rate) != input_rate or input_rate <= 0:
        raise ValueError("input_rate must be a positive integer")
    input_rate = int(input_rate)
    channels = MONTAGES[count]
    x = np.asarray(samples_uv, dtype=np.float64)
    if x.shape != (count, 40 * input_rate):
        raise ValueError(f"expected {(count, 40 * input_rate)}, got {x.shape}")
    if not np.isfinite(x).all():
        return np.empty((0,)), "nonfinite", {"channels": list(channels), "finite": False}
    flat = (x[:, -30 * input_rate:].reshape(count, 30, input_rate).std(axis=-1) < 0.1).sum(axis=1)
    factor = math.gcd(input_rate, RATE)
    if input_rate != RATE:
        x = resample_poly(x, RATE // factor, input_rate // factor, axis=-1)
    b, a = iirnotch(50, 30, fs=RATE)
    sos = np.concatenate((tf2sos(b, a), butter(4, [0.5, 35], btype="bandpass", fs=RATE, output="sos")))
    x = sosfilt(sos, x, axis=-1)[:, -30 * RATE:]
    ptp, std = np.ptp(x, axis=1), np.std(x, axis=1)
    details = {name: {"flat_seconds": int(flat[i]), "filtered_ptp_uv": float(ptp[i]),
                      "filtered_std_uv": float(std[i])} for i, name in enumerate(channels)}
    reason = ("flat_signal" if np.any(flat > 2) else "high_amplitude" if np.any(ptp > 500)
              else "low_variation" if np.any(std < 0.1) else None)
    return (np.empty((0,)) if reason else x.astype(np.float32)), reason, details


def preprocess_window(samples_uv, input_rate, count):
    processed, reason, _ = quality_details(samples_uv, input_rate, count)
    return processed, reason


def model_input(processed, count):
    MONTAGES[count]
    selected = np.array(processed, dtype=np.float32, copy=True)
    if selected.shape != (count, 7500) or not np.isfinite(selected).all():
        raise ValueError("expected finite selected-channel 30s processed waveform")
    selected -= selected.mean(axis=0, keepdims=True)
    return selected / 100.0


def build_model(torch, count):
    MONTAGES[count]
    return base.build_model(torch, count)


def channel_selection(info, count):
    selected = []
    for target in MONTAGES[count]:
        matches = [i for i, label in enumerate(info["labels"]) if base.canonical(label) == target.upper()]
        if len(matches) != 1:
            raise ValueError(f"{target}: expected exactly one source, got {matches}")
        index = matches[0]
        if info["units"][index].lower() not in ("uv", "µv", "μv"):
            raise ValueError(f"{target}: source must be calibrated in uV")
        selected.append(info["labels"][index])
    return selected


def load_selected_edf(edf, count):
    """Read only selected EDF signal blocks, using header physical calibration."""
    info = base.header_info(edf)
    selected = channel_selection(info, count)
    indices = [info['labels'].index(name) for name in selected]
    rates = [int(info['samples_per_record'][i]) / info['record_seconds'] for i in indices]
    rate = int(round(rates[0]))
    if rate <= 0 or any(not np.isclose(r, rate) for r in rates):
        raise ValueError('mixed or noninteger rates')
    with edf.open('rb') as stream:
        header = stream.read(256)
    offset, nrecords = int(header[184:192]), int(header[236:244])
    sizes = np.array(info['samples_per_record'], dtype=np.int64)
    total = int(sizes.sum())
    actual = edf.stat().st_size - offset
    if total <= 0 or actual < 0 or actual % (total * 2):
        raise ValueError('EDF data length does not match full records')
    available = actual // (total * 2)
    if nrecords == -1:
        nrecords = available
    if nrecords != available or offset != 256 * (len(sizes) + 1):
        raise ValueError('EDF record/header count mismatch')
    data = np.memmap(edf, mode='r', dtype='<i2', offset=offset, shape=(nrecords, total))
    starts = np.concatenate(([0], np.cumsum(sizes)))
    result = np.empty((count, nrecords * int(sizes[indices[0]])), dtype=np.float64)
    for j, i in enumerate(indices):
        pmin, pmax = float(info['physical_min'][i]), float(info['physical_max'][i])
        dmin, dmax = int(info['digital_min'][i]), int(info['digital_max'][i])
        if dmax <= dmin or pmax <= pmin or not np.isfinite([pmin, pmax]).all():
            raise ValueError('invalid EDF calibration')
        result[j] = np.asarray(data[:, starts[i]:starts[i + 1]], dtype=np.float64).reshape(-1)
        result[j] -= dmin
        result[j] *= (pmax - pmin) / (dmax - dmin)
        result[j] += pmin
    del data
    return result, rate, info, selected


def prepare_subject(sid, edf, txt, cache, count):
    cache.mkdir(parents=True, exist_ok=True)
    payload = {"edf": str(edf.resolve()), "size": edf.stat().st_size,
               "mtime_ns": edf.stat().st_mtime_ns,
               "annotation_sha256": hashlib.sha256(txt.read_bytes()).hexdigest(),
               "pipeline": pipeline_for(count)}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    meta_path, array_path = cache / f"{sid}.json", cache / f"{sid}.npy"
    if meta_path.exists() and array_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        data = np.load(array_path, mmap_mode="r")
        if meta["fingerprint"] != fingerprint or list(data.shape) != meta["array_shape"] or data.dtype != np.float32:
            raise ValueError(f"{sid}: stale cache")
        base.log(f"cap{count} {sid}: reuse {len(meta['labels'])} epochs")
        return meta
    rows = base.read_labels(txt)
    source_uv, rate, info, selected = load_selected_edf(edf, count)
    try:
        rejected = {k: 0 for k in ("no_past_context", "beyond_recording", "flat_signal", "nonfinite", "high_amplitude", "low_variation")}
        candidates = []
        for stage, start, _ in rows:
            if stage not in STAGES:
                continue
            if start < 10:
                rejected["no_past_context"] += 1
            elif start + 30 > source_uv.shape[1] / rate + 1e-9:
                rejected["beyond_recording"] += 1
            else:
                candidates.append((stage, start))
        shape = (len(candidates), count, 7500)
        array = np.lib.format.open_memmap(array_path, mode="w+", dtype=np.float32, shape=shape)
        labels, starts = [], []
        for stage, start in candidates:
            first = int(round((start - 10) * rate))
            x, reason = preprocess_window(source_uv[:, first:first + 40 * rate], rate, count)
            if reason:
                rejected[reason] += 1
            else:
                array[len(labels)] = x
                labels.append(STAGES.index(stage))
                starts.append(start)
        array.flush()
        del array
        if not labels:
            raise ValueError(f"{sid}: no clean selected-channel epochs")
        meta = {"subject_id": sid, "fingerprint": fingerprint, "source": payload,
                "source_labels": selected, "source_rate_hz": rate, "array_shape": list(shape),
                "labels": labels, "starts_seconds": starts, "counts": np.bincount(labels, minlength=3).tolist(),
                "annotation_counts": {s: sum(r[0] == s for r in rows) for s in (*STAGES, "N3", "R", "L")},
                "candidate_count": len(candidates), "rejected": rejected}
        base.write_json(meta_path, meta)
        base.log(f"cap{count} {sid}: kept={len(labels)}/{len(candidates)} counts={meta['counts']}")
        return meta
    finally:
        del source_uv


class EpochDataset:
    def __init__(self, cache, subjects, count):
        self.count, self.maps, self.index = count, {}, []
        for sid in subjects:
            meta = json.loads((cache / f"{sid}.json").read_text(encoding="utf-8"))
            if meta["source"]["pipeline"] != pipeline_for(count):
                raise ValueError("incompatible cache contract")
            data = np.load(cache / f"{sid}.npy", mmap_mode="r")
            if list(data.shape) != meta["array_shape"] or data.shape[1:] != (count, 7500) or data.dtype != np.float32:
                raise ValueError("invalid cache")
            self.maps[sid] = data
            self.index.extend((sid, i, label, meta["starts_seconds"][i]) for i, label in enumerate(meta["labels"]))
        self.labels = np.asarray([r[2] for r in self.index], dtype=np.int64)
        if len(self.labels) == 0 or np.any(np.bincount(self.labels, minlength=3) == 0):
            raise ValueError("split missing classes")
    def __len__(self):
        return len(self.index)
    def __getitem__(self, i):
        sid, epoch, label, _ = self.index[i]
        return model_input(self.maps[sid][epoch], self.count), label


def train_one(args, count, split, fingerprint):
    import torch
    from torch.utils.data import DataLoader
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this run")
    device = "cuda"
    directory = args.output / f"cap{count}"
    settings = {"seed": args.seed, "epochs": args.epochs, "patience": args.patience,
                "batch_size": args.batch_size, "dataset_fingerprint": fingerprint}
    training_path = directory / "training_summary.json"
    if training_path.exists():
        old = json.loads(training_path.read_text(encoding="utf-8"))
        if old["settings"] != settings or not (directory / "best.pt").exists():
            raise ValueError("training settings mismatch")
        return old
    datasets = {k: EpochDataset(directory / "cache", split[k], count) for k in ("train", "validation")}
    loaders = {k: DataLoader(d, batch_size=args.batch_size, shuffle=k == "train", num_workers=0, pin_memory=True) for k, d in datasets.items()}
    counts = np.bincount(datasets["train"].labels, minlength=3)
    model = build_model(torch, count).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-3)
    loss_fn = torch.nn.CrossEntropyLoss(weight=torch.tensor(counts.sum() / (3 * counts), dtype=torch.float32, device=device))
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=2)
    best_score, best_epoch, history = -1., 0, []
    started = time.monotonic()
    base.log(f"cap{count}: TRAINING START CUDA {torch.cuda.get_device_name(0)}, epochs={ {k:len(v) for k,v in datasets.items()} }")
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for x, y in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(x.to(device, non_blocking=True)), y.to(device, non_blocking=True))
            if not torch.isfinite(loss):
                raise RuntimeError("nonfinite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        truth, probs = base.evaluate(torch, model, loaders["validation"], device)
        result = base.metrics(truth, probs)
        score = result["macro_f1"]
        scheduler.step(score)
        history.append({"epoch": epoch, "loss": float(np.mean(losses)), "validation": result})
        base.write_json(directory / "history.json", history)
        if score > best_score:
            best_score, best_epoch = score, epoch
            checkpoint = {"state_dict": {k:v.detach().cpu() for k,v in model.state_dict().items()},
                          "architecture": "build_model:" + pipeline_for(count)["version"], "channels": list(MONTAGES[count]),
                          "pipeline": pipeline_for(count), "classes": list(STAGES), "split": split,
                          "epoch": epoch, "settings": settings, "deployment_ready": False}
            temporary = directory / "best.pt.tmp"
            torch.save(checkpoint, temporary)
            temporary.replace(directory / "best.pt")
        base.log(f"cap{count} epoch={epoch} loss={history[-1]['loss']:.4f} val_F1={score:.4f} recalls={result['recall']}")
        if epoch - best_epoch >= args.patience:
            break
    summary = {"settings": settings, "best_epoch": best_epoch, "best_validation_macro_f1": best_score,
               "training_seconds": time.monotonic() - started, "training_class_counts": counts.tolist(),
               "device": torch.cuda.get_device_name(0), "epochs_completed": len(history)}
    base.write_json(training_path, summary)
    base.write_json(directory / "input_contract.json", {"channels": list(MONTAGES[count]), "pipeline": pipeline_for(count), "deployment_ready": False})
    return summary


def evaluate_all(args, split, summaries):
    import torch
    from torch.utils.data import DataLoader
    predictions, reports = {}, {}
    for count in MONTAGES:
        directory = args.output / f"cap{count}"
        ds = EpochDataset(directory / "cache", split["test"], count)
        model = build_model(torch, count).cuda()
        checkpoint = torch.load(directory / "best.pt", map_location="cpu", weights_only=True)
        model.load_state_dict(checkpoint["state_dict"])
        truth, probs = base.evaluate(torch, model, DataLoader(ds, batch_size=args.batch_size, num_workers=0, pin_memory=True), "cuda")
        predictions[count] = {(row[0], row[3]): (int(y), p) for row, y, p in zip(ds.index, truth, probs, strict=True)}
        report = {**summaries[count], "channels": list(MONTAGES[count]), "pipeline": pipeline_for(count),
                  "subject_split": split, "test": base.metrics(truth, probs), "per_subject": {}}
        with (directory / "test_predictions.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["subject", "epoch_start_seconds", "truth", "prediction", "p_W", "p_N1", "p_N2"])
            for (sid, start), (y, p) in predictions[count].items():
                writer.writerow([sid, start, STAGES[y], STAGES[int(p.argmax())], *p.tolist()])
        ids = np.array([r[0] for r in ds.index])
        for sid in split["test"]:
            mask = ids == sid
            if mask.any():
                report["per_subject"][sid] = base.metrics(truth[mask], probs[mask])
        reports[count] = report
    common = sorted(set.intersection(*(set(v) for v in predictions.values())))
    if not common:
        raise ValueError("no common qualified test epochs")
    for count, report in reports.items():
        truth = np.array([predictions[count][key][0] for key in common])
        for key in common:
            if len({predictions[c][key][0] for c in MONTAGES}) != 1:
                raise ValueError("common test label mismatch")
        probs = np.stack([predictions[count][key][1] for key in common])
        report["common_qualified_test"] = base.metrics(truth, probs)
        qualification = {}
        for part, subjects in split.items():
            metas = [json.loads((args.output / f"cap{count}" / "cache" / f"{sid}.json").read_text(encoding="utf-8")) for sid in subjects]
            eligible = sum(m["candidate_count"] for m in metas)
            labelled = sum(sum(m["annotation_counts"][s] for s in STAGES) for m in metas)
            kept = sum(len(m["labels"]) for m in metas)
            qualification[part] = {"qualified": kept, "eligible": eligible, "labelled_W_N1_N2": labelled,
                                   "qualified_fraction_eligible": kept / eligible, "qualified_fraction_labelled": kept / labelled,
                                   "per_class": {s: {"qualified": sum(m["counts"][i] for m in metas),
                                   "labelled": sum(m["annotation_counts"][s] for m in metas),
                                   "qualified_fraction_labelled": sum(m["counts"][i] for m in metas) / sum(m["annotation_counts"][s] for m in metas)} for i,s in enumerate(STAGES)}}
        report["qualification"] = qualification
        base.write_json(args.output / f"cap{count}" / "report.json", report)
    base.write_json(args.output / "common_test_windows.json", [{"subject": sid, "start_seconds": start} for sid,start in common])
    base.write_json(args.output / "comparison.json", {f"cap{c}": r for c,r in reports.items()})
    lines = ["# CAP selected-electrode training results", "", "Research only. Test evaluated after all three validation-selected models completed.",
             f"Common qualified test windows: {len(common)}. Original subject split retained.", ""]
    for count, r in reports.items():
        lines.extend([f"## cap{count}: {', '.join(MONTAGES[count])}",
                      f"Best epoch {r['best_epoch']}; epochs completed {r['epochs_completed']}; validation macro F1 {r['best_validation_macro_f1']:.4f}.",
                      f"Own qualified test: {r['test']['n_epochs']} windows; macro F1 {r['test']['macro_f1']:.4f}; accuracy {r['test']['accuracy']:.4f}.",
                      f"Common test macro F1 {r['common_qualified_test']['macro_f1']:.4f}; accuracy {r['common_qualified_test']['accuracy']:.4f}.",
                      f"Test qualified/eligible: {r['qualification']['test']['qualified_fraction_eligible']:.2%}."])
        q = r['qualification']['test']
        lines.append('Test per-class qualification: ' + '; '.join(f"{s} {q['per_class'][s]['qualified']}/{q['per_class'][s]['labelled']} ({q['per_class'][s]['qualified_fraction_labelled']:.2%})" for s in STAGES))
        for scope in ("test", "common_qualified_test"):
            lines.append(f"{scope}: " + "; ".join(f"{s} F1={r[scope]['f1'][s]:.4f}, recall={r[scope]['recall'][s]:.4f}" for s in STAGES))
        lines.append("")
    (args.output / "TRAINING_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    base.log("ALL TRAINING AND HELD-OUT EVALUATION COMPLETE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", type=Path, default=Path(__file__).resolve().parents[1] / "results/waveform_cap_v1/split.json")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--patience", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if min(args.epochs, args.patience, args.batch_size) <= 0:
        parser.error("training arguments must be positive")
    files = base.find_files(args.dataset)
    split = json.loads(args.split.read_text(encoding="utf-8"))
    if set(split) != {"train", "validation", "test"}:
        raise ValueError("invalid original split")
    ids = [sid for part in split.values() for sid in part]
    if len(ids) != len(set(ids)) or set(ids) != {r[0] for r in files}:
        raise ValueError("original split does not exactly match extracted subjects")
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "split.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != split:
        raise ValueError("output split mismatch")
    base.write_json(target, split)
    summaries = {}
    for count in MONTAGES:
        metas = [prepare_subject(sid, edf, txt, args.output / f"cap{count}" / "cache", count) for sid,edf,txt in files]
        base.write_json(args.output / f"cap{count}" / "manifest.json", {"pipeline": pipeline_for(count), "split": split,
                        "subjects": [{k:v for k,v in m.items() if k not in ("labels", "starts_seconds")} for m in metas]})
        fingerprint = hashlib.sha256(json.dumps([m["fingerprint"] for m in metas]).encode()).hexdigest()
        if not args.prepare_only:
            summaries[count] = train_one(args, count, split, fingerprint)
    if not args.prepare_only:
        evaluate_all(args, split, summaries)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
