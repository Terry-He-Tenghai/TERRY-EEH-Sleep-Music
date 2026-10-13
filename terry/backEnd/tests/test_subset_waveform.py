"""Selected-montage LIVE regressions; no remote music requests."""
import numpy as np
import pytest

from channel_mapping import CAP_ORDER
from waveform_classifier import WaveformClassifier, frontal_training_code


def signal():
    t = np.arange(10000) / 250
    return np.vstack([20 * np.sin(2 * np.pi * (6 + i % 6) * t + i / 3) for i in range(16)])


@pytest.mark.parametrize('count', [2, 4, 6])
def test_unselected_bad_channels_do_not_block_selected_model(count):
    code = frontal_training_code()
    model = WaveformClassifier(CAP_ORDER, 250, count, predictor=lambda _: [.7, .2, .1])
    raw = signal()
    for index, name in enumerate(CAP_ORDER):
        if name not in model.source_channels:
            raw[index] = np.nan
    result = model.update(raw, 40)
    assert result['status'] == 'ready'
    assert result['info']['quality_channels'] == list(code.MONTAGES[count])
    assert model.buffer.shape == (count, 10000)


@pytest.mark.parametrize('count', [2, 4, 6])
@pytest.mark.parametrize('bad, reason', [(np.nan, 'nonfinite'), (0., 'flat_signal')])
def test_selected_bad_channel_is_reported_and_never_classified(count, bad, reason):
    model = WaveformClassifier(CAP_ORDER, 250, count, predictor=lambda _: pytest.fail('Bad EEG classified'))
    raw = signal()
    name = model.selected_channels[-1]
    raw[model.indices[-1]] = bad
    result = model.update(raw, 40)
    assert result['status'] == 'invalid'
    assert result['info']['quality_reason'] == reason
    assert any(d['channel'] == name and d['reason'] == reason for d in result['info']['quality_details'])
    assert result['info']['collected_seconds'] == (0 if reason == 'nonfinite' else 40)
    assert result['info']['buffer_retained'] is (reason != 'nonfinite')


@pytest.mark.parametrize('count', [2, 4, 6])
def test_selected_index_mapping_matches_training_preprocessing(count):
    seen = []
    code = frontal_training_code()
    model = WaveformClassifier(CAP_ORDER, 250, count, predictor=lambda x: seen.append(x.copy()) or [.7, .2, .1])
    data = signal()
    assert model.update(data, 40)['status'] == 'ready'
    selected = data[model.indices]
    filtered, reason = code.preprocess_window(selected, 250, count)
    assert reason is None
    np.testing.assert_array_equal(seen[0], code.model_input(filtered, count))


@pytest.mark.parametrize('count', [2, 4, 6, 8, 16])
def test_finite_bad_window_rolls_forward_without_restarting_40_seconds(count):
    calls = []
    model = WaveformClassifier(CAP_ORDER, 250, count, predictor=lambda x: calls.append(x) or [.7, .2, .1])
    raw = signal()
    index = CAP_ORDER.index(model.selected_channels[0])
    raw[index, 2500:3250] = 0  # Three flat seconds in the 30-second QC window.
    result = model.update(raw, 40)
    assert result['status'] == 'invalid'
    assert not calls
    assert result['info']['buffer_retained'] is True
    assert result['info']['reset_reason'] is None
    assert result['info']['collected_seconds'] == 40
    result = model.update(signal()[:, :1500], 46)
    assert result['status'] == 'ready'  # Bad seconds are now only past context.
    assert len(calls) == 1
    assert result['info']['collected_seconds'] == 40


def test_high_amplitude_diagnostics_do_not_approve_noisy_frontal_channel():
    model = WaveformClassifier(CAP_ORDER, 250, 2, predictor=lambda _: pytest.fail('Noisy EEG classified'))
    raw = signal()
    raw[CAP_ORDER.index('Fp1'), -2500:] += 400 * np.sin(2 * np.pi * 2 * np.arange(2500) / 250)
    result = model.update(raw, 40)
    assert result['status'] == 'invalid'
    assert result['info']['quality_reason'] == 'high_amplitude'
    fp1 = next(item for item in result['info']['quality_details'] if item['channel'] == 'Fp1')
    assert fp1['filtered_ptp_uv'] > 500
    assert fp1['largest_second_ptp_uv'] > 500
    assert 1 <= fp1['largest_second_from_end'] <= 10
    assert fp1['seconds_over_500uv'] > 0
    assert result['info']['buffer_retained'] is True


def test_old_central_checkpoint_cannot_be_loaded_as_frontal(tmp_path):
    import torch
    from waveform_classifier import WaveformModelError, subset_training_code
    old = subset_training_code()
    path = tmp_path / 'cap2'
    path.mkdir()
    torch.save({'architecture': 'build_model:cap-waveform-subset-v1',
                'channels': list(old.MONTAGES[2]), 'classes': ['W', 'N1', 'N2'],
                'pipeline': old.pipeline_for(2)}, path / 'best.pt')
    with pytest.raises(WaveformModelError, match='waveform_model_contract_mismatch'):
        WaveformClassifier(CAP_ORDER, 250, 2, model_root=tmp_path)


def test_original_fp1_fp2_checkpoint_loads_with_rewired_input(tmp_path):
    import torch
    code = frontal_training_code()
    pipeline = code.pipeline_for(2)
    pipeline['channels'] = ['Fp1', 'Fp2']
    pipeline['qc']['required_clean_channels'] = ['Fp1', 'Fp2']
    path = tmp_path / 'cap2'
    path.mkdir()
    torch.save({'architecture': code.ARCHITECTURE,
                'channels': ['Fp1', 'Fp2'], 'classes': list(code.STAGES),
                'pipeline': pipeline,
                'state_dict': code.build_model(torch, 2).state_dict()}, path / 'best.pt')
    model = WaveformClassifier(CAP_ORDER, 250, 2, model_root=tmp_path)
    assert model.indices == [0, 2]


@pytest.mark.parametrize('count, indices', [(2, [0, 2]), (4, [0, 2, 10, 11]),
                                         (6, [0, 2, 10, 11, 8, 9])])
def test_frontal_selection_reads_fp2_from_device_input_three(count, indices):
    model = WaveformClassifier(CAP_ORDER, 250, count, predictor=lambda _: [.7, .2, .1])
    assert model.selected_channels == frontal_training_code().MONTAGES[count]
    assert model.indices == indices
    raw = signal()
    raw[CAP_ORDER.index('Fp2')] = np.nan
    assert model.update(raw, 40)['status'] == 'ready'
    raw[CAP_ORDER.index('C3')] = 0
    result = model.update(raw, 80)
    assert result['status'] == 'invalid'
    assert result['info']['source_device_channels'] == [index + 1 for index in indices]
    assert any(d['channel'] == 'Fp2' and d['reason'] == 'flat_signal'
               for d in result['info']['quality_details'])


@pytest.mark.parametrize('count', [2, 4, 6])
def test_api_accepts_subset_count_and_full_capture_remains_16(count):
    from app import StartRequest, CAP_CHANNEL_NAMES
    request = StartRequest(mode='brainflow', classification_channels=count)
    assert request.classification_channels == count
    assert len(CAP_CHANNEL_NAMES) == 16


def test_alpha_theta_absolute_and_relative_welch_power():
    model = WaveformClassifier(CAP_ORDER, 250, 2, predictor=lambda _: [.7, .2, .1])
    t = np.arange(10000) / 250
    raw = np.tile(20 * np.sin(2 * np.pi * 10 * t) + 10 * np.sin(2 * np.pi * 6 * t), (16, 1))
    powers = model.update(raw, 40)['band_power_uv2']
    assert powers['relative_denominator_hz'] == [1, 30]
    np.testing.assert_allclose(powers['values']['alpha_8_12'], [200, 200], rtol=.01)
    np.testing.assert_allclose(powers['values']['theta'], [50, 50], rtol=.01)
    np.testing.assert_allclose(powers['relative']['alpha'], [.8, .8], rtol=.01)
    np.testing.assert_allclose(powers['relative']['theta'], [.2, .2], rtol=.01)


def test_zero_spectral_denominator_is_missing_not_zero(monkeypatch):
    from scipy import signal as scipy_signal
    model = WaveformClassifier(CAP_ORDER, 250, 2, predictor=lambda _: [.7, .2, .1])
    monkeypatch.setattr(scipy_signal, 'welch', lambda *a, **kw: (np.arange(126), np.zeros((2, 126))))
    relative = model.update(signal(), 40)['band_power_uv2']['relative']
    assert relative == {'alpha': [None, None], 'theta': [None, None]}
