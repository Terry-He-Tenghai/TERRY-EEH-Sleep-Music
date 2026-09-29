"""End-to-end synthetic smoke test; these scores are NOT real-data results."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

import train_sleep_waveform_models as training


def test_two_models_have_separate_checkpoints_and_same_held_out_subjects(tmp_path):
    torch = pytest.importorskip("torch")
    cache = tmp_path / "cache"
    cache.mkdir()
    subjects = [f"EPCTL{i:02}" for i in range(1, 10)]
    rng = np.random.default_rng(11)
    for sid in subjects:
        samples = rng.normal(0, 15, (6, 16, 7500)).astype(np.float32)
        np.save(cache / f"{sid}.npy", samples)
        training.write_json(cache / f"{sid}.json", {
            "source": {"max_epochs": None}, "array_shape": list(samples.shape),
            "labels": [0, 1, 2, 0, 1, 2], "starts_seconds": [30, 60, 90, 120, 150, 180],
        })
    split = training.split_subjects(subjects, 42)
    args = SimpleNamespace(output=tmp_path, seed=42, epochs=1, batch_size=6, patience=1)
    for count in (8, 16):
        report = training.train_one(args, count, split, "synthetic-test")
        assert report["subject_split"] == split
        assert report["test"]["n_epochs"] == 12
        assert report["channels"] == list(training.CAP16[:count])
        assert set(report["per_subject"]) == set(split["test"])
        weights = torch.load(tmp_path / f"cap{count}" / "best.pt", map_location="cpu", weights_only=True)
        assert weights["deployment_ready"] is False
        assert weights["channels"] == list(training.CAP16[:count])
        assert weights["state_dict"]["0.weight"].shape[1] == count
        contract = json.loads((tmp_path / f"cap{count}" / "input_contract.json").read_text())
        assert contract["hardware_reference_verified"] is False
        assert training.train_one(args, count, split, "synthetic-test") == report
