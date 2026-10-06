"""LIVE backlog recovery must discard old EEG, never cancel or reuse classification."""
import numpy as np
from adaptive_web import AdaptiveWebService, _Session
from channel_mapping import CAP_ORDER


def test_live_queue_overflow_recollects_instead_of_permanently_blocking():
    events = []
    service = AdaptiveWebService(events.append)
    ctx = _Session(17, 'LIVE', 250, CAP_ORDER)
    service._session = ctx
    service._last = service._empty_event(17, 'LIVE')
    for i in range(33):
        start = i * 25
        service.submit(np.ones((16, 25)), start, 250, 17,
                       timestamps_s=np.arange(start, start + 25) / 250,
                       package_ids=np.arange(start, start + 25) % 256)
    assert not ctx.cancelled.is_set()
    assert service.status()['reason'] == 'recollecting_after_inference_backlog'
    assert service.status()['probabilities'] is None
    assert service.status()['classification_confirmed'] is False
    assert ctx.chunks.qsize() == 1
    assert ctx.chunks.get_nowait()[1] == 800


def test_live_worker_rebuilds_context_and_confirmations_after_overflow(monkeypatch):
    import waveform_classifier
    monkeypatch.setattr('adaptive_web.time.monotonic', lambda: 100.)
    real = waveform_classifier.WaveformClassifier
    monkeypatch.setattr(waveform_classifier, 'WaveformClassifier',
                        lambda names, rate, count, **kwargs: real(names, rate, count, predictor=lambda _: [.1, .1, .8]))
    events = []
    ctx = _Session(17, 'LIVE', 250, CAP_ORDER, classification_channels=8, music_source='ace')
    def capture(event):
        events.append(event)
        if event.get('timestamp_s', 0) >= 51.3:
            ctx.cancelled.set()
    service = AdaptiveWebService(capture)
    service._session = ctx
    service._last = service._empty_event(17, 'LIVE')
    for i in range(33):
        service.submit(np.ones((16, 25)), i * 25, 250, 17,
                       timestamps_s=np.arange(i * 25, (i + 1) * 25) / 250,
                       package_ids=np.arange(i * 25, (i + 1) * 25) % 256)
    for i in range(8):
        start = 825 + i * 1500
        t = np.arange(start, start + 1500) / 250
        data = np.vstack([20 * np.sin(2 * np.pi * (6 + j % 6) * t + j / 3) for j in range(16)])
        service.submit(data, start, 250, 17, timestamps_s=t,
                       package_ids=np.arange(start, start + 1500) % 256)
    service._process(ctx)
    assert any(e['reason'] == 'recollecting_after_inference_backlog' for e in events)
    predicted = [e for e in events if e.get('probabilities')]
    assert len(predicted) == 2
    assert predicted[0]['classification_confirmed']
    assert predicted[1]['classification_confirmed']
    assert predicted[1]['waveform_model']['collected_seconds'] == 40


def test_overflow_cannot_publish_inflight_confirmed_prediction():
    service = AdaptiveWebService(lambda _: None)
    ctx = _Session(17, 'LIVE', 250, CAP_ORDER)
    service._session = ctx
    service._last = service._empty_event(17, 'LIVE')
    ctx.live_queue_reset = True
    service._emit(ctx, status='ready', classification_confirmed=True, probabilities={'W': 1., 'N1': 0., 'N2': 0.})
    assert service.status()['classification_confirmed'] is False
    assert service.status()['probabilities'] is None


def test_demo_overflow_keeps_existing_explicit_restart_policy():
    service = AdaptiveWebService(lambda _: None)
    ctx = _Session(17, 'DEMO', 250, CAP_ORDER)
    service._session = ctx
    service._last = service._empty_event(17, 'DEMO')
    for i in range(33):
        service.submit(np.ones((16, 25)), i * 25, 250, 17)
    assert ctx.cancelled.is_set()
    assert service.status()['reason'] == 'inference_queue_overflow_restart_required'
