"""LIVE waveform classification and ACE gating (no remote API calls)."""
import time

import numpy as np
import pytest

from adaptive_web import AdaptiveWebService, _Session
from channel_mapping import CAP_ORDER
from waveform_classifier import WaveformClassifier, ORIGIN
from ace_step import AutomaticMusic


def signal(start, seconds=6):
    t = np.arange(start, start + seconds * 250) / 250
    return np.vstack([20 * np.sin(2 * np.pi * (6 + i % 6) * t + i / 3) for i in range(16)])


def run_windows(monkeypatch, windows, count=8, broken_counter=False, *,
                missing_at=None, missing_samples=256, timestamp_transform=None):
    import waveform_classifier
    monkeypatch.setattr(waveform_classifier, 'WaveformClassifier',
                        lambda names, rate, count, **kwargs: WaveformClassifier(
                            names, rate, count, predictor=lambda x: [.05, .1, .85]))
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
        sample_positions = np.arange(start, start + 1500)
        if missing_at is not None:
            sample_positions = sample_positions + (sample_positions >= missing_at) * missing_samples
        counters = sample_positions % 256
        if broken_counter and i == 0:
            counters[25] = counters[24]
        timestamps = sample_positions / 250
        if timestamp_transform is not None:
            timestamps = timestamp_transform(timestamps)
        service.submit(window, start, 250, 17,
                       timestamps_s=timestamps, package_ids=counters)
    service._process(ctx)
    return events


@pytest.mark.parametrize('count', [8, 16])
def test_model_warmup_confirmation_and_cached_ace_audio(monkeypatch, count):
    events = run_windows(monkeypatch, [signal(i * 1500) for i in range(8)], count)
    assert all(e['probabilities'] is None for e in events if e['timestamp_s'] < 40)
    first = next(e for e in events if e.get('probabilities'))
    assert first['timestamp_s'] == 42
    assert first['classification_confirmed'] is False
    event = events[-1]
    assert event['timestamp_s'] == 48
    assert event['status'] == 'ready'
    assert event['classification_confirmed'] is True
    assert event['probability_origin'] == ORIGIN
    assert event['waveform_model']['model'] == f'cap{count}'
    assert len(event['channel_repair']['used_channels']) == count
    assert event['target_music_state'] == 'M3'
    automatic = AutomaticMusic()
    automatic.start(17, 'ambient')
    automatic.cached['M3'] = '/api/ace/generations/test_audio/audio'
    automatic.consider(first)
    assert automatic.status()['status'] == 'paused'
    automatic.consider(event)
    assert automatic.status()['status'] == 'ready'
    automatic.consider({**event, 'status': 'frozen', 'state': None, 'probabilities': None})
    assert automatic.status()['status'] == 'paused'


@pytest.mark.parametrize('count', [8, 16])
def test_single_electrode_is_not_a_valid_model_input(monkeypatch, count):
    data = np.full((16, 1500), np.nan)
    data[2] = signal(0)[2]
    event = run_windows(monkeypatch, [data], count)[-1]
    assert event['status'] == 'frozen'
    assert event['probabilities'] is None
    assert event['classification_confirmed'] is False
    automatic = AutomaticMusic()
    automatic.start(17, 'piano')
    automatic.consider(event)
    assert automatic.worker is None


def test_packet_gap_discards_context_then_collects_new_full_window(monkeypatch):
    events = run_windows(monkeypatch, [signal(i * 1500) for i in range(9)], broken_counter=True)
    assert any(e['reason'] == 'recollecting_after_packet_gap' for e in events)
    assert all(e['probabilities'] is None for e in events if e['timestamp_s'] < 48)
    assert events[-1]['classification_confirmed'] is True
    assert events[-1]['timestamp_s'] == 54


@pytest.mark.parametrize('count', [8, 16])
@pytest.mark.parametrize('missing_at', [12000, 12750])
@pytest.mark.parametrize('missing_samples', [256, 512])
def test_full_counter_cycle_loss_revokes_ace_until_new_context_and_confirmation(
        monkeypatch, count, missing_at, missing_samples):
    events = run_windows(monkeypatch, [signal(i * 1500) for i in range(17)], count,
                         missing_at=missing_at, missing_samples=missing_samples)
    assert any(e['classification_confirmed'] for e in events if e['timestamp_s'] == 48)
    gap = next((e for e in events if e['reason'] == 'recollecting_after_packet_gap'), None)
    assert gap is not None, 'Counter wrap must not hide missing physical samples'
    assert gap['timestamp_s'] == 54
    assert gap['waveform_model']['collected_seconds'] == 0
    assert all(e['probabilities'] is None for e in events if 54 <= e['timestamp_s'] < 96)
    first = next(e for e in events if e['timestamp_s'] >= 54 and e['probabilities'])
    assert first['timestamp_s'] == 96
    assert first['classification_confirmed'] is False
    assert events[-1]['timestamp_s'] == 102
    assert events[-1]['classification_confirmed'] is True

    automatic = AutomaticMusic()
    automatic.start(17, 'ambient')
    automatic.cached['M3'] = '/api/ace/generations/test_audio/audio'
    for event in events:
        automatic.consider(event)
        if 54 <= event['timestamp_s'] < 102:
            assert automatic.status()['status'] == 'paused'
            assert automatic.status()['audio_url'] is None
    assert automatic.status()['status'] == 'ready'


@pytest.mark.parametrize('count', [8, 16])
def test_batched_hardware_timestamps_and_small_clock_drift_remain_usable(monkeypatch, count):
    # Repeated timestamps within a 100 ms transport batch are not missing EEG.
    events = run_windows(monkeypatch, [signal(i * 1500) for i in range(8)], count,
                         timestamp_transform=lambda t: 1_700_000_000 + np.floor(t * 10) / 10 * 1.001)
    assert not any(e['reason'] == 'recollecting_after_packet_gap' for e in events)
    assert events[-1]['classification_confirmed'] is True


def test_interpolated_timestamp_gap_cannot_hide_a_counter_cycle(monkeypatch):
    # Some transports spread their timestamp correction across a batch. No
    # adjacent timestamp here jumps by 0.5 s, but 256 physical samples are lost.
    def interpolate_gap(timestamps):
        logical = timestamps - (timestamps >= 48 + 256 / 250) * (256 / 250)
        return logical + np.clip((logical - 48) / 6, 0, 1) * (256 / 250)

    events = run_windows(monkeypatch, [signal(i * 1500) for i in range(10)],
                         missing_at=12000, timestamp_transform=interpolate_gap)
    assert any(e['reason'] == 'recollecting_after_packet_gap' for e in events)
    assert all(e['probabilities'] is None for e in events if e['timestamp_s'] >= 54)


def test_timestamp_drift_is_checked_over_bounded_history(monkeypatch):
    events = run_windows(monkeypatch, [signal(i * 1500) for i in range(24)],
                         timestamp_transform=lambda t: 1_700_000_000 + t * 1.005)
    assert not any(e['reason'] == 'recollecting_after_packet_gap' for e in events)
    assert events[-1]['classification_confirmed'] is True


def test_frozen_timestamps_cannot_produce_a_classification(monkeypatch):
    events = run_windows(monkeypatch, [signal(i * 1500) for i in range(8)],
                         timestamp_transform=lambda t: np.full_like(t, 1_700_000_000))
    assert any(e['reason'] == 'recollecting_after_packet_gap' for e in events)
    assert all(e['probabilities'] is None for e in events)


def test_valid_classification_submits_ace_generation_and_reuses_audio(monkeypatch):
    import ace_step as ace
    event = run_windows(monkeypatch, [signal(i * 1500) for i in range(8)])[-1]
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
    automatic.consider(event)
    assert len(calls) == 1
    automatic.consider({**event, 'emitted_at_s': time.time() - 16})
    assert automatic.status()['status'] == 'paused'
