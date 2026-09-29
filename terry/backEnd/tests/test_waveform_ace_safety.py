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
