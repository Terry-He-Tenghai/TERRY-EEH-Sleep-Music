"""Five-stage contracts, windowed preparation and synthetic training integration."""
import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import torch

import train_sleep_five_stage_models as five
import train_sleep_waveform_models as old
import train_sleep_subset_models as subset
import train_sleep_frontal_models as frontal


def write_cache(root, sid, montage, labels=None, smoke=None):
    labels = list(range(5)) if labels is None else labels
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    data = rng.normal(size=(len(labels), len(five.MONTAGES[montage]), 7500)).astype(np.float32)
    np.save(root / f"{sid}.npy", data)
    old.write_json(root / f"{sid}.json", {
        "source": {"pipeline": five.pipeline_for(montage), "max_epochs": smoke},
        "array_shape": list(data.shape), "labels": labels,
        "starts_seconds": [30. * (i + 1) for i in range(len(labels))]})


def test_fp1_f4_has_independent_channel_contract():
    assert five.MONTAGES["fp1_f4"] == ("Fp1", "F4")
    assert five.MONTAGES["frontal2"] == ("Fp1", "Fp2")
    pipeline = five.pipeline_for("fp1_f4")
    assert pipeline["channels"] == ["Fp1", "F4"]
    assert pipeline["qc"]["required_clean_channels"] == ["Fp1", "F4"]
    assert pipeline != five.pipeline_for("frontal2")


def test_labels_metrics_and_invalid_labels():
    assert five.STAGES == ("W", "N1", "N2", "N3", "REM")
    assert five.SOURCE_TO_STAGE["R"] == five.SOURCE_TO_STAGE["REM"] == "REM"
    assert "L" not in five.SOURCE_TO_STAGE
    result = five.metrics(np.arange(5), np.eye(5))
    assert result["macro_f1"] == result["accuracy"] == result["cohen_kappa"] == 1
    assert result["brier_score"] == result["ece_10_bins"] == 0
    assert result["confusion_matrix"] == np.eye(5, dtype=int).tolist()
    assert result["support"] == dict.fromkeys(five.STAGES, 1)
    wrong = five.metrics(np.arange(5), np.roll(np.eye(5), 1, axis=1))
    assert wrong["accuracy"] == wrong["macro_f1"] == 0
    for labels, probs in [(np.array([5]), np.ones((1, 5)) / 5),
                           (np.array([-1]), np.ones((1, 5)) / 5),
                           (np.arange(5), np.eye(3)),
                           (np.arange(5), np.full((5, 5), np.nan))]:
        with pytest.raises(ValueError):
            five.metrics(labels, probs)


def test_all_montages_five_logits_and_legacy_unchanged():
    before = copy.deepcopy(old.PIPELINE)
    torch.set_num_threads(2)
    for name, channels in five.MONTAGES.items():
        model = five.build_model(torch, name).eval()
        with torch.inference_mode():
            logits = model(torch.zeros(2, len(channels), 7500))
        assert logits.shape == (2, 5)
        assert torch.isfinite(logits).all()
        pipeline = five.pipeline_for(name)
        assert pipeline["classes"] == list(five.STAGES)
        assert pipeline["channels"] == list(channels)
        t = np.arange(10000) / 250
        wave = np.stack([15 * np.sin(2 * np.pi * (i + 2) * t) for i in range(len(channels))])
        processed, reason = five.preprocess_window(wave, 250, name)
        assert reason is None
        assert processed.shape == (len(channels), 7500)
    assert old.PIPELINE == before
    assert old.STAGES == subset.STAGES == frontal.STAGES == ("W", "N1", "N2")
    assert old.build_model(torch, 8)[-1].out_features == 3
    assert frontal.build_model(torch, 2)[-1].out_features == 3


def test_split_reuse_and_leakage_rejection():
    split = old.split_subjects([f"EPCTL{i:02d}" for i in range(28)], 42)
    subjects = sum(split.values(), [])
    five.validate_split(split, subjects)
    broken = copy.deepcopy(split)
    broken["train"].append(broken["test"][0])
    with pytest.raises(ValueError):
        five.validate_split(broken, subjects)
    with pytest.raises(ValueError):
        five.validate_split(split, subjects[:-1])


def test_cache_separation_and_missing_classes(tmp_path):
    write_cache(tmp_path, "s", "frontal2")
    ds = five.EpochDataset(tmp_path, ["s"], "frontal2")
    x, y = ds[4]
    assert y == 4 and x.shape == (2, 7500)
    np.testing.assert_allclose(x.mean(axis=0), 0, atol=1e-7)
    path = tmp_path / "s.json"
    meta = json.loads(path.read_text())
    for pipeline, smoke in [(frontal.pipeline_for(2), None), (five.pipeline_for("frontal2"), 5)]:
        meta["source"].update(pipeline=pipeline, max_epochs=smoke)
        old.write_json(path, meta)
        with pytest.raises(ValueError):
            five.EpochDataset(tmp_path, ["s"], "frontal2")
    del ds  # Release the Windows memory map before replacing the cache fixture.
    write_cache(tmp_path, "s", "frontal2", labels=[0, 1, 2, 3])
    with pytest.raises(ValueError, match="lacks"):
        five.EpochDataset(tmp_path, ["s"], "frontal2")
    write_cache(tmp_path, "s", "frontal2", labels=[0, 1, 2, 3, 5])
    with pytest.raises(ValueError, match="invalid"):
        five.EpochDataset(tmp_path, ["s"], "frontal2")


def test_windowed_preparation_mapping_and_fingerprint(tmp_path):
    edf, txt = tmp_path / "source.edf", tmp_path / "labels.txt"
    edf.write_bytes(b"fixture")
    txt.write_text("W 0 30\nW 30 30\nN1 60 30\nN2 90 30\nN3 120 30\nR 150 30\nREM 180 30\nL 210 30\n")
    reads = []
    class Raw:
        info = {"sfreq": 250.}
        n_times = 240 * 250
        closed = False
        def reorder_channels(self, names):
            assert names == ["Fp1", "Fp2"]
        def get_data(self, *, start, stop):
            reads.append((start, stop))
            assert stop - start == 40 * 250
            t = np.arange(start, stop) / 250
            return np.stack([15e-6 * np.sin(2 * np.pi * hz * t) for hz in (5, 7)])
        def close(self):
            self.closed = True
    raw = Raw()
    header = {"labels": ["Fp1", "Fp2"], "units": ["uV", "uV"],
              "samples_per_record": ["250", "250"], "record_seconds": 1}
    with patch.object(old, "header_info", return_value=header), patch("mne.io.read_raw_edf", return_value=raw) as reader:
        meta = five.prepare_subject("s", edf, txt, tmp_path / "cache", "frontal2")
        assert reader.call_args.kwargs["preload"] is False
        assert reader.call_args.kwargs["include"] == ["Fp1", "Fp2"]
    assert raw.closed
    assert len(reads) == 6
    assert meta["labels"] == [0, 1, 2, 3, 4, 4]
    assert meta["counts"] == [1, 1, 1, 1, 2]
    assert meta["excluded_L"] == 1
    assert meta["rejected"]["no_past_context"] == 1
    assert meta["starts_seconds"] == [30., 60., 90., 120., 150., 180.]
    # Reuse does not touch EDF; changing annotations invalidates the cache.
    assert five.prepare_subject("s", edf, txt, tmp_path / "cache", "frontal2") == meta
    txt.write_text(txt.read_text() + "W 240 30\n")
    with pytest.raises(ValueError, match="incompatible"):
        five.prepare_subject("s", edf, txt, tmp_path / "cache", "frontal2")


def test_legacy_output_refused_before_write(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    split = {"train": ["a"], "validation": ["b"], "test": ["c"]}
    split_path = tmp_path / "original_split.json"
    old.write_json(split_path, split)
    output = tmp_path / "legacy"
    output.mkdir()
    weights = output / "best.pt"
    weights.write_bytes(b"old weights")
    with patch.object(old, "find_files", return_value=[(s, Path(s), Path(s)) for s in "abc"]):
        with pytest.raises(ValueError, match="isolated"):
            five.main(["--dataset", str(dataset), "--output", str(output), "--split", str(split_path), "--prepare-only"])
    assert weights.read_bytes() == b"old weights"
    assert list(output.iterdir()) == [weights]


def test_cpu_training_checkpoint_and_five_probability_csv(tmp_path):
    args = SimpleNamespace(output=tmp_path, seed=42, epochs=1, patience=1, batch_size=5)
    split = {"train": ["train"], "validation": ["val"], "test": ["heldout"]}
    for sid in sum(split.values(), []):
        write_cache(tmp_path / "frontal2/cache", sid, "frontal2")
    accesses = []
    dataset = five.EpochDataset
    def tracked(cache, subjects, montage):
        accesses.append(subjects)
        return dataset(cache, subjects, montage)
    with patch("torch.cuda.is_available", return_value=False), patch.object(five, "EpochDataset", side_effect=tracked):
        summary = five.train_one(args, "frontal2", split, "synthetic")
        assert accesses == [["train"], ["val"]]
        five.evaluate_all(args, split, {"frontal2": summary})
        assert accesses[-1] == ["heldout"]
    directory = tmp_path / "frontal2"
    checkpoint = torch.load(directory / "best.pt", weights_only=True)
    five.validate_checkpoint(checkpoint, "frontal2", split)
    final_layer = str(len(five.build_model(torch, "frontal2")) - 1)
    assert checkpoint["state_dict"][f"{final_layer}.weight"].shape == (5, 64)
    report = json.loads((directory / "report.json").read_text())
    assert len(report["test"]["confusion_matrix"]) == 5
    assert report["training_class_counts"] == [1] * 5
    assert report["cpu_contract_validation"]["output_shape"] == [1, 5]
    with (directory / "test_predictions.csv").open(newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0][-5:] == ["p_W", "p_N1", "p_N2", "p_N3", "p_REM"]
    assert len(rows) == 6
    assert all(r[0] == "heldout" for r in rows[1:])
    before = (directory / "report.json").read_bytes()
    with patch.object(old, "evaluate", side_effect=AssertionError("heldout reevaluated")):
        five.evaluate_all(args, split, {"frontal2": summary})
    assert (directory / "report.json").read_bytes() == before
    checkpoint["classes"] = list(old.STAGES)
    with pytest.raises(ValueError):
        five.validate_checkpoint(checkpoint, "frontal2", split)
