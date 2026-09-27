"""Explicit scripted demo contract: synthetic samples, never model predictions."""
import importlib.util
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

spec = importlib.util.spec_from_file_location('terry_showcase_test_app', Path(__file__).parents[1] / 'app.py')
web = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = web
spec.loader.exec_module(web)


def test_showcase_profile_is_explicit_validated_and_model_remains_default():
    assert web.StartRequest().demo_profile == 'model'
    assert web.StartRequest(demo_profile='showcase').demo_profile == 'showcase'
    assert web.StartRequest(mode='brainflow').demo_profile == 'model'
    for fields in [dict(demo_profile='unknown'), dict(demo_profile=True),
                   dict(mode='brainflow', demo_profile='showcase'),
                   dict(sample_rate_hz=500, demo_profile='showcase'),
                   dict(sample_rate_hz=1000, demo_profile='showcase')]:
        with pytest.raises(ValidationError):
            web.StartRequest(**fields)


def test_showcase_queued_worker_cycles_without_models(tmp_path, monkeypatch):
    import threading
    import numpy as np
    from anphy_sleep.config import load_config
    import anphy_sleep.config
    from adaptive_web import AdaptiveWebService, ROOT
    import babyslakh

    config, root = load_config(ROOT / 'config.hardware.yaml')
    config['data']['results_dir'] = str(tmp_path / 'no-models')
    monkeypatch.setattr(anphy_sleep.config, 'load_config', lambda path: (config, root))
    monkeypatch.setattr(babyslakh, 'get_track', lambda track: {'id': track, 'title': track})
    events, acknowledged = [], threading.Event()
    def publish(event):
        events.append(event)
        if event['status'] in ('ready', 'blocked', 'error', 'stopped'):
            acknowledged.set()
    service = AdaptiveWebService(publish)
    generation = service.start('demo', 250, web.CHANNEL_NAMES,
                               stem_track_id='Track00008', demo_profile='showcase')
    try:
        for index in range(33):
            acknowledged.clear()
            service.submit(np.ones((16, 750)), index * 750, 250, generation)
            assert acknowledged.wait(3), service.status()
            assert service.status()['status'] == 'ready', service.status()
        ready = [event for event in events if event['status'] == 'ready']
        assert [event['timestamp_s'] for event in ready] == list(range(3, 100, 3))
        stages = {event['timestamp_s']: event for event in ready}
        for elapsed, stage, music, probabilities in [
            (3, 'W', 'M1', {'W': .94, 'N1': .04, 'N2': .02}),
            (24, 'N1', 'M2', {'W': .08, 'N1': .86, 'N2': .06}),
            (48, 'N2', 'M3', {'W': .02, 'N1': .08, 'N2': .90}),
            (72, 'W', 'M1', {'W': .94, 'N1': .04, 'N2': .02}),
            (96, 'W', 'M1', {'W': .94, 'N1': .04, 'N2': .02}),
        ]:
            event = stages[elapsed]
            assert event['source'] == 'DEMO'
            assert event['demo_stage'] == stage and event['demo_elapsed_s'] == elapsed
            assert event['current_music_state'] == event['target_music_state'] == music
            assert event['probabilities'] == probabilities
            assert event['playback_mode'] == event['inference_mode'] == 'demo_scripted'
            assert event['demo_scripted'] is True
            assert event['probability_origin'] == 'scripted_not_model'
            assert event['state']['status'] == 'demo_scripted'
            assert event['state']['baseline_ready'] is False
            assert event['state']['n2_within_5m_probability'] is None
            assert event['signal_quality'] == 1
            assert event['signal_quality_scope'] == 'synthetic_sample_validity_only'
            assert event['bpm'] == 60 and event['phrase_beats'] == 16
            assert event['planned_only'] is True and event['playback_started'] is False
            assert event['stem_mix']['mode'] == 'demo_scripted'
        awake, n1, n2 = (stages[t] for t in (3, 24, 48))
        assert awake['modulation']['control_level'] > n1['modulation']['control_level'] > n2['modulation']['control_level']
        assert awake['stem_mix']['gains']['piano'] > n1['stem_mix']['gains']['piano'] > n2['stem_mix']['gains']['piano']
        assert awake['stem_mix']['gains']['pad'] < n1['stem_mix']['gains']['pad'] < n2['stem_mix']['gains']['pad']
        assert n2['gains']['melody'] == n2['gains']['bass'] == 0
        assert awake['notes'] != n1['notes'] != n2['notes']
    finally:
        service.stop(generation)
    assert service.status()['status'] == 'stopped'
    assert service.status()['stem_mix'] is None
    count = len(events)
    service.submit(np.ones((16, 750)), 24750, 250, generation)
    assert len(events) == count


@pytest.fixture
def queued_showcase(monkeypatch):
    """Public start/submit, with synchronous worker dispatch and virtual time."""
    import time
    from types import SimpleNamespace
    import adaptive_web

    clock = SimpleNamespace(now=100.)
    monkeypatch.setattr(adaptive_web, 'time', SimpleNamespace(monotonic=lambda: clock.now, time=time.time))
    monkeypatch.setattr(adaptive_web.threading.Thread, 'start', lambda self: None)
    events = []
    service = adaptive_web.AdaptiveWebService(events.append)
    generation = service.start('demo', 250, web.CHANNEL_NAMES, demo_profile='showcase')
    ctx = service._session
    ctx.started_at = clock.now
    return service, ctx, clock, events, generation


@pytest.mark.parametrize('case,reason', [
    ('rate', 'sample_discontinuity_restart_required'),
    ('offset', 'sample_discontinuity_restart_required'),
    ('channels', 'invalid_channel_count_restart_required'),
    ('nan', 'nonfinite_synthetic_samples_restart_required'),
    ('inf', 'nonfinite_synthetic_samples_restart_required'),
    ('oversized', 'invalid_or_oversized_chunk_restart_required'),
    ('empty', 'invalid_or_oversized_chunk_restart_required'),
    ('timestamps', 'invalid_hardware_timestamps_restart_required'),
    ('reversed_clock', 'hardware_timestamp_discontinuity_restart_required'),
    ('backlog', 'inference_backlog_restart_required'),
])
def test_showcase_rejects_invalid_samples(queued_showcase, case, reason):
    import numpy as np
    service, ctx, clock, events, generation = queued_showcase
    samples = np.ones((15 if case == 'channels' else 16,
                       2501 if case == 'oversized' else 0 if case == 'empty' else 750))
    if case in ('nan', 'inf'):
        samples[0, 0] = float(case)
    timestamps = None
    if case == 'timestamps':
        timestamps = np.ones(2)
    elif case == 'reversed_clock':
        timestamps = np.arange(750)[::-1] / 250
    service.submit(samples, 1 if case == 'offset' else 0, 500 if case == 'rate' else 250,
                   generation, timestamps_s=timestamps)
    if case == 'backlog':
        clock.now += 4
    service._process(ctx)
    assert service.status()['reason'] == reason
    assert ctx.cancelled.is_set()
    assert not any(event['status'] == 'ready' for event in events)


@pytest.mark.parametrize('has_samples', [False, True])
def test_showcase_first_sample_and_stale_timeouts(queued_showcase, monkeypatch, has_samples):
    import queue
    import numpy as np
    service, ctx, clock, events, generation = queued_showcase
    if has_samples:
        service.submit(np.ones((16, 750)), 0, 250, generation)
    # Retain the real queue operation for prequeued samples.
    original_get = ctx.chunks.get
    def scripted_get(block=True, timeout=None):
        if not ctx.chunks.empty():
            return original_get(block=False)
        clock.now += 31 if not has_samples else 3
        raise queue.Empty
    monkeypatch.setattr(ctx.chunks, 'get', scripted_get)
    service._process(ctx)
    assert service.status()['reason'] == ('acquisition_stale_restart_required' if has_samples else 'first_sample_timeout_restart_required')
    assert ctx.cancelled.is_set()
    assert service.status()['playback_mode'] == 'silent'
    assert service.status()['probabilities'] is None
    assert sum(event['status'] == 'ready' for event in events) == int(has_samples)


def test_showcase_first_update_waits_for_three_seconds_and_emits_every_boundary(queued_showcase):
    import numpy as np
    service, ctx, clock, events, generation = queued_showcase
    service.submit(np.ones((16, 749)), 0, 250, generation)
    service.submit(np.ones((16, 1501)), 749, 250, generation)
    original = service._publish
    def publish(event):
        original(event)
        if event['timestamp_s'] == 9:
            service.stop(generation)
    service._publish = publish
    service._process(ctx)
    assert [e['timestamp_s'] for e in events if e['status'] == 'ready'] == [3, 6, 9]
    assert service.status()['status'] == 'stopped'
    assert service.status()['plan_updated'] is False
    assert service.status()['notes'] == []


@pytest.mark.parametrize('stop_during_plan', [False, True])
def test_showcase_discards_late_or_cancelled_results(queued_showcase, monkeypatch, stop_during_plan):
    import numpy as np
    service, ctx, clock, events, generation = queued_showcase
    service.submit(np.ones((16, 750)), 0, 250, generation)
    def track(state, context):
        if stop_during_plan:
            service.stop(generation)
        else:
            clock.now += 2.1
        return None, 'no_available_track_for_state'
    monkeypatch.setattr(service, '_track', track)
    service._process(ctx)
    assert not any(event['status'] == 'ready' for event in events)
    assert service.status()['reason'] == ('acquisition_stopped' if stop_during_plan else 'inference_result_stale_restart_required')


def test_acquisition_forwards_explicit_profile(monkeypatch):
    service = web.AcquisitionService()
    calls = []
    monkeypatch.setattr(service._adaptive, 'start', lambda *args, **kwargs: calls.append(kwargs) or 1)
    monkeypatch.setattr(web.threading.Thread, 'start', lambda self: None)
    service.start(web.StartRequest(demo_profile='showcase'))
    assert calls[0]['demo_profile'] == 'showcase'


@pytest.mark.parametrize('fields', [dict(source='LIVE'), dict(source=None),
    dict(inference_mode='standard'), dict(demo_scripted=False), dict(demo_scripted=1),
    dict(probability_origin='model'), dict(probability_origin=None)])
def test_scripted_stem_mix_requires_explicit_demo_provenance(fields):
    from babyslakh import project_stem_mix
    event = dict(status='ready', track_status='available', playback_mode='demo_scripted',
                 source='DEMO', inference_mode='demo_scripted', demo_scripted=True,
                 probability_origin='scripted_not_model', modulation={'control_level': .7})
    valid = project_stem_mix('Track00008', event)
    assert valid['mode'] == 'demo_scripted'
    adaptive = project_stem_mix('Track00008', {**event, 'playback_mode': 'adaptive'})
    assert valid['gains'] == adaptive['gains']
    assert project_stem_mix('Track00008', {**event, **fields}) is None


def test_showcase_waveform_follows_same_bounded_stage_clock():
    import numpy as np
    from demo_showcase import showcase_waveform, showcase_stage
    assert [showcase_stage(t) for t in (0, 23.999, 24, 48, 72, 96, 120)] == ['W', 'W', 'N1', 'N2', 'W', 'W', 'N1']
    powers = []
    for start in (0, 24, 48):
        times = start + np.arange(500) / 250
        data = showcase_waveform(times, 0, 0)
        assert np.isfinite(data).all() and abs(data).max() < 35
        spectrum = abs(np.fft.rfft(data))
        frequencies = np.fft.rfftfreq(len(data), 1/250)
        powers.append((spectrum[(frequencies >= 8) & (frequencies <= 12)].sum(),
                       spectrum[(frequencies >= 4) & (frequencies < 8)].sum(),
                       spectrum[(frequencies >= .5) & (frequencies < 4)].sum()))
    assert powers[0][0] > powers[1][0] > powers[2][0]
    assert powers[1][1] > powers[0][1]
    assert powers[2][2] > powers[1][2] > powers[0][2]


@pytest.mark.parametrize('case,reason', [
    ('first_late', 'first_sample_timeout_restart_required'),
    ('gap', 'acquisition_gap_restart_required'),
    ('overflow', 'inference_queue_overflow_restart_required'),
])
def test_showcase_submit_preserves_bounded_acquisition_guards(queued_showcase, case, reason):
    import numpy as np
    service, ctx, clock, events, generation = queued_showcase
    if case == 'first_late':
        clock.now += 31
    elif case == 'gap':
        service.submit(np.ones((16, 25)), 0, 250, generation)
        clock.now += 2.1
    elif case == 'overflow':
        for index in range(32):
            service.submit(np.ones((16, 25)), index * 25, 250, generation)
    service.submit(np.ones((16, 25)), 0, 250, generation)
    assert service.status()['reason'] == reason
    assert ctx.cancelled.is_set()
    assert not any(e['status'] == 'ready' for e in events)


def test_adaptive_service_rejects_showcase_on_live_or_wrong_rate():
    from adaptive_web import AdaptiveWebService
    service = AdaptiveWebService(lambda event: None)
    for mode, rate, profile in [('brainflow', 250, 'showcase'), ('demo', 500, 'showcase'),
                                ('demo', 250, 'unknown')]:
        with pytest.raises(ValueError):
            service.start(mode, rate, web.CHANNEL_NAMES, demo_profile=profile)
    assert service.status()['status'] == 'stopped'


def test_showcase_requires_configured_channel_order(queued_showcase):
    service, ctx, clock, events, generation = queued_showcase
    ctx.channels = tuple(reversed(ctx.channels))
    service._process(ctx)
    assert service.status()['reason'] == 'configured_channel_order_mismatch'
    assert not any(e['status'] == 'ready' for e in events)


def test_model_profile_keeps_missing_model_guard(tmp_path, monkeypatch):
    import anphy_sleep.config
    from adaptive_web import AdaptiveWebService, ROOT
    config, root = anphy_sleep.config.load_config(ROOT / 'config.hardware.yaml')
    config['data']['results_dir'] = str(tmp_path / 'missing-models')
    monkeypatch.setattr(anphy_sleep.config, 'load_config', lambda path: (config, root))
    monkeypatch.setattr(web.threading.Thread, 'start', lambda self: None)
    service = AdaptiveWebService(lambda event: None)
    service.start('demo', 250, web.CHANNEL_NAMES)
    service._process(service._session)
    assert service.status()['reason'] == 'configured_realtime_models_missing'
    assert service.status().get('demo_scripted') is not True


def test_live_session_cannot_enter_showcase_worker(queued_showcase, monkeypatch):
    service, ctx, clock, events, generation = queued_showcase
    ctx.source = 'LIVE'
    monkeypatch.setenv('TERRY_EEG_CHANNEL_MAP_CONFIRMED', '1')
    service._process(ctx)
    assert service.status()['reason'] == 'showcase_requires_demo_source'
    assert not any(e['status'] == 'ready' for e in events)
