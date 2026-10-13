"""Opt-in live smoke test; never writes to the production session archive."""
import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from starlette.requests import Request

import session_reports as module


@pytest.mark.skipif(not os.environ.get('SONGEVAL_SMOKE_WAV'), reason='Requires live private SongEval and official example WAV')
def test_live_private_service_persists_scores_and_exports_csv(tmp_path, monkeypatch):
    store = module.Reports(tmp_path)
    monkeypatch.setattr(module, 'reports', store)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    identifier = store.start({'mode': 'test'})
    store.finish('manual_stop', 0)
    store.attach(identifier, 'audio', {'metrics': {}})
    (tmp_path / f'{identifier}.wav').write_bytes(Path(os.environ['SONGEVAL_SMOKE_WAV']).read_bytes())
    async def receive():
        return {'type': 'http.request', 'body': b'{"send_audio_to_server":true}', 'more_body': False}
    request = Request({'type': 'http', 'method': 'POST', 'headers': []}, receive)
    tasks = BackgroundTasks()
    asyncio.run(module.song_evaluation(identifier, request, tasks))
    asyncio.run(tasks())
    song = module.get_report(identifier)['songeval']
    assert song['status'] == 'completed', song
    assert song['analyzed_audio_seconds'] == 30
    assert song['encoder_revision'] == '0562a57814f6f8bbd9fdea0a25921a2fce1a841a'
    row = module.experiment_summary()['rows'][0]
    assert 1 <= row['songeval_musicality'] <= 5
    assert b'songeval_musicality' in module.experiment_export().body
    assert not module.song_job_lock.locked()
    print(json.dumps(song, indent=2))
