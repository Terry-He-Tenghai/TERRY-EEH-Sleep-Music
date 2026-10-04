"""Independent frontal CAP training; source EDFs are opened read-only.

Reuse the subset training implementation in an isolated module namespace so its
original central montages and preprocessing contract remain unchanged.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import numpy as np
import train_sleep_waveform_models as base

VERSION = "cap-waveform-frontal-v1"
ARCHITECTURE = "build_model:" + VERSION
MONTAGES = {2: ("Fp1", "Fp2"), 4: ("Fp1", "Fp2", "F3", "F4"),
            6: ("Fp1", "Fp2", "F3", "F4", "F7", "F8")}
STAGES = base.STAGES
RATE = 250
WINDOW_SECONDS = 30
CONTEXT_SECONDS = 10

_spec = importlib.util.spec_from_file_location(
    "_frontal_subset_core", Path(__file__).with_name("train_sleep_subset_models.py"))
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)
_core.MONTAGES = MONTAGES.copy()
_quality_details = _core.quality_details
_model_input = _core.model_input
_train_one = _core.train_one
_evaluate_all = _core.evaluate_all


def pipeline_for(count):
    channels = MONTAGES[count]
    result = json.loads(json.dumps(base.PIPELINE))
    result.update(version=VERSION, channels=list(channels))
    result["qc"].update(require_all_16_clean=False,
                        required_clean_channels=list(channels),
                        scope="selected electrodes only, before average reference")
    return result


def quality_details(samples_uv, input_rate, count):
    return _quality_details(samples_uv, input_rate, count)


def preprocess_window(samples_uv, input_rate, count):
    processed, reason, _ = quality_details(samples_uv, input_rate, count)
    return processed, reason


def model_input(processed, count):
    return _model_input(processed, count)


def build_model(torch, count):
    MONTAGES[count]
    return base.build_model(torch, count)


def validate_checkpoint(checkpoint, count, split=None):
    if (checkpoint.get("architecture") != ARCHITECTURE
            or checkpoint.get("channels") != list(MONTAGES[count])
            or checkpoint.get("pipeline") != pipeline_for(count)
            or checkpoint.get("classes") != list(STAGES)
            or checkpoint.get("deployment_ready") is not False):
        raise ValueError("incompatible frontal checkpoint contract")
    if split is not None and checkpoint.get("split") != split:
        raise ValueError("frontal checkpoint subject split mismatch")


def train_one(args, count, split, fingerprint):
    import torch
    checkpoint = args.output / f"cap{count}" / "best.pt"
    if checkpoint.exists():
        validate_checkpoint(torch.load(checkpoint, map_location="cpu", weights_only=True), count, split)
    result = _train_one(args, count, split, fingerprint)
    validate_checkpoint(torch.load(checkpoint, map_location="cpu", weights_only=True), count, split)
    return result


def evaluate_all(args, split, summaries):
    import torch
    for count in MONTAGES:
        checkpoint = torch.load(args.output / f"cap{count}" / "best.pt",
                                map_location="cpu", weights_only=True)
        validate_checkpoint(checkpoint, count, split)
        model = build_model(torch, count).cpu().eval()
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        with torch.inference_mode():
            output = model(torch.zeros(1, count, WINDOW_SECONDS * RATE))
        if output.shape != (1, len(STAGES)) or not torch.isfinite(output).all():
            raise ValueError("frontal checkpoint CPU inference failed")
    _evaluate_all(args, split, summaries)
    base.write_json(args.output / "cpu_contract_validation.json", {
        "architecture": ARCHITECTURE, "passed": True,
        "models": {f"cap{c}": {"channels": list(MONTAGES[c]), "output_shape": [1, 3],
                    "strict_state_dict": True, "finite_logits": True} for c in MONTAGES},
        "real_device_validated": False})


# Every reused function resolves the frontal-specific hooks in its own globals.
_core.pipeline_for = pipeline_for
_core.quality_details = quality_details
_core.preprocess_window = preprocess_window
_core.model_input = model_input
_core.build_model = build_model
_core.train_one = train_one
_core.evaluate_all = evaluate_all
EpochDataset = _core.EpochDataset
channel_selection = _core.channel_selection
load_selected_edf = _core.load_selected_edf
prepare_subject = _core.prepare_subject


def main():
    return _core.main()


if __name__ == "__main__":
    raise SystemExit(main())
