"""Research-only cap8/cap16 raw waveform inference, sharing the training code.

Physical acquisition remains 16-channel even for cap8: the first training pilot
used the same all-16-clean windows for both models. No missing-channel filling,
spectral fallback, or claim of hardware/clinical validation is made here.
"""
from __future__ import annotations

import importlib.util
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

ORIGIN = "trained_waveform_cnn_experimental"


class WaveformModelError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@lru_cache(maxsize=1)
def training_code():
    path = Path(__file__).resolve().parents[1] / "script" / "train_sleep_waveform_models.py"
    spec = importlib.util.spec_from_file_location("terry_waveform_training_contract", path)
    if spec is None or spec.loader is None:
        raise WaveformModelError("waveform_model_contract_mismatch")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_settings():
    try:
        path = Path(__file__).with_name("config.waveform.yaml")
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict) or settings.get("enabled") is not True:
            raise ValueError("waveform research inference must be explicitly enabled")
        root = Path(settings["model_root"])
        if not root.is_absolute():
            root = path.parent / root
        confirmations = settings["confirmations_required"]
        minimum = settings["minimum_stage_probability"]
        if type(confirmations) is not int or confirmations < 1 or not 0.5 <= float(minimum) <= 1:
            raise ValueError("invalid classification gate")
        return {**settings, "model_root": root.resolve()}
    except Exception as exc:
        raise WaveformModelError("waveform_model_configuration_error") from exc


class WaveformClassifier:
    def __init__(self, names, rate, count, *, model_root=None, predictor=None):
        self.contract = training_code()
        self.count, self.rate = count, rate
        if tuple(names) != self.contract.CAP16:
            raise WaveformModelError("waveform_requires_full_cap_capture")
        if count not in (8, 16) or rate != self.contract.RATE:
            raise WaveformModelError("waveform_model_contract_mismatch")
        self.model = None
        self.predictor = predictor
        if predictor is None:
            root = model_root if model_root is not None else load_settings()["model_root"]
            weight_path = Path(root) / f"cap{count}" / "best.pt"
            if not weight_path.is_file():
                raise WaveformModelError("waveform_model_missing")
            try:
                import torch
                checkpoint = torch.load(weight_path, map_location="cpu", weights_only=True)
                if (checkpoint.get("channels") != list(self.contract.CAP16[:count])
                        or checkpoint.get("classes") != list(self.contract.STAGES)
                        or checkpoint.get("pipeline") != self.contract.PIPELINE
                        or checkpoint.get("architecture") != "build_model:cap-waveform-v1"):
                    raise WaveformModelError("waveform_model_contract_mismatch")
                self.model = self.contract.build_model(torch, count)
                self.model.load_state_dict(checkpoint["state_dict"], strict=True)
                self.model.eval()
                self.torch = torch
            except WaveformModelError:
                raise
            except Exception as exc:
                raise WaveformModelError("waveform_model_load_failed") from exc
        self.reset()

    def reset(self):
        self.buffer = np.empty((16, 0), dtype=float)
        self.last_end = None

    def info(self):
        return {"model": f"cap{self.count}", "experimental": True,
                "collected_seconds": self.buffer.shape[1] / self.rate,
                "required_seconds": 40, "classes": list(self.contract.STAGES),
                "hardware_validated": False, "probabilities_calibrated": False,
                "window_seconds": 30, "update_seconds": 6}

    def update(self, samples_uv, end_s):
        samples = np.asarray(samples_uv, dtype=float)
        if samples.ndim != 2 or samples.shape[0] != 16 or samples.shape[1] == 0 or not math.isfinite(end_s):
            raise ValueError("invalid waveform chunk")
        if self.last_end is not None and abs(end_s - self.last_end - samples.shape[1] / self.rate) > 1 / self.rate:
            self.reset()
        self.last_end = end_s
        if not np.isfinite(samples).all():
            self.reset()
            return {"status": "invalid", "reason": "nonfinite", "probabilities": None, "info": self.info()}
        self.buffer = np.concatenate((self.buffer, samples), axis=1)[:, -40 * self.rate:]
        if self.buffer.shape[1] < 40 * self.rate:
            return {"status": "waiting", "probabilities": None, "info": self.info()}
        processed, reason = self.contract.preprocess_window(self.buffer, self.rate)
        if reason:
            self.reset()
            return {"status": "invalid", "reason": reason, "probabilities": None, "info": self.info()}
        values = self.contract.model_input(processed, self.count)
        if self.predictor is not None:
            probabilities = np.asarray(self.predictor(values), dtype=float)
        else:
            with self.torch.inference_mode():
                output = self.model(self.torch.from_numpy(values[None, ...]))
                probabilities = self.torch.softmax(output, dim=1)[0].cpu().numpy().astype(float)
        if (probabilities.shape != (3,) or not np.isfinite(probabilities).all()
                or np.any(probabilities < 0) or np.any(probabilities > 1)
                or abs(probabilities.sum() - 1) > 1e-5):
            raise ValueError("invalid model probabilities")
        stage = self.contract.STAGES[int(probabilities.argmax())]
        return {"status": "ready", "probabilities": dict(zip(self.contract.STAGES, probabilities.tolist())),
                "info": {**self.info(), "stage": stage, "prediction_end_s": float(end_s)}}
