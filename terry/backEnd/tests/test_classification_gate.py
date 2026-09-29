import time
from types import SimpleNamespace

from classification_gate import ClassificationGate
from ace_step import AutomaticMusic


def state(t, **kwargs):
    return SimpleNamespace(**dict(dict(status='ok', signal_quality=.8, window_end_s=t,
                                      aasm_state_probabilities={'W': .1, 'N1': .8, 'N2': .1}), **kwargs))


def test_full_window_and_three_confirmations_without_baseline():
    # This gate belongs to the existing DEMO model path. LIVE waveform models
    # use their own configurable two-confirmation gate in adaptive_web.
    gate = ClassificationGate()
    assert not gate.update(state(27))
    assert not gate.update(state(30))
    assert not gate.update(state(30))
    assert not gate.update(state(33))
    assert gate.update(state(36))
    assert not gate.update(state(39, signal_quality=0))
    assert not gate.update(state(42))
    assert not gate.update(state(45))
    assert gate.update(state(48))


def test_uncertain_and_changing_classification_cannot_start():
    gate = ClassificationGate()
    assert not gate.update(state(30))
    assert not gate.update(state(33, aasm_state_probabilities={'W': .8, 'N1': .1, 'N2': .1}))
    assert not gate.update(state(36, aasm_state_probabilities={'W': .4, 'N1': .3, 'N2': .3}))


def test_confirmed_classification_plays_cached_style_before_baseline(monkeypatch):
    monkeypatch.setattr('threading.Thread.start', lambda self: None)
    music = AutomaticMusic()
    music.start(12, 'ambient')
    event = dict(session_id=12, status='ready', playback_mode='adaptive', source='LIVE',
                 state={'status': 'ok', 'baseline_ready': False}, classification_confirmed=True,
                 inference_mode='waveform_cnn', probability_origin='trained_waveform_cnn_experimental',
                 emitted_at_s=time.time(), signal_quality=1.0,
                 probabilities={'W': .1, 'N1': .8, 'N2': .1},
                 target_music_state='M2', selected_track={'url': '/api/music/style-ambient-0/audio'},
                 track_status='available')
    music.consider(event)
    assert music.status()['status'] == 'ready'
    assert music.status()['audio_url'] == event['selected_track']['url']
    music.consider({**event, 'status': 'frozen'})
    assert music.status()['status'] == 'paused'
    assert music.status()['audio_url'] is None
