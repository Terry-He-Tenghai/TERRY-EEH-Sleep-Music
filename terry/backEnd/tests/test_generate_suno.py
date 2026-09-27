import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('generate_suno', Path(__file__).parents[1] / 'scripts/generate_suno.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_submit_once_and_persist_without_key(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'ROOT', tmp_path)
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Original instrumental ambient')
    calls = []
    def api(*args):
        calls.append(args)
        return {'id': 'task-unified-abc', 'status': 'pending', 'secret': 'must-not-persist'}
    monkeypatch.setattr(mod, 'api_request', api)
    mod.run(SimpleNamespace(action='submit', prompt_file=prompt), 'test-only-key')
    assert len(calls) == 1
    assert calls[0][3]['model'] == 'suno-v5.5'
    record = (tmp_path / 'music/candidates/task-unified-abc/task.json').read_text()
    assert 'test-only-key' not in record and 'must-not-persist' not in record


@pytest.mark.parametrize('url', ['http://img.aisaasgo.org/a.mp3', 'https://evil.example/a.mp3',
                                  'https://img.aisaasgo.org@evil.example/a.mp3',
                                  'https://img.aisaasgo.org/a.html'])
def test_reject_untrusted_audio_url(tmp_path, url):
    with pytest.raises(ValueError):
        mod.download_audio(url, tmp_path, 0)


@pytest.mark.parametrize('extension', ['mp3', 'mpeg'])
def test_fetch_download_has_no_authorization(tmp_path, monkeypatch, extension):
    monkeypatch.setattr(mod, 'ROOT', tmp_path)
    monkeypatch.setattr(mod, 'api_request', lambda *args: {'id': 'task-1', 'status': 'completed',
                         'results': [f'https://img.aisaasgo.org/a.{extension}']})
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield b'ID3-test-candidate'
    def get(url, **kwargs):
        assert 'headers' not in kwargs and not kwargs['allow_redirects']
        return Response()
    monkeypatch.setattr(mod.requests, 'get', get)
    mod.run(SimpleNamespace(action='fetch', task_id='task-1', wait_seconds=0), 'test-key')
    assert (tmp_path / 'music/candidates/task-1/candidate-0.mp3').exists()
    assert not (tmp_path / 'music/manifest.json').exists()


def test_pending_does_not_resubmit(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'ROOT', tmp_path)
    calls = []
    def api(method, *args):
        calls.append(method)
        return {'id': 'task-1', 'status': 'pending'}
    monkeypatch.setattr(mod, 'api_request', api)
    mod.run(SimpleNamespace(action='fetch', task_id='task-1', wait_seconds=0), 'test-key')
    assert calls == ['GET']


def test_failed_task_does_not_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'ROOT', tmp_path)
    monkeypatch.setattr(mod, 'api_request', lambda *args: {'id': 'task-1', 'status': 'failed'})
    with pytest.raises(RuntimeError):
        mod.run(SimpleNamespace(action='fetch', task_id='task-1', wait_seconds=0), 'test-key')


def test_post_timeout_has_no_retry(monkeypatch):
    calls = []
    def request(*args, **kwargs):
        calls.append(args)
        raise mod.requests.Timeout()
    monkeypatch.setattr(mod.requests, 'request', request)
    with pytest.raises(RuntimeError):
        mod.api_request('POST', '/audios/generations', 'test-key', {})
    assert len(calls) == 1


def test_v5_body_and_duration_restriction():
    args = SimpleNamespace(model='suno-v5', custom_mode=True, style='ambient', title='Quiet')
    body = mod.create_body(args, 'warm pad')
    assert body['model'] == 'suno-v5'
    assert 'duration' not in body
    args.duration = 180
    with pytest.raises(ValueError, match='only supported'):
        mod.create_body(args, 'warm pad')


def test_basic_body_is_explicitly_instrumental():
    assert mod.create_body(SimpleNamespace(), 'quiet ambient') == {
        'model': 'suno-v5.5', 'prompt': 'quiet ambient',
        'custom_mode': False, 'instrumental': True,
    }


def test_custom_body():
    args = SimpleNamespace(custom_mode=True, style=' ambient ', title=' Quiet ',
                           negative_tags='vocals, drums', duration=180)
    body = mod.create_body(args, 'warm pad')
    assert body['style'] == 'ambient' and body['title'] == 'Quiet'
    assert body['instrumental'] is True and body['custom_mode'] is True
    assert body['duration'] == 180 and body['negative_tags'] == 'vocals, drums'


@pytest.mark.parametrize('args', [SimpleNamespace(custom_mode=True),
    SimpleNamespace(custom_mode=True, style=' ', title='Quiet'),
    SimpleNamespace(duration=180),
    SimpleNamespace(custom_mode=True, style='ambient', title='Quiet', duration=-1)])
def test_invalid_custom_options(args):
    with pytest.raises(ValueError):
        mod.create_body(args, 'warm pad')


def test_provider_error_is_redacted(monkeypatch):
    class Response:
        status_code = 400
        def json(self):
            return {'error': {'message': 'Missing style test-secret sk_live_abc https://example.com/?token=private'}}
    monkeypatch.setattr(mod.requests, 'request', lambda *a, **k: Response())
    with pytest.raises(mod.ProviderError) as result:
        mod.api_request('POST', '/audios/generations', 'test-secret', {})
    message = str(result.value)
    assert '400' in message and 'Missing style' in message
    assert 'test-secret' not in message and 'sk_live_abc' not in message and 'token=private' not in message
