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
        if name not in code.MONTAGES[count]:
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
    raw[CAP_ORDER.index(name)] = bad
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
    selected = data[[CAP_ORDER.index(name) for name in code.MONTAGES[count]]]
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


@pytest.mark.parametrize('count', [2, 4, 6])
def test_api_accepts_subset_count_and_full_capture_remains_16(count):
    from app import StartRequest, CAP_CHANNEL_NAMES
    request = StartRequest(mode='brainflow', classification_channels=count)
    assert request.classification_channels == count
    assert len(CAP_CHANNEL_NAMES) == 16
