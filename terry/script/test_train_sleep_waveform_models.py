"""Training input-contract regressions; synthetic data only, no EDF/weights needed."""
import numpy as np
import pytest

import train_sleep_waveform_models as training


@pytest.mark.parametrize('label, expected', [
    ('EEG T5-Ref', 'P7'), ('T6', 'P8'), ('T3-Ref', 'T7'), ('T4', 'T8'),
    ('F4-', 'F4'), ('FZ', 'FZ'), ('CZ', 'CZ'),
])
def test_channel_aliases_preserve_physical_positions(label, expected):
    assert training.canonical(label) == expected


def test_channel_selection_reorders_names_not_source_indices():
    labels = list(reversed(training.CAP16))
    labels[labels.index('P7')] = 'T5-Ref'
    labels[labels.index('P8')] = 'T6-Ref'
    selected = training.channel_selection({'labels': labels, 'units': ['uV'] * 16})
    assert [training.canonical(name) for name in selected] == [name.upper() for name in training.CAP16]


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'wrong_unit'])
def test_channel_selection_rejects_ambiguous_or_wrong_unit_inputs(problem):
    info = {'labels': list(training.CAP16), 'units': ['uV'] * 16}
    if problem == 'missing':
        info['labels'][4] = 'Fz'
    elif problem == 'duplicate':
        info['labels'].append('T5-Ref')
        info['units'].append('uV')
    else:
        info['units'][4] = 'mV'
    with pytest.raises(ValueError):
        training.channel_selection(info)


def test_labels_keep_nonzero_start_and_do_not_relabel_deep_sleep(tmp_path):
    path = tmp_path / 'labels.txt'
    path.write_text('W 30 30\nN1 60 30\nN2 90 30\nN3 120 30\nREM 150 30\nL 180 30\n')
    rows = training.read_labels(path)
    assert rows[0] == ('W', 30.0, 30.0)
    assert [row[0] for row in rows] == ['W', 'N1', 'N2', 'N3', 'R', 'L']
    assert training.STAGES == ('W', 'N1', 'N2')


@pytest.mark.parametrize('text', [
    'W 0 30\nN1 20 30\n', 'W -30 30\n', 'W 0 20\n', 'W nan 30\n', 'unknown 0 30\n',
])
def test_invalid_annotations_are_rejected(tmp_path, text):
    path = tmp_path / 'labels.txt'
    path.write_text(text)
    with pytest.raises(ValueError):
        training.read_labels(path)


def test_subject_split_is_reproducible_disjoint_and_order_independent():
    subjects = [f'EPCTL{i:02}' for i in range(1, 29)]
    split = training.split_subjects(subjects, 42)
    assert split == training.split_subjects(list(reversed(subjects)), 42)
    assert {key: len(value) for key, value in split.items()} == {'train': 16, 'validation': 6, 'test': 6}
    flattened = [subject for group in split.values() for subject in group]
    assert len(flattened) == len(set(flattened)) == 28
    assert set(flattened) == set(subjects)
    with pytest.raises(ValueError):
        training.split_subjects(subjects + [subjects[0]], 42)


@pytest.mark.parametrize('count', [8, 16])
def test_model_input_references_only_selected_channels_without_mutating_cache(count):
    source = np.arange(16 * 100, dtype=np.float32).reshape(16, 100)
    original = source.copy()
    result = training.model_input(source, count)
    np.testing.assert_allclose(result, (source[:count] - source[:count].mean(axis=0)) / 100)
    np.testing.assert_allclose(result.mean(axis=0), 0, atol=1e-6)
    np.testing.assert_array_equal(source, original)
    assert not np.shares_memory(result, source)


def waveform(rate):
    t = np.arange(40 * rate) / rate
    return np.vstack([20 * np.sin(2 * np.pi * (6 + i % 6) * t + i / 3) for i in range(16)])


@pytest.mark.parametrize('rate', [250, 1000])
def test_preprocessing_returns_30_seconds_at_250_hz(rate):
    processed, reason = training.preprocess_window(waveform(rate), rate)
    assert reason is None
    assert processed.shape == (16, 7500)
    assert processed.dtype == np.float32
    assert np.isfinite(processed).all()


@pytest.mark.parametrize('problem', ['nonfinite', 'flat_signal', 'high_amplitude'])
def test_all_16_channels_must_pass_quality_checks(problem):
    data = waveform(250)
    if problem == 'nonfinite':
        data[15, -1] = np.nan
    elif problem == 'flat_signal':
        data[15, -750:] = 0
    else:
        data[15] *= 100
    _, reason = training.preprocess_window(data, 250)
    assert reason == problem
