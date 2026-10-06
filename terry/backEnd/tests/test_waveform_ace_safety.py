"""ACE-Step must never turn stale or heuristic LIVE events into new music."""
import time

import pytest

import ace_step as ace


def valid_event():
    return {'session_id': 63, 'status': 'ready', 'source': 'LIVE', 'playback_mode': 'adaptive',
            'state': {'status': 'ok', 'baseline_ready': False}, 'classification_confirmed': True,
            'inference_mode': 'waveform_cnn', 'probability_origin': 'trained_waveform_cnn_experimental',
            'signal_quality': 1.0, 'probabilities': {'W': .8, 'N1': .15, 'N2': .05},
            'emitted_at_s': time.time(), 'target_music_state': 'M1'}


@pytest.mark.parametrize('patch', [
    {'classification_confirmed': False},
    {'probability_origin': 'eeg_spectral_heuristic_unvalidated', 'state': {'status': 'ok', 'baseline_ready': True}},
    {'probabilities': {'W': float('nan'), 'N1': .1, 'N2': .1}},
    {'probabilities': {'W': .1, 'N1': .1, 'N2': .1}},
    {'signal_quality': .5},
    {'emitted_at_s': 0},
    {'target_music_state': 'invalid'},
])
def test_invalid_live_events_cannot_start_generation(patch):
    automatic = ace.AutomaticMusic()
    automatic.start(63, 'ambient')
    automatic.consider({**valid_event(), **patch})
    assert automatic.worker is None
    assert automatic.status()['audio_url'] is None
    assert automatic.status()['status'] == 'paused'


def test_no_new_events_expires_cached_audio_permission(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(63, 'ambient')
    automatic.cached['M1'] = '/api/ace/generations/cached/audio'
    automatic.consider(valid_event())
    assert automatic.status()['status'] == 'ready'
    deadline = automatic.live_valid_until
    monkeypatch.setattr(ace.time, 'monotonic', lambda: deadline + .1)
    assert automatic.status()['status'] == 'paused'
    assert automatic.status()['audio_url'] is None
    assert automatic.wanted is None


def test_inflight_generation_finishes_into_cache_during_quality_hold(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(63, 'ambient')
    automatic.wanted = 'M1'
    automatic.last_submit = -1000
    def generate(_request):
        automatic.consider({**valid_event(), 'status': 'frozen', 'state': None,
                            'classification_confirmed': False, 'probabilities': None})
        assert automatic.status()['status'] == 'paused'
        return {'task_id': 'test_task_0001'}
    monkeypatch.setattr(ace, 'generate', generate)
    monkeypatch.setattr(ace, 'generation', lambda _task: {
        'status': 'completed', 'audio_url': '/api/ace/generations/test_task_0001/audio'})
    automatic._run(63)
    assert automatic.cached['M1'] == '/api/ace/generations/test_task_0001/audio'
    assert automatic.status()['audio_url'] is None
    automatic.consider(valid_event())
    assert automatic.status()['audio_url'] == automatic.cached['M1']


def test_new_target_keeps_old_audio_until_generated_track_is_ready(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(63, 'ambient')
    automatic.cached['M1'] = '/api/ace/generations/m1_track/audio'
    automatic.consider(valid_event())
    old = automatic.status()['audio_url']
    class PendingThread:
        def __init__(self, target, args, **kwargs):
            self.run = lambda: target(*args)
        def start(self):
            pass
        def is_alive(self):
            return True
    monkeypatch.setattr(ace.threading, 'Thread', PendingThread)
    automatic.consider({**valid_event(), 'target_music_state': 'M3',
                        'probabilities': {'W': .05, 'N1': .1, 'N2': .85}})
    assert automatic.status()['audio_url'] == old
    assert automatic.status()['wanted_music_state'] == 'M3'
    monkeypatch.setattr(ace, 'generate', lambda _: {'task_id': 'test_task_0001'})
    monkeypatch.setattr(ace, 'generation', lambda _: {
        'status': 'completed', 'audio_url': '/api/ace/generations/m3_track/audio'})
    automatic.worker.run()
    assert automatic.status()['music_state'] == 'M3'
    assert automatic.status()['audio_url'] != old


def test_cooldown_retries_new_target_on_next_valid_window(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(63, 'ambient')
    automatic.cached['M1'] = '/api/ace/generations/m1_track/audio'
    automatic.consider(valid_event())
    old = automatic.status()['audio_url']
    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.run = lambda: target(*args)
        def start(self):
            self.run()
        def is_alive(self):
            return False
    monkeypatch.setattr(ace.threading, 'Thread', InlineThread)
    now = [100.0]
    monkeypatch.setattr(ace.time, 'monotonic', lambda: now[0])
    automatic.last_submit = 99.0
    event = {**valid_event(), 'target_music_state': 'M2',
             'probabilities': {'W': .05, 'N1': .85, 'N2': .1}}
    automatic.consider(event)
    assert automatic.status()['audio_url'] == old
    assert automatic.status()['wanted_music_state'] == 'M2'
    calls = []
    monkeypatch.setattr(ace, 'generate', lambda request: (calls.append(request), {'task_id': 'test_task_0001'})[1])
    monkeypatch.setattr(ace, 'generation', lambda _: {
        'status': 'completed', 'audio_url': '/api/ace/generations/m3_track/audio'})
    now[0] = 115.0
    automatic.consider(event)
    assert len(calls) == 1
    assert automatic.status()['music_state'] == 'M2'


def test_two_distinct_valid_n2_predictions_pause_until_valid_non_n2():
    automatic = ace.AutomaticMusic()
    automatic.start(63, 'ambient')
    automatic.cached['M1'] = '/api/ace/generations/m1_track/audio'
    automatic.cached['M3'] = '/api/ace/generations/m3_track/audio'
    automatic.consider({**valid_event(), 'sequence': 1})
    n2 = {**valid_event(), 'target_music_state': 'M3', 'sequence': 2,
          'waveform_model': {'stage': 'N2'},
          'probabilities': {'W': .05, 'N1': .1, 'N2': .85}}
    automatic.consider(n2)
    assert automatic.status()['audio_url'] == automatic.cached['M3']
    automatic.consider(n2)
    assert automatic.status()['status'] == 'ready'
    automatic.consider({**n2, 'sequence': 3})
    assert automatic.status()['status'] == 'sleep_paused'
    assert automatic.status()['audio_url'] is None
    automatic.consider({**n2, 'sequence': 4})
    assert automatic.status()['status'] == 'sleep_paused'
    automatic.consider({**valid_event(), 'sequence': 5})
    assert automatic.status()['status'] == 'ready'
    assert automatic.status()['audio_url'] == automatic.cached['M1']


def test_bad_quality_breaks_n2_streak_without_resuming_sleep_pause():
    automatic = ace.AutomaticMusic()
    automatic.start(63, 'ambient')
    automatic.cached['M3'] = '/api/ace/generations/m3_track/audio'
    n2 = {**valid_event(), 'target_music_state': 'M3', 'sequence': 1,
          'waveform_model': {'stage': 'N2'},
          'probabilities': {'W': .05, 'N1': .1, 'N2': .85}}
    automatic.consider(n2)
    automatic.consider({**n2, 'sequence': 2, 'status': 'frozen', 'signal_quality': 0})
    automatic.consider({**n2, 'sequence': 3})
    assert automatic.status()['status'] == 'ready'
    automatic.consider({**n2, 'sequence': 4})
    automatic.consider({**n2, 'sequence': 5, 'status': 'frozen', 'signal_quality': 0})
    assert automatic.status()['status'] == 'sleep_paused'
