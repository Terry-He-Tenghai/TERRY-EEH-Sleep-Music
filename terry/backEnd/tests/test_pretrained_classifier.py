from concurrent.futures import Future
import numpy as np
import pytest
from pretrained_classifier import PretrainedClassifier

CONFIG = {'enabled': True, 'channel_map_confirmed': True, 'reference': 'M2'}

class Inline:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future


def fake(samples, rate, channel):
    assert channel == 'C3'
    assert rate == 250
    assert len(samples) >= 75000
    return {'stage': 'N3', 'probabilities': {'W': .1, 'N1': .1, 'N2': .1, 'N3': .6, 'REM': .1}, 'music_target': 'M3'}


@pytest.mark.parametrize('config,reason', [
    ({**CONFIG, 'channel_map_confirmed': False}, 'channel_map_unconfirmed'),
    ({**CONFIG, 'reference': 'average'}, 'reference_unconfirmed_or_unsupported'),
    ({**CONFIG, 'reference': 'unknown'}, 'reference_unconfirmed_or_unsupported'),
])
def test_unmatched_signal_never_calls_model(config, reason):
    def forbidden(*args):
        pytest.fail('Model must not run on unconfirmed montage')
    model = PretrainedClassifier(('C3',), 250, config, forbidden, Inline())
    result = model.update(np.ones((1, 1500)), 6, {'C3'})
    assert result['reason'] == reason
    assert result['probabilities'] is None


def test_reference_requires_corresponding_real_central_electrode():
    model = PretrainedClassifier(('C3',), 250, {**CONFIG, 'reference': 'M1'}, fake, Inline())
    assert model.update(np.ones((1, 1500)), 6, {'C3'})['reason'] == 'matching_clean_central_channel_missing'


def test_warmup_full_five_stage_output_and_gap_reset():
    model = PretrainedClassifier(('C3',), 250, CONFIG, fake, Inline())
    window = np.ones((1, 1500))
    for end in range(6, 300, 6):
        assert model.update(window, end, {'C3'})['reason'] == 'warming_up_300_seconds'
    assert model.update(window, 300, {'C3'})['status'] == 'fallback'
    result = model.update(window, 306, {'C3'})
    assert result['status'] == 'ready'
    assert result['stage'] == 'N3'
    assert result['probabilities']['N2'] == .1
    assert result['window_end_s'] == 300
    assert model.update(window, 330, {'C3'})['reason'] == 'warming_up_300_seconds'
    assert model.update(window, 336, set())['status'] == 'fallback'


def test_model_error_preserves_fallback():
    def broken(*args):
        raise RuntimeError('weights unavailable')
    model = PretrainedClassifier(('C3',), 250, CONFIG, broken, Inline())
    model.update(np.ones((1, 75000)), 300, {'C3'})
    result = model.update(np.ones((1, 1500)), 306, {'C3'})
    assert result['status'] == 'fallback'
    assert result['reason'] == 'model_load_or_prediction_failed'


def test_old_inflight_result_not_used_after_reset():
    class Pending:
        def submit(self, *args):
            self.future = Future()
            self.future.set_running_or_notify_cancel()
            return self.future
    executor = Pending()
    model = PretrainedClassifier(('C3',), 250, CONFIG, fake, executor)
    model.update(np.ones((1, 75000)), 300, {'C3'})
    model.reset()
    executor.future.set_result(fake(np.ones(75000), 250, 'C3'))
    result = model.update(np.ones((1, 1500)), 306, {'C3'})
    assert result['status'] == 'fallback'
    assert result['probabilities'] is None
