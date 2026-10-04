"""Research waveform inference using versioned training contracts.

All sessions physically capture 16 channels. Subset models quality-check only
selected electrodes; legacy cap8/cap16 retain their all-16-clean contract.
No missing-channel filling or spectral fallback is performed.
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


@lru_cache(maxsize=1)
def subset_training_code():
    path = Path(__file__).resolve().parents[1] / 'script' / 'train_sleep_subset_models.py'
    spec = importlib.util.spec_from_file_location('terry_subset_training_contract', path)
    if spec is None or spec.loader is None:
        raise WaveformModelError('waveform_model_contract_mismatch')
    module = importlib.util.module_from_spec(spec)
    import sys
    script_directory = str(path.parent)
    sys.path.insert(0, script_directory)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(script_directory)
    return module


@lru_cache(maxsize=1)
def frontal_training_code():
    path = Path(__file__).resolve().parents[1] / 'script' / 'train_sleep_frontal_models.py'
    spec = importlib.util.spec_from_file_location('terry_frontal_training_contract', path)
    if spec is None or spec.loader is None:
        raise WaveformModelError('waveform_model_contract_mismatch')
    module = importlib.util.module_from_spec(spec)
    import sys
    directory = str(path.parent)
    sys.path.insert(0, directory)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(directory)
    return module


def load_settings():
    try:
        path = Path(__file__).with_name("config.waveform.yaml")
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict) or settings.get("enabled") is not True:
            raise ValueError("waveform research inference must be explicitly enabled")
        for key in ('model_root', 'subset_model_root', 'frontal_model_root'):
            if key not in settings:
                continue
            root = Path(settings[key])
            if not root.is_absolute():
                root = path.parent / root
            settings[key] = root.resolve()
        confirmations = settings["confirmations_required"]
        minimum = settings["minimum_stage_probability"]
        if type(confirmations) is not int or confirmations < 1 or not 0.5 <= float(minimum) <= 1:
            raise ValueError("invalid classification gate")
        return settings
    except Exception as exc:
        raise WaveformModelError("waveform_model_configuration_error") from exc


class WaveformClassifier:
    def __init__(self, names, rate, count, *, model_root=None, predictor=None):
        legacy = training_code()
        self.count, self.rate = count, rate
        if tuple(names) != legacy.CAP16:
            raise WaveformModelError("waveform_requires_full_cap_capture")
        if count not in (2, 4, 6, 8, 16) or rate != legacy.RATE:
            raise WaveformModelError("waveform_model_contract_mismatch")
        self.subset = count in (2, 4, 6)
        self.contract = frontal_training_code() if self.subset else legacy
        self.selected_channels = tuple(self.contract.MONTAGES[count]) if self.subset else legacy.CAP16[:count]
        self.quality_channels = self.selected_channels if self.subset else legacy.CAP16
        self.indices = [legacy.CAP16.index(name) for name in self.quality_channels]
        self.pipeline = self.contract.pipeline_for(count) if self.subset else legacy.PIPELINE
        self.architecture = 'build_model:cap-waveform-frontal-v1' if self.subset else 'build_model:cap-waveform-v1'
        self.model = None
        self.predictor = predictor
        if predictor is None:
            key = 'frontal_model_root' if self.subset else 'model_root'
            root = model_root if model_root is not None else load_settings().get(key)
            if root is None:
                raise WaveformModelError('waveform_model_configuration_error')
            weight_path = Path(root) / f"cap{count}" / "best.pt"
            if not weight_path.is_file():
                raise WaveformModelError("waveform_model_missing")
            try:
                import torch
                checkpoint = torch.load(weight_path, map_location="cpu", weights_only=True)
                if (checkpoint.get("channels") != list(self.selected_channels)
                        or checkpoint.get("classes") != list(self.contract.STAGES)
                        or checkpoint.get("pipeline") != self.pipeline
                        or checkpoint.get("architecture") != self.architecture):
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
        self.buffer = np.empty((len(self.quality_channels), 0), dtype=float)
        self.last_end = None

    def info(self):
        return {"model": f"cap{self.count}", "experimental": True,
                "collected_seconds": self.buffer.shape[1] / self.rate,
                "required_seconds": 40, "classes": list(self.contract.STAGES),
                "hardware_validated": False, "probabilities_calibrated": False,
                "selected_channels": list(self.selected_channels),
                "quality_channels": list(self.quality_channels),
                "quality_scope": 'selected_channels' if self.subset else 'all_16_channels',
                "window_seconds": 30, "update_seconds": 6}

    def _quality_details(self, samples):
        details = []
        for name, values in zip(self.quality_channels, samples):
            finite = bool(np.isfinite(values).all())
            item = {'channel': name, 'reason': None, 'finite': finite}
            if not finite:
                item['reason'] = 'nonfinite'
            else:
                epoch = values[-30 * self.rate:]
                if len(epoch) >= 30 * self.rate:
                    flat = int((epoch.reshape(30, self.rate).std(axis=1) < .1).sum())
                    item['flat_seconds'] = flat
                    if flat > 2:
                        item['reason'] = 'flat_signal'
                if len(values) == 40 * self.rate:
                    from scipy.signal import butter, iirnotch, sosfilt, tf2sos
                    b, a = iirnotch(50, 30, fs=self.rate)
                    sos = np.concatenate((tf2sos(b, a), butter(4, [.5, 35], btype='bandpass', fs=self.rate, output='sos')))
                    filtered = sosfilt(sos, values)[-30 * self.rate:]
                    item['filtered_ptp_uv'] = float(np.ptp(filtered))
                    item['filtered_std_uv'] = float(filtered.std())
                    if item['reason'] is None:
                        if item['filtered_ptp_uv'] > 500:
                            item['reason'] = 'high_amplitude'
                        elif item['filtered_std_uv'] < .1:
                            item['reason'] = 'low_variation'
            details.append(item)
        return details

    def _invalid(self, reason, samples):
        details = self._quality_details(samples)
        self.reset()
        return {'status': 'invalid', 'reason': reason, 'probabilities': None,
                'info': {**self.info(), 'quality_reason': reason, 'reset_reason': reason,
                         'quality_details': details}}

    def update(self, samples_uv, end_s):
        samples = np.asarray(samples_uv, dtype=float)
        if samples.ndim != 2 or samples.shape[0] != 16 or samples.shape[1] == 0 or not math.isfinite(end_s):
            raise ValueError("invalid waveform chunk")
        samples = samples[self.indices]
        if self.last_end is not None and abs(end_s - self.last_end - samples.shape[1] / self.rate) > 1 / self.rate:
            self.reset()
        self.last_end = end_s
        if not np.isfinite(samples).all():
            return self._invalid('nonfinite', samples)
        self.buffer = np.concatenate((self.buffer, samples), axis=1)[:, -40 * self.rate:]
        if self.buffer.shape[1] < 40 * self.rate:
            return {"status": "waiting", "probabilities": None, "info": self.info()}
        processed, reason = (self.contract.preprocess_window(self.buffer, self.rate, self.count)
                             if self.subset else self.contract.preprocess_window(self.buffer, self.rate))
        if reason:
            return self._invalid(reason, self.buffer)
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
