from pathlib import Path

import numpy as np
from scipy.signal import butter, iirnotch, tf2sos

from channel_repair import repair_channels


def assess(samples):
    b, a = iirnotch(50, 30, fs=250)
    sos = np.concatenate([tf2sos(b, a), butter(4, [5, 50], fs=250, btype='bandpass', output='sos')])
    return repair_channels(samples, tuple(str(i) for i in range(16)), 500,
                           filter_sos=sos, sample_rate_hz=250)


def test_demo_repair_uses_actual_signal_pipeline_filter_contract():
    from anphy_sleep.config import load_config
    from anphy_sleep.contracts import EegChunk
    from anphy_sleep.streaming import SignalPipeline

    config, _ = load_config(Path(__file__).parents[1] / 'config.hardware.yaml')
    pipeline = SignalPipeline(config)
    np.testing.assert_array_equal(
        pipeline.filter_sos, np.concatenate([pipeline.notch_sos, pipeline.sos]))
    state_before = pipeline.filter_state.copy()
    t = np.arange(1500) / 250
    raw = np.vstack([20 * np.sin(2 * np.pi * (6 + i % 6) * t + i / 3) for i in range(16)])
    repaired, details = repair_channels(raw, pipeline.target_channels, 500,
                                       filter_sos=pipeline.filter_sos, sample_rate_hz=250)
    assert details['usable']
    # Quality assessment uses the same coefficients but must not advance the
    # causal filter state subsequently used by the real streaming pipeline.
    np.testing.assert_array_equal(pipeline.filter_state, state_before)
    windows = pipeline.push(EegChunk(timestamp_s=0, sample_rate_hz=250,
                                    channel_names=pipeline.target_channels,
                                    samples=repaired, unit='uV', session_id='demo-test'))
    assert windows and windows[0][0] == 6
    assert np.isfinite(windows[0][1]).all()


def test_mains_noise_is_assessed_after_filtering_without_mutating_model_input():
    t = np.arange(1500) / 250
    raw = np.tile(20 * np.sin(2 * np.pi * 10 * t) + 3000 * np.sin(2 * np.pi * 50 * t), (16, 1))
    repaired, details = assess(raw)
    assert details['usable']
    assert len(details['valid_channels']) == 16
    np.testing.assert_array_equal(repaired, raw)


def test_flat_nonfinite_and_plateau_channels_are_not_rescued_by_filter():
    t = np.arange(1500) / 250
    raw = np.tile(20 * np.sin(2 * np.pi * 10 * t), (16, 1))
    raw[0] = 187500
    raw[1, 100] = np.nan
    raw[2, :100] = 187500
    _, details = assess(raw)
    assert [c['reason'] for c in details['channels'][:3]] == ['flatline', 'nonfinite', 'repeated_plateau']


def test_large_in_band_artifacts_still_block_classification():
    t = np.arange(1500) / 250
    raw = np.tile(3000 * np.sin(2 * np.pi * 10 * t), (16, 1))
    repaired, details = assess(raw)
    assert repaired is None
    assert not details['usable']
