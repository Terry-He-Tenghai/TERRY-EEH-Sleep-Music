import asyncio
import io
import json

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

import session_reports as reports_module
import songeval_client as client


def result():
    return dict(status='completed', audio_analyzed=True, model='SongEval', score_range=[1, 5],
                model_version='revision', method='segments', coverage_scope='excerpts',
                analyzed_audio_seconds=30, scores={key: 3.5 for key in client.KEYS})


def request(body):
    async def receive():
        return dict(type='http.request', body=json.dumps(body).encode(), more_body=False)
    return Request(dict(type='http', method='POST', headers=[]), receive)


def test_client_sends_only_audio_and_validates_native_scores(tmp_path, monkeypatch):
    path = tmp_path / 'mix.wav'
    path.write_bytes(b'RIFF-only-audio')
    def open_request(req, timeout):
        assert req.data == b'RIFF-only-audio'
        assert timeout == 1800
        return io.BytesIO(json.dumps(result()).encode())
    monkeypatch.setattr(client, 'urlopen', open_request)
    assert client.evaluate(path)['scores']['musicality'] == 3.5


@pytest.mark.parametrize('invalid', [True, None, 7, float('nan')])
def test_invalid_score_is_missing_not_zero(tmp_path, monkeypatch, invalid):
    path = tmp_path / 'mix.wav'
    path.write_bytes(b'RIFF')
    data = result()
    data['scores']['musicality'] = invalid
    monkeypatch.setattr(client, 'urlopen', lambda *a, **k: io.BytesIO(json.dumps(data).encode()))
    evaluated = client.evaluate(path)
    assert evaluated['status'] == 'failed'
    assert all(v is None for v in evaluated['scores'].values())


def test_job_requires_consent_and_persists_separate_scores(tmp_path, monkeypatch):
    store = reports_module.Reports(tmp_path)
    monkeypatch.setattr(reports_module, 'reports', store)
    identifier = store.start({'mode': 'brainflow'})
    store.finish('manual_stop', 0)
    store.attach(identifier, 'audio', {'metrics': {}})
    (tmp_path / f'{identifier}.wav').write_bytes(b'RIFF')
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(reports_module.song_evaluation(identifier, request({}), tasks))
    assert exc.value.status_code == 422
    monkeypatch.setattr(client, 'evaluate', lambda path: result())
    assert asyncio.run(reports_module.song_evaluation(identifier, request({'send_audio_to_server': True}), tasks))['status'] == 'running'
    assert reports_module.experiment_row(store.load(identifier))['songeval_status'] == 'running'
    with pytest.raises(HTTPException) as exc:
        asyncio.run(reports_module.song_evaluation(identifier, request({'send_audio_to_server': True}), BackgroundTasks()))
    assert exc.value.status_code == 409
    asyncio.run(tasks())
    row = reports_module.experiment_row(store.load(identifier))
    assert row['songeval_musicality'] == 3.5
    assert row['musicality'] is None
    assert row['ai_coherence'] is None
    assert not reports_module.song_job_lock.locked()


def test_interrupted_job_is_retryable_and_not_exported_as_score():
    report = {'id': 'f'*32, 'started_at_s': 1, 'songeval': {**result(), 'status': 'running'}}
    row = reports_module.experiment_row(report)
    assert row['songeval_status'] == 'failed'
    assert row['songeval_musicality'] is None


def test_upload_blocks_evaluation(tmp_path, monkeypatch):
    store = reports_module.Reports(tmp_path)
    monkeypatch.setattr(reports_module, 'reports', store)
    identifier = store.start({})
    reports_module.audio_uploads.add(identifier)
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(reports_module.song_evaluation(identifier, request({'send_audio_to_server': True}), BackgroundTasks()))
        assert exc.value.status_code == 409
    finally:
        reports_module.audio_uploads.discard(identifier)
