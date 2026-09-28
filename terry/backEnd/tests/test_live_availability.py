"""Availability-first EEG feedback through the automatic ACE music gate."""
import time

import numpy as np
import pytest

from adaptive_web import AdaptiveWebService, _Session
from channel_mapping import CAP_ORDER
from degraded_classifier import classify_window
from ace_step import AutomaticMusic


def run_windows(windows, count=8, broken_counter=False):
    ctx = _Session(17, 'LIVE', 250, CAP_ORDER, classification_channels=count, music_source='ace')
    events = []
    def capture(event):
        events.append(event)
        if event.get('timestamp_s', 0) >= len(windows) * 6:
            ctx.cancelled.set()
    service = AdaptiveWebService(capture)
    service._session = ctx
    service._last = service._empty_event(17, 'LIVE')
    for i, window in enumerate(windows):
        start = i * 1500
        counters = np.arange(start, start + 1500) % 256
        if broken_counter and i == 0:
            counters[25] = counters[24]
        service.submit(window, start, 250, 17,
                       timestamps_s=np.arange(start, start + 1500) / 250,
                       package_ids=counters)
    service._process(ctx)
    return events


def signal(amplitude=20):
    return amplitude * np.sin(2 * np.pi * 10 * np.arange(1500) / 250)


@pytest.mark.parametrize('count', [8, 16])
@pytest.mark.parametrize('kind', ['clean', 'large', 'missing', 'tiny'])
def test_one_channel_produces_classification_and_ace_audio(count, kind):
    data = np.full((16, 1500), np.nan)
    # C3 is available in both selected montages; all other electrodes are missing.
    data[2] = signal(2000 if kind == 'large' else .01 if kind == 'tiny' else 20)
    if kind == 'missing':
        data[2, 300:600] = np.nan
    event = run_windows([data], count)[-1]
    assert event['status'] == 'ready'
    assert event['channel_repair']['used_channels'] == ['C3']
    assert event['channel_repair']['quality_warning'] == (kind != 'clean')
    assert sum(event['probabilities'].values()) == pytest.approx(1)
    assert all(np.isfinite(list(event['probabilities'].values())))
    automatic = AutomaticMusic()
    automatic.start(17, 'ambient')
    automatic.cached[event['target_music_state']] = '/api/ace/generations/test_audio/audio'
    automatic.consider(event)
    assert automatic.status()['status'] == 'ready'
    assert automatic.status()['audio_url']
    automatic.consider({**event, 'status': 'frozen', 'state': None, 'probabilities': None})
    assert automatic.status()['status'] == 'paused'
    automatic.stop()


@pytest.mark.parametrize('value', [0., 123456., np.nan, np.inf])
def test_no_signal_then_recovery(value):
    bad = np.full((16, 1500), value)
    good = bad.copy()
    good[0] = signal()
    events = run_windows([bad, good])
    empty = next(e for e in events if e['reason'] == 'no_valid_electrodes')
    assert empty['probabilities'] is None
    assert empty['playback_mode'] == 'silent'
    assert events[-1]['state']['status'] == 'ok'
    with pytest.raises(ValueError):
        classify_window(bad, 250)


def test_single_channel_submits_ace_generation_and_gets_audio(monkeypatch):
    import ace_step as ace

    data = np.zeros((16, 1500))
    data[0] = signal(2000)
    event = run_windows([data])[-1]
    calls = []
    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def is_alive(self):
            return False
        def start(self):
            self.target(*self.args)
    def generate(request):
        calls.append(request)
        return {'task_id': 'test_task_0001'}
    monkeypatch.setattr(ace.threading, 'Thread', InlineThread)
    monkeypatch.setattr(ace, 'generate', generate)
    monkeypatch.setattr(ace, 'generation', lambda task: {
        'status': 'completed', 'audio_url': '/api/ace/generations/test_task_0001/audio'})
    automatic = AutomaticMusic()
    automatic.start(17, 'piano')
    automatic.last_submit = -1000
    automatic.consider(event)
    assert len(calls) == 1
    assert calls[0].style == 'piano'
    assert automatic.status()['status'] == 'ready'
    assert automatic.status()['audio_url'].endswith('/audio')
    automatic.consider(event)
    assert len(calls) == 1  # unchanged music state reuses generated audio
    automatic.stop()


def test_pretrained_target_reaches_ace_without_relabeling_probabilities(monkeypatch):
    from pretrained_classifier import PretrainedClassifier
    model_result = {'status': 'ready', 'stage': 'REM', 'music_target': 'M2',
                    'probabilities': {'W': .05, 'N1': .05, 'N2': .05, 'N3': .05, 'REM': .8}}
    monkeypatch.setattr(PretrainedClassifier, 'update', lambda *args: model_result)
    data = np.zeros((16, 1500))
    data[2] = signal()
    event = run_windows([data])[-1]
    assert event['target_music_state'] == 'M2'
    assert event['music_control_origin'] == 'yasa_rolling_unvalidated'
    assert event['pretrained']['probabilities']['REM'] == .8
    assert set(event['probabilities']) == {'W', 'N1', 'N2'}
    automatic = AutomaticMusic()
    automatic.start(17, 'ambient')
    automatic.cached['M2'] = '/api/ace/generations/test/audio'
    automatic.consider(event)
    assert automatic.status()['music_state'] == 'M2'
    automatic.stop()


def test_packet_loss_discards_window_then_recovers_without_restart():
    data = np.zeros((16, 1500))
    data[0] = signal()
    events = run_windows([data, data], broken_counter=True)
    assert any(e['reason'] == 'recollecting_after_packet_gap' and e['probabilities'] is None for e in events)
    assert events[-1]['state']['status'] == 'ok'
    assert events[-1]['timestamp_s'] == 12
