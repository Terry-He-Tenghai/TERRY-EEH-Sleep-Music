"""Selected-montage LIVE regressions; no remote music requests."""
import numpy as np
import pytest

from channel_mapping import CAP_ORDER
from waveform_classifier import WaveformClassifier, subset_training_code


def signal():
    t = np.arange(10000) / 250
    return np.vstack([20 * np.sin(2 * np.pi * (6 + i % 6) * t + i / 3) for i in range(16)])


@pytest.mark.parametrize('count', [2, 4, 6])
def test_unselected_bad_channels_do_not_block_selected_model(count):
    code = subset_training_code()
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
    assert result['info']['collected_seconds'] == 0


@pytest.mark.parametrize('count', [2, 4, 6])
def test_selected_index_mapping_matches_training_preprocessing(count):
    seen = []
    code = subset_training_code()
    model = WaveformClassifier(CAP_ORDER, 250, count, predictor=lambda x: seen.append(x.copy()) or [.7, .2, .1])
    data = signal()
    assert model.update(data, 40)['status'] == 'ready'
    selected = data[[CAP_ORDER.index(name) for name in code.MONTAGES[count]]]
    filtered, reason = code.preprocess_window(selected, 250, count)
    assert reason is None
    np.testing.assert_array_equal(seen[0], code.model_input(filtered, count))


@pytest.mark.parametrize('count', [2, 4, 6])
def test_api_accepts_subset_count_and_full_capture_remains_16(count):
    from app import StartRequest, CAP_CHANNEL_NAMES
    request = StartRequest(mode='brainflow', classification_channels=count)
    assert request.classification_channels == count
    assert len(CAP_CHANNEL_NAMES) == 16
