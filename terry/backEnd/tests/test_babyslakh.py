"""Curated original-audio access and projection, without hardware/model IO."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import stat
from types import SimpleNamespace
import wave

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
import pytest

import babyslakh
from adaptive_web import AdaptiveWebService, _Session
from eeg_music_modulation import EegMusicModulator

spec = importlib.util.spec_from_file_location('terry_stem_test_app', Path(__file__).parents[1] / 'app.py')
web = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = web
spec.loader.exec_module(web)


def write_wav(path, frames=160, rate=16000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((channels, 2, rate, frames, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * channels * frames)


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    root = tmp_path / 'dataset'
    for track_id, stems in babyslakh.CURATED.items():
        for stem_id in stems:
            write_wav(root / track_id / 'stems' / f'{stem_id}.wav')
        (root / track_id / 'metadata.yaml').write_text('stems:\n  S00:\n    audio_rendered: false\n    midi_saved: false\n')
    # Existing but intentionally excluded tracks/stems may never be exposed.
    write_wav(root / 'Track00001' / 'stems' / 'S00.wav')
    write_wav(root / 'Track00008' / 'stems' / 'S01.wav')
    monkeypatch.setenv('TERRY_BABYSLAKH_ROOT', str(root))
    return root


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(babyslakh.router)
    def get(path):
        messages = []
        async def run():
            async def receive():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message):
                messages.append(message)
            await app({'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                       'http_version': '1.1', 'method': 'GET', 'scheme': 'http', 'path': path,
                       'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
                       'headers': [], 'client': ('127.0.0.1', 1234), 'server': ('test', 80)}, receive, send)
        asyncio.run(run())
        start = next(m for m in messages if m['type'] == 'http.response.start')
        body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        return SimpleNamespace(status_code=start['status'], content=body,
                               headers={k.decode(): v.decode() for k, v in start['headers']},
                               json=lambda: json.loads(body))
    return SimpleNamespace(get=get)


def test_curated_list_uses_actual_headers_not_metadata_flags(dataset, client):
    response = client.get('/api/stem-music')
    assert response.status_code == 200
    tracks = response.json()['tracks']
    assert [track['id'] for track in tracks] == [f'Track{index:05d}' for index in range(1, 21)]
    for track in tracks:
        assert {s['id']: s['role'] for s in track['stems']} == babyslakh.CURATED[track['id']]
        assert len(track['stems']) == 4
        for item in [track, *track['stems']]:
            assert item['duration_seconds'] == .01
            assert item['sample_rate_hz'] == 16000
            assert item['channels'] == 1
        for stem in track['stems']:
            audio = client.get(stem['url'])
            assert audio.status_code == 200
            assert audio.headers['content-type'] == 'audio/wav'
            assert audio.content[:4] == b'RIFF'


def test_missing_or_mismatched_stems_hide_whole_track(dataset, client):
    (dataset / 'Track00008' / 'stems' / 'S00.wav').unlink()
    assert [t['id'] for t in client.get('/api/stem-music').json()['tracks']] == [f'Track{index:05d}' for index in range(1, 21) if index != 8]
    write_wav(dataset / 'Track00020' / 'stems' / 'S01.wav', frames=800)
    assert [t['id'] for t in client.get('/api/stem-music').json()['tracks']] == [
        f'Track{index:05d}' for index in range(1, 21) if index not in {8, 20}
    ]


@pytest.mark.parametrize('track,stem', [('Track00001', 'S00'), ('Track00008', 'S01'),
    ('..', 'S00'), ('Track00008/../Track00020', 'S00'), ('Track00008', '../mix'),
    ('Track00008', 'S00.wav'), ('Track00008', '..\\S00')])
def test_fixed_ids_reject_noncurated_and_traversal(dataset, track, stem):
    with pytest.raises(HTTPException) as exc:
        babyslakh.stem_audio(track, stem)
    assert exc.value.status_code == 404


@pytest.mark.parametrize('linked_kind', ['symlink', 'reparse'])
@pytest.mark.parametrize('part', ['file', 'stems', 'track', 'root', 'ancestor'])
def test_linked_paths_are_rejected_including_ancestors(dataset, tmp_path, monkeypatch, part, linked_kind):
    source = {'file': dataset / 'Track00008' / 'stems' / 'S00.wav',
              'stems': dataset / 'Track00008' / 'stems',
              'track': dataset / 'Track00008', 'root': dataset,
              'ancestor': tmp_path}[part]
    # Inject a real lstat-shaped reparse result; works on Windows without admin
    # symlink privileges and exercises every ancestor through the same guard.
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == source:
            return SimpleNamespace(st_mode=stat.S_IFLNK if linked_kind == 'symlink' else info.st_mode,
                                   st_file_attributes=0x400 if linked_kind == 'reparse' else 0)
        return info
    monkeypatch.setattr(Path, 'lstat', lstat)
    assert babyslakh.get_track('Track00008') is None
    with pytest.raises(HTTPException) as exc:
        babyslakh.stem_audio('Track00008', 'S00')
    assert exc.value.status_code == 404


def test_real_symlink_is_rejected(dataset, tmp_path):
    target = dataset / 'Track00008' / 'stems' / 'S00.wav'
    original = tmp_path / 'original.wav'
    target.rename(original)
    try:
        target.symlink_to(original)
    except OSError:
        pytest.skip('OS does not grant symlink creation privileges')
    assert babyslakh.get_track('Track00008') is None


def ready_event(level):
    return {'status': 'ready', 'track_status': 'available', 'playback_mode': 'adaptive',
            'modulation': {'control_level': level}}


def test_projection_contrast_uses_existing_modulator_control():
    def control(wake, n1):
        state = SimpleNamespace(window_end_s=320, aasm_state_probabilities={
            'W': wake, 'N1': n1, 'N2': 1-wake-n1}, interpretable_features={})
        return EegMusicModulator().apply(state, 'M2', 42)[3]['control_level']
    low, high = control(.01, .01), control(.97, .01)
    quiet = babyslakh.project_stem_mix('Track00020', ready_event(low))
    awake = babyslakh.project_stem_mix('Track00020', ready_event(high))
    assert quiet['control_level'] == low < high == awake['control_level']
    assert quiet['gains']['piano'] + .4 < awake['gains']['piano']
    assert quiet['gains']['bass'] < awake['gains']['bass']
    assert quiet['gains']['pad'] > awake['gains']['pad']
    assert quiet['gains']['strings'] > awake['gains']['strings']
    assert quiet['brightness'] < awake['brightness']
    assert set(quiet['gains']) == {'piano', 'strings', 'bass', 'pad'}
    for plan in [quiet, awake]:
        assert all(0 <= gain <= 1 for gain in plan['gains'].values())
        assert plan['mode'] == 'adaptive'
        assert plan['transition_seconds'] > 0


@pytest.mark.parametrize('level', [None, True, '0.5', float('nan'), float('inf'), -1, 2])
def test_invalid_controls_never_fabricated(level):
    assert babyslakh.project_stem_mix('Track00008', ready_event(level)) is None


def test_emit_projects_only_stem_sessions_and_clears_on_hold():
    events = []
    service = AdaptiveWebService(events.append)
    ctx = _Session(1, 'LIVE', 250, (), stem_track_id='Track00008')
    service._session = ctx
    service._emit(ctx, **ready_event(.8))
    assert events[-1]['stem_mix']['control_level'] == .8
    service._emit(ctx, playback_mode='conservative', modulation=None)
    conservative = events[-1]['stem_mix']
    assert conservative['mode'] == 'conservative'
    assert conservative['control_level'] is None
    assert max(conservative['gains'].values()) <= .12
    for status in ['waiting', 'frozen', 'blocked', 'error', 'stopped']:
        service._emit(ctx, status=status)
        assert events[-1]['stem_mix'] is None
    legacy = AdaptiveWebService(events.append)
    legacy_ctx = _Session(2, 'DEMO', 250, ())
    legacy._session = legacy_ctx
    legacy._emit(legacy_ctx, **ready_event(.5))
    assert 'stem_mix' not in events[-1]


def test_track_selection_does_not_require_suno(dataset, monkeypatch):
    import music_library
    monkeypatch.setattr(music_library, '_read_manifest', lambda: pytest.fail('Suno must not be read'))
    ctx = _Session(1, 'LIVE', 250, (), stem_track_id='Track00008')
    track, status = AdaptiveWebService._track('M3', ctx)
    assert status == 'available' and track['id'] == 'Track00008'


def test_start_request_is_strict_and_backward_compatible():
    assert web.StartRequest().stem_track_id is None
    assert web.StartRequest(uploaded_track_id='user_' + 'a' * 32).stem_track_id is None
    for value in ['Track00021', '../Track00008', 8, True, '']:
        with pytest.raises(ValidationError):
            web.StartRequest(stem_track_id=value)
    with pytest.raises(ValidationError):
        web.StartRequest(stem_track_id='Track00008', uploaded_track_id='user_' + 'a' * 32)


def test_start_checks_availability_and_skips_library_style(dataset, monkeypatch):
    calls = []
    monkeypatch.setattr(web.service, 'start', lambda request: calls.append(request) or web.service.status())
    monkeypatch.setattr(web, 'candidates', lambda style: pytest.fail('Stem mode must skip style lookup'))
    request = web.StartRequest(stem_track_id='Track00008', music_style='piano')
    asyncio.run(web.start(request))
    assert calls == [request]
    (dataset / 'Track00008' / 'stems' / 'S00.wav').unlink()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(web.start(request))
    assert exc.value.status_code == 422
    assert calls == [request]


def test_legacy_start_keeps_library_and_upload_validation(monkeypatch):
    monkeypatch.setattr(web, 'candidates', lambda style: [])
    monkeypatch.setattr(web, 'uploaded', lambda track: None)
    for request in [web.StartRequest(music_style='piano'),
                    web.StartRequest(uploaded_track_id='user_' + 'a' * 32)]:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(web.start(request))
        assert exc.value.status_code == 422


def test_acquisition_passes_stem_id_and_adaptive_start_stores_it(monkeypatch):
    service = web.AcquisitionService()
    calls = []
    monkeypatch.setattr(service._adaptive, 'start', lambda *args, **kwargs: calls.append((args, kwargs)) or 1)
    monkeypatch.setattr(web.threading.Thread, 'start', lambda self: None)
    service.start(web.StartRequest(stem_track_id='Track00020'))
    assert calls[0][1]['stem_track_id'] == 'Track00020'
    adaptive = AdaptiveWebService(lambda event: None)
    adaptive.start('demo', 250, (), stem_track_id='Track00020')
    assert adaptive._session.stem_track_id == 'Track00020'
    assert adaptive.status()['stem_mix'] is None
