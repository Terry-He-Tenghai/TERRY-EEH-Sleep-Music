"""Preprocessing parity and real trained weights for live inference."""
from pathlib import Path

import numpy as np
import pytest

from channel_mapping import CAP_ORDER
from waveform_classifier import WaveformClassifier, WaveformModelError, training_code


def signal(seconds=40):
    t = np.arange(seconds * 250) / 250
    return np.vstack([20 * np.sin(2 * np.pi * (6 + i % 6) * t + i / 3) for i in range(16)])


@pytest.mark.parametrize('count', [8, 16])
def test_preprocessing_is_exactly_the_training_preprocessing(count):
    seen = []
    model = WaveformClassifier(CAP_ORDER, 250, count, predictor=lambda x: seen.append(x.copy()) or [.7, .2, .1])
    data = signal()
    assert model.update(data[:, :7500], 30)['status'] == 'waiting'
    result = model.update(data[:, 7500:], 40)
    assert result['status'] == 'ready'
    code = training_code()
    filtered, reason = code.preprocess_window(data, 250)
    assert reason is None
    np.testing.assert_array_equal(seen[0], code.model_input(filtered, count))
    assert result['info']['stage'] == 'W'
    assert result['info']['prediction_end_s'] == 40


@pytest.mark.parametrize('count', [8, 16])
def test_real_weights_load_and_return_normalized_probabilities(count):
    root = Path(__file__).resolve().parents[2] / 'results' / 'waveform_cap_v1'
    if not (root / f'cap{count}' / 'best.pt').exists():
        pytest.skip('Local research weights not present')
    model = WaveformClassifier(CAP_ORDER, 250, count, model_root=root)
    result = model.update(signal(), 40)
    assert result['status'] == 'ready'
    assert set(result['probabilities']) == {'W', 'N1', 'N2'}
    assert sum(result['probabilities'].values()) == pytest.approx(1)
    assert result['info']['hardware_validated'] is False


def test_discontinuous_samples_reset_the_context():
    model = WaveformClassifier(CAP_ORDER, 250, 8, predictor=lambda x: [.7, .2, .1])
    model.update(signal(30), 30)
    result = model.update(signal(10), 50)  # Ten-second gap: not 40 seconds of continuous data.
    assert result['status'] == 'waiting'
    assert result['info']['collected_seconds'] == 10


@pytest.mark.parametrize('bad', [np.nan, np.inf, 0.0])
def test_invalid_signal_never_invokes_predictor(bad):
    model = WaveformClassifier(CAP_ORDER, 250, 8, predictor=lambda _: pytest.fail('Invalid EEG reached CNN'))
    result = model.update(np.full((16, 10000), bad), 40)
    assert result['status'] == 'invalid'
    assert result['probabilities'] is None
    assert result['info']['collected_seconds'] == (40 if bad == 0.0 else 0)


def test_missing_weights_and_incompatible_acquisition_are_explicit(tmp_path):
    with pytest.raises(WaveformModelError, match='waveform_model_missing'):
        WaveformClassifier(CAP_ORDER, 250, 8, model_root=tmp_path)
    with pytest.raises(WaveformModelError, match='waveform_requires_full_cap_capture'):
        WaveformClassifier(CAP_ORDER[:8], 250, 8, predictor=lambda _: [.7, .2, .1])
    with pytest.raises(WaveformModelError, match='waveform_model_contract_mismatch'):
        WaveformClassifier(CAP_ORDER, 500, 16, predictor=lambda _: [.7, .2, .1])


def test_checkpoint_montage_mismatch_cannot_load(tmp_path):
    import torch
    code = training_code()
    directory = tmp_path / 'cap8'
    directory.mkdir()
    torch.save({'channels': list(code.CAP16), 'classes': list(code.STAGES), 'pipeline': code.PIPELINE,
                'architecture': 'build_model:cap-waveform-v1'}, directory / 'best.pt')
    with pytest.raises(WaveformModelError, match='waveform_model_contract_mismatch'):
        WaveformClassifier(CAP_ORDER, 250, 8, model_root=tmp_path)
