import numpy as np
import soundfile as sf
import pytest
from session_reports import Reports, analyze_audio, build_trace
from session_reports import experiment_row, ExperimentLabel


def event(end, stage='N2', **extra):
    return dict(timestamp_s=end, sequence=int(end), source='LIVE', status='ready',
                signal_quality=1., classification_confirmed=True,
                probabilities={s: .9 if s == stage else .05 for s in ('W', 'N1', 'N2')}, **extra)


def test_n2_requires_distinct_qualified_live_windows(tmp_path):
    reports = Reports(tmp_path)
    identifier = reports.start({'mode': 'brainflow'})
    assert not reports.observe(event(40))
    assert not reports.observe(event(40))
    invalid = event(46)
    invalid['signal_quality'] = 0.
    assert not reports.observe(invalid)
    assert not reports.observe(event(52))
    assert reports.observe(event(58))
    reports.finish('two_valid_n2', 58)
    reports.finish('manual_stop', 60)
    report = reports.load(identifier)
    assert report['end_reason'] == 'two_valid_n2'
    assert len(report['windows']) == 4
    assert report['eeg_summary']['qualified_window_ratio'] == .75
    assert report['eeg_summary']['packet_loss'] is None


def test_demo_never_triggers_sleep_end(tmp_path):
    reports = Reports(tmp_path)
    reports.start({'mode': 'demo'})
    for end in (40, 46, 52):
        sample = event(end)
        sample['source'] = 'DEMO'
        sample['demo_scripted'] = True
        assert not reports.observe(sample)


def test_attachment_does_not_restore_running_session(tmp_path):
    reports = Reports(tmp_path)
    identifier = reports.start({})
    reports.finish('manual_stop', 0)
    reports.attach(identifier, 'browser', {'events': []})
    assert reports.load(identifier)['ended_at_s'] is not None
    with pytest.raises(Exception):
        reports.load('../anything')


def test_audio_screens_stereo_output_not_cancelled_mono(tmp_path):
    rate = 8000
    wave = .3 * np.sin(2*np.pi*440*np.arange(rate*2)/rate)
    path = tmp_path / 'output.wav'
    sf.write(path, np.column_stack([wave, -wave]), rate, subtype='FLOAT')
    report = analyze_audio(path)
    assert len(report['frames']) == 2
    assert report['frames'][0]['rms_dbfs'] > -20
    assert abs(report['frames'][0]['centroid_hz'] - 440) < 5
    assert report['bpm'] is None
    assert report['comfort_conclusion'] is None


def test_output_preserves_overload_and_rms_jump_candidates(tmp_path):
    rate = 8000
    time = np.arange(rate)/rate
    samples = np.concatenate([.1*np.sin(2*np.pi*440*time), 1.2*np.sin(2*np.pi*440*time)])
    path = tmp_path / 'overload.wav'
    sf.write(path, samples, rate, subtype='FLOAT')
    report = analyze_audio(path)
    assert report['frames'][1]['clipped_samples'] > 0
    assert report['rms_jump_candidates']


def test_trace_does_not_invent_ace_generation_window():
    report = {'windows': [event(40)], 'browser': {'recording_started_audio_s': 1,
              'events': [{'type': 'applied', 'engine': 'stems', 'sequence': 40, 'audio_time_s': 3},
                         {'type': 'playback-started', 'engine': 'ace', 'sequence': 40, 'audio_time_s': 3}]},
              'audio': {'metrics': {'frames': [{'time_s': 2, 'rms_dbfs': -20}]}}}
    trace = build_trace(report)
    assert trace[0]['eeg_window']['timestamp_s'] == 40
    assert trace[0]['recording_time_s'] == 2
    assert len(trace[0]['nearby_audio_frames']) == 1
    assert trace[1]['eeg_window'] is None


def test_report_api_saves_recording_and_analysis(tmp_path, monkeypatch):
    import asyncio
    import json
    import session_reports as module
    from fastapi import HTTPException
    from starlette.requests import Request
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    store = Reports(tmp_path)
    monkeypatch.setattr(module, 'reports', store)
    identifier = store.start({'mode': 'test'})
    store.finish('manual_stop', 0)
    def request(payload):
        async def receive():
            return {'type': 'http.request', 'body': payload, 'more_body': False}
        return Request({'type': 'http', 'method': 'PUT', 'headers': []}, receive)
    path = tmp_path / 'test.wav'
    sf.write(path, np.zeros((8000, 2)), 8000, subtype='FLOAT')
    assert asyncio.run(module.browser_report(identifier, request(json.dumps({'events': []}).encode())))['status'] == 'saved'
    assert asyncio.run(module.audio_report(identifier, request(path.read_bytes())))['status'] == 'saved'
    saved = module.get_report(identifier)
    assert saved['audio']['metrics']['frames'][0]['rms_dbfs'] == -240
    assert module.download_audio(identifier).path.read_bytes()[:4] == b'RIFF'
    with pytest.raises(HTTPException) as exception:
        asyncio.run(module.audio_report(identifier, request(b'invalid')))
    assert exception.value.status_code == 422


def test_experiment_missing_data_is_not_zero():
    row = experiment_row({'id': 'a' * 32, 'started_at_s': 1, 'metadata': {'mode': 'demo'}})
    assert row['condition'] == 'unassigned'
    assert row['centroid_hz'] is None
    assert row['clipped_samples'] is None
    assert row['playback_errors'] is None
    assert row['alpha_power_uv2'] is None
    assert row['ended'] is False


def test_experiment_labels_persist_and_export(tmp_path, monkeypatch):
    import session_reports as module
    from pydantic import ValidationError
    store = Reports(tmp_path)
    monkeypatch.setattr(module, 'reports', store)
    identifier = store.start({'mode': 'brainflow', 'music_source': 'stems'})
    store.observe(event(40, classification_ms=12, band_power_uv2={'values': {'alpha': [2, 4]}}))
    store.finish('manual_stop', 40)
    module.label_experiment(identifier, ExperimentLabel(participant='P001', condition='closed_loop', comfort=5))
    row = module.experiment_summary()['rows'][0]
    assert row['participant'] == 'P001'
    assert row['classification_ms'] == 12
    assert row['alpha_power_uv2'] == 3
    assert row['comfort'] == 5
    assert row['ended'] is True
    assert b'P001' in module.experiment_export().body
    assert store.load(identifier)['windows']
    with pytest.raises(ValidationError):
        ExperimentLabel(participant='=formula')
    with pytest.raises(ValidationError):
        ExperimentLabel(comfort=8)
