import time

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app as web
import session_reports as report_api
from experiment_analysis import METRICS, protocol_metrics
from raw_recording import RawRecording
from session_reports import ExperimentLabel, Reports


@pytest.fixture
def store(tmp_path, monkeypatch):
    result = Reports(tmp_path / 'reports')
    monkeypatch.setattr(web, 'reports', result)
    monkeypatch.setattr(report_api, 'reports', result)
    monkeypatch.setattr(web, 'RawRecording', lambda meta: RawRecording(meta, root=tmp_path / 'raw'))
    monkeypatch.setattr(web.ace_automatic, 'stop', lambda: None)
    return result


def test_fixed_enforces_record_only():
    request = web.StartRequest(music_source='ace', music_style='piano', auto_songeval=True,
        experiment={'participant': ' 测试甲 ', 'condition': 'fixed'})
    assert request.experiment.participant == '测试甲'
    assert request.music_source == 'external'
    assert request.save_raw_data and not request.auto_songeval
    assert request.demo_profile == 'model'
    with pytest.raises(ValidationError):
        web.StartRequest(experiment={'condition': 'sham'})
    with pytest.raises(ValidationError):
        web.StartRequest(music_source='external')


@pytest.mark.parametrize('condition', ['fixed', 'sham', 'closed_loop'])
def test_execution_sources_repeated_trials_and_raw_archive(condition, store, monkeypatch):
    service = web.AcquisitionService()
    starts, sham_starts, ace_starts = [], [], []
    monkeypatch.setattr(service._adaptive, 'start', lambda *a, **kw: starts.append((a, kw)) or 1)
    monkeypatch.setattr(service._sham, 'start', lambda *a, **kw: sham_starts.append((a, kw)) or 2)
    monkeypatch.setattr(service, '_run_sham', lambda generation: service._stop_event.wait(1))
    monkeypatch.setattr(service, '_run_brainflow', lambda request: service._stop_event.wait(1))
    monkeypatch.setattr(web.ace_automatic, 'start', lambda *a, **kw: ace_starts.append(a))
    ids = []
    for trial in (1, 2):
        service.start(web.StartRequest(mode='brainflow', music_source='ace', music_style='ambient',
            experiment={'participant': '测试甲', 'condition': condition}))
        ids.append(store.current['id'])
        assert store.current['experiment']['trial'] == trial
        service.stop()
        if condition == 'sham':
            assert not service._sham_thread.is_alive()
        report = store.load(ids[-1])
        assert report['raw_recording']['complete']
        assert report['metadata']['experiment_duration_s'] == 2700
        assert report['engineering']['backend_cpu_mean_percent'] >= 0
    assert ids[0] != ids[1]
    assert starts[0][0][0] == 'brainflow'
    assert starts[0][1]['music_source'] == ('ace' if condition == 'closed_loop' else 'external')
    if condition == 'sham':
        assert sham_starts[0][0][0:2] == ('demo', 250)
        assert sham_starts[0][1]['demo_profile'] == 'showcase'
        assert ace_starts[0][0] == 2
        assert report['experiment']['sham_trajectory_id'] == 'showcase-96s-v1'
    elif condition == 'fixed':
        assert not sham_starts and not ace_starts
    else:
        assert not sham_starts and ace_starts[0][0] == 1


def test_sham_keeps_real_eeg_separate_and_n2_does_not_end_trial(store, monkeypatch):
    store.start({'mode': 'brainflow'})
    service = web.AcquisitionService()
    service._condition = 'sham'
    broadcasts, music = [], []
    monkeypatch.setattr(service, '_broadcast', broadcasts.append)
    monkeypatch.setattr(web.ace_automatic, 'consider', music.append)
    for stamp in (40, 46):
        service._publish(dict(type='adaptive_music', source='LIVE', timestamp_s=stamp, status='ready',
            classification_confirmed=True, signal_quality=1, probabilities={'N2': .95, 'W': .05}))
    assert not service._stop_event.is_set()
    assert len(store.current['windows']) == 2 and not music
    assert all(event['type'] == 'eeg_measurement' for event in broadcasts)
    service._publish_sham(dict(type='adaptive_music', source='DEMO', timestamp_s=3, demo_scripted=True))
    assert len(store.current['windows']) == 2
    assert len(store.current['control_windows']) == 1 and len(music) == 1
    assert music[0]['music_control_source'] == 'scripted_demo'


def test_switching_conditions_keeps_music_generation_ids_unique(store, monkeypatch):
    service = web.AcquisitionService()
    # Block model workers, retaining real start/stop and generation assignment.
    monkeypatch.setattr(service._adaptive, '_worker', lambda: None)
    monkeypatch.setattr(service._sham, '_worker', lambda: None)
    monkeypatch.setattr(service, '_run_sham', lambda generation: service._stop_event.wait(1))
    monkeypatch.setattr(service, '_run_brainflow', lambda request: service._stop_event.wait(1))
    generations = []
    monkeypatch.setattr(web.ace_automatic, 'start', lambda generation, *a, **kw: generations.append(generation))
    monkeypatch.setattr(web.ace_automatic, 'consider', lambda event: None)
    for condition in ('closed_loop', 'sham', 'closed_loop', 'sham'):
        service.start(web.StartRequest(mode='brainflow', music_source='ace', music_style='ambient',
            experiment={'participant': 'Switching test', 'condition': condition}))
        assert service.adaptive_status()['session_id'] == generations[-1]
        service.stop()
    assert generations == [1, 2, 3, 4]


def test_fixed_never_controls_music_and_deadline_ends(store, monkeypatch):
    store.start({'mode': 'brainflow'})
    service = web.AcquisitionService()
    service._condition = 'fixed'
    broadcasts, music = [], []
    monkeypatch.setattr(service, '_broadcast', broadcasts.append)
    monkeypatch.setattr(web.ace_automatic, 'consider', music.append)
    service._publish(dict(type='adaptive_music', timestamp_s=40, source='LIVE', status='ready',
                          notes=[{'pitch': 60}], selected_track={'id': 'test'}))
    assert not music and broadcasts[-1]['notes'] == []
    assert broadcasts[-1]['playback_mode'] == 'silent'
    service._deadline = time.monotonic() - 1
    assert service._duration_complete()
    assert store.current['end_reason'] == 'duration_complete'


def test_unicode_labels_immutable_assignment_and_selected_analysis(store):
    ids = []
    for condition in ('fixed', 'sham'):
        label = ExperimentLabel(participant='测试甲', condition=condition,
                                trial_status='completed', condition_verified=True)
        identifier = store.start({'mode': 'brainflow', 'execution_version': 1, 'experiment': label.model_dump()})
        ids.append(identifier)
        report_api.label_experiment(identifier, label)
        store.finish('duration_complete', 2700)
    with pytest.raises(HTTPException):
        report_api.label_experiment(ids[0], ExperimentLabel(participant='测试甲', condition='closed_loop'))
    assert report_api.experiment_analysis(ids=[ids[1]])['counts']['sessions'] == 1
    assert report_api.experiment_analysis(ids=[''])['counts']['sessions'] == 0
    assert report_api.experiment_analysis()['counts']['sessions'] == 2
    assert '测试甲'.encode() in report_api.experiment_export().body


def test_sus_and_missing_metrics():
    best = protocol_metrics({'experiment': {'sus_items': [5, 1] * 5}})
    assert best['sus_score'] == 100
    assert protocol_metrics({'experiment': {'sus_items': [3] * 10}})['sus_score'] == 50
    assert protocol_metrics({'experiment': {'sus_items': [3] * 9 + [None]}})['sus_score'] is None
    assert best['alpha_relative_change'] is None
    assert 'heart_rate_change_bpm' not in METRICS and 'rmssd_change_ms' not in METRICS
    assert 'songeval_musicality' in METRICS and 'musicality' in METRICS
