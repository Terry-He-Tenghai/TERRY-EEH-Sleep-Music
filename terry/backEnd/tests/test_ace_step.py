import json
import io
import wave

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import ace_step as ace
import app as web
from starlette.requests import Request


def request(headers=None):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers or []})


def test_submit_style_and_prompt(monkeypatch):
    calls = []

    def fake_post(path, payload):
        calls.append((path, payload))
        return {"task_id": "task_12345678"}

    monkeypatch.setattr(ace, "post", fake_post)
    assert ace.generate(ace.GenerateRequest(style="piano", duration=30))["task_id"] == "task_12345678"
    assert calls[0][0] == "/release_task"
    assert "solo piano" in calls[0][1]["prompt"]
    assert calls[0][1]["audio_duration"] == 30
    assert calls[0][1]["audio_format"] == "wav"
    with pytest.raises(HTTPException) as exc:
        ace.generate(ace.GenerateRequest(style="unknown"))
    assert exc.value.status_code == 422


def test_official_extract_selects_base_and_requested_track(monkeypatch):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * (8000 * 12))
    monkeypatch.setattr(ace, 'cover_audio', lambda _: output.getvalue())
    captured = []
    monkeypatch.setattr(ace, 'post_cover', lambda payload, data: (captured.append((payload, data)), {'task_id': 'task_12345678'})[1])
    result = ace.extract(ace.ExtractRequest(reference_track_id='user_' + 'a' * 32, track='keyboard'))
    assert result['track'] == 'keyboard'
    assert captured[0][0]['model'] == 'acestep-v15-base'
    assert captured[0][0]['task_type'] == 'extract'
    assert captured[0][0]['instruction'] == 'Extract the KEYBOARD track from the audio:'
    assert captured[0][0]['audio_duration'] == 12
    assert captured[0][1] == output.getvalue()
    with pytest.raises(ValidationError):
        ace.ExtractRequest(reference_track_id='user_' + 'a' * 32, track='instrumental')


def test_cover_upload_uses_bounded_pcm_and_cover_task(monkeypatch, tmp_path):
    track_id = 'user_' + 'a' * 32
    source = tmp_path / 'uploaded.wav'
    with wave.open(str(source), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x01\x02' * (8000 * 125))
    import music_choices
    import music_library
    monkeypatch.setattr(music_choices, 'uploaded', lambda value: object() if value == track_id else None)
    monkeypatch.setattr(music_library, '_audio_path', lambda track: source)
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'code': 200, 'data': {'task_id': 'task_12345678'}, 'error': None}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        assert url.endswith('/release_task')
        return Response()

    monkeypatch.setattr(ace.requests, 'post', fake_post)
    separated = []
    monkeypatch.setattr(ace, 'separate_accompaniment', lambda audio: (separated.append(audio), audio)[1])
    result = ace.generate(ace.GenerateRequest(style='ambient', duration=120, reference_track_id=track_id))
    assert len(separated) == 1
    assert result['task_id'] == 'task_12345678'
    assert captured['data']['task_type'] == 'cover'
    assert captured['data']['audio_duration'] == '125.0'
    assert captured['data']['audio_cover_strength'] == '0.55'
    assert 'ctx_audio' in captured['files']
    with wave.open(io.BytesIO(captured['files']['ctx_audio'][1]), 'rb') as audio:
        assert audio.getnframes() == 125 * 8000
        assert audio.readframes(1) == b'\x01\x02'
    monkeypatch.setattr(music_choices, 'uploaded', lambda value: None)
    with pytest.raises(HTTPException) as exc:
        ace.generate(ace.GenerateRequest(style='ambient', reference_track_id=track_id))
    assert exc.value.status_code == 422


def test_separation_failure_does_not_submit_cover(monkeypatch):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * (8000 * 10))
    monkeypatch.setattr(ace, 'cover_audio', lambda _: output.getvalue())
    def fail(_):
        raise HTTPException(502, 'separation failed')
    monkeypatch.setattr(ace, 'separate_accompaniment', fail)
    monkeypatch.setattr(ace, 'post_cover', lambda *_: pytest.fail('Original audio must not be submitted'))
    with pytest.raises(HTTPException):
        ace.generate(ace.GenerateRequest(style='ambient', reference_track_id='user_' + 'a' * 32))


@pytest.mark.parametrize('seconds', [9, 601])
def test_cover_rejects_out_of_range_source_without_truncating(monkeypatch, tmp_path, seconds):
    source = tmp_path / 'uploaded.wav'
    with wave.open(str(source), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * (8000 * seconds))
    import music_choices
    import music_library
    monkeypatch.setattr(music_choices, 'uploaded', lambda _: object())
    monkeypatch.setattr(music_library, '_audio_path', lambda _: source)
    with pytest.raises(HTTPException) as exc:
        ace.cover_audio('user_' + 'a' * 32)
    assert exc.value.status_code == 422


def test_separator_rejects_invalid_audio(monkeypatch):
    class Response:
        content = b'not a wav file'
        def raise_for_status(self):
            pass
    monkeypatch.setattr(ace.requests, 'post', lambda *args, **kwargs: Response())
    with pytest.raises(HTTPException) as exc:
        ace.separate_accompaniment(b'source')
    assert exc.value.status_code == 502


@pytest.mark.parametrize('seconds', [1, 120, 600])
def test_separator_returns_valid_accompaniment(monkeypatch, seconds):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b'\x01\x02\x03\x04' * (44100 * seconds))
    class Response:
        content = output.getvalue()
        def raise_for_status(self):
            pass
    def post(url, **kwargs):
        assert url == 'http://127.0.0.1:8002/separate'
        assert kwargs['data'] == b'source'
        assert kwargs['timeout'] == (5, 1800)
        return Response()
    monkeypatch.setenv('AUDIO_SEPARATOR_URL', 'http://127.0.0.1:8002')
    monkeypatch.setattr(ace.requests, 'post', post)
    assert ace.separate_accompaniment(b'source') == output.getvalue()


def test_audio_upload_has_long_write_timeout(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'code': 200, 'data': {'task_id': 'task_12345678'}}

    def post(url, **kwargs):
        assert kwargs['timeout'] == (120, 1800)
        assert kwargs['files']['ctx_audio'][1] == b'audio'
        return Response()

    monkeypatch.setattr(ace.requests, 'post', post)
    assert ace.post_cover({'task_type': 'extract'}, b'audio')['task_id'] == 'task_12345678'


def test_separator_rejects_accompaniment_longer_than_ten_minutes(monkeypatch):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * (8000 * 601))
    class Response:
        content = output.getvalue()
        def raise_for_status(self):
            pass
    monkeypatch.setattr(ace.requests, 'post', lambda *args, **kwargs: Response())
    with pytest.raises(HTTPException) as exc:
        ace.separate_accompaniment(b'source')
    assert exc.value.status_code == 502


def test_separator_timeout_is_explicit(monkeypatch):
    def timeout(*args, **kwargs):
        raise ace.requests.Timeout()
    monkeypatch.setattr(ace.requests, 'post', timeout)
    with pytest.raises(HTTPException) as exc:
        ace.separate_accompaniment(b'source')
    assert exc.value.status_code == 502
    assert '8002' in exc.value.detail


def test_reference_track_is_only_available_in_ace_mode():
    track_id = 'user_' + 'a' * 32
    assert web.StartRequest(music_source='ace', music_style='ambient', reference_track_id=track_id).reference_track_id == track_id
    with pytest.raises(ValidationError):
        web.StartRequest(music_source='upload', reference_track_id=track_id)
    with pytest.raises(ValidationError):
        web.StartRequest(music_source='ace', music_style='ambient', reference_track_id='../source.wav')


def test_automatic_generation_passes_reference_id(monkeypatch):
    automatic = ace.AutomaticMusic()
    track_id = 'user_' + 'a' * 32
    automatic.start(54, 'ambient', track_id)
    automatic.wanted = 'M1'
    calls = []
    monkeypatch.setattr(ace, 'generate', lambda request: (calls.append(request), {'task_id': 'task_12345678'})[1])
    monkeypatch.setattr(ace, 'generation', lambda task_id: {'status': 'completed', 'audio_url': '/api/ace/generations/task_12345678/audio'})
    automatic._run(54)
    assert calls[0].reference_track_id == track_id
    assert calls[0].duration == 120


def test_scripted_demo_generates_without_model_and_keeps_first_completed_audio(monkeypatch):
    automatic = ace.AutomaticMusic()
    track_id = 'user_' + 'a' * 32
    automatic.start(54, 'ambient', track_id)
    event = {'session_id': 54, 'source': 'DEMO', 'status': 'ready',
             'demo_scripted': True, 'inference_mode': 'demo_scripted',
             'probability_origin': 'scripted_not_model', 'playback_mode': 'demo_scripted',
             'state': {'status': 'demo_scripted', 'baseline_ready': False},
             'target_music_state': 'M1', 'track_status': 'available',
             'selected_track': {'url': '/api/music/user_original/audio'}}

    class PendingThread:
        def __init__(self, target, args, **kwargs):
            self.run = lambda: target(*args)

        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(ace.threading, 'Thread', PendingThread)
    automatic.consider(event)
    assert automatic.status()['audio_url'] is None
    automatic.consider({**event, 'target_music_state': 'M2'})
    calls = []
    monkeypatch.setattr(ace, 'generate', lambda request: (calls.append(request), {'task_id': 'task_12345678'})[1])
    monkeypatch.setattr(ace, 'generation', lambda _: {'status': 'completed', 'audio_url': '/api/ace/generations/task_12345678/audio'})
    automatic.worker.run()
    assert calls[0].reference_track_id == track_id
    assert calls[0].duration == 120
    assert automatic.status()['audio_url'].startswith('/api/ace/')


def test_scripted_permission_cannot_be_spoofed_by_live_event(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(54, 'ambient')
    event = {'session_id': 54, 'source': 'LIVE', 'status': 'ready',
             'demo_scripted': True, 'inference_mode': 'demo_scripted',
             'probability_origin': 'scripted_not_model', 'playback_mode': 'demo_scripted',
             'state': {'status': 'demo_scripted'}, 'target_music_state': 'M1'}
    automatic.consider(event)
    assert automatic.worker is None
    assert automatic.status()['status'] == 'paused'


def test_poll_and_audio_uses_only_upstream_result(monkeypatch):
    monkeypatch.setattr(ace, "post", lambda path, payload: [{
        "task_id": "task_12345678", "status": 1,
        "result": json.dumps([{"file": "/v1/audio?path=%2Fserver%2Fgenerated.wav"}]),
    }])
    result = ace.generation("task_12345678")
    assert result["status"] == "completed"
    assert result["audio_url"].endswith("/task_12345678/audio")
    with pytest.raises(HTTPException) as exc:
        ace.audio("../../etc/passwd", request())
    assert exc.value.status_code == 422
    class FakeResponse:
        headers = {"content-length": "4"}
        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b"RIFF"

        def close(self):
            pass

    requests = []
    monkeypatch.setattr(ace.requests, "get", lambda url, **kwargs: (requests.append((url, kwargs)), FakeResponse())[1])
    response = ace.audio("task_12345678", request())
    assert response.media_type == "audio/wav"
    assert requests[0][1]["params"] == {"path": "/server/generated.wav"}
    ranged = ace.audio("task_12345678", request([(b"range", b"bytes=0-1")]))
    assert ranged.status_code == 206
    assert ranged.headers["content-range"] == "bytes 0-1/4"


def test_upstream_failure_and_queued(monkeypatch):
    monkeypatch.setattr(ace, "post", lambda path, payload: [{
        "task_id": "task_12345678", "status": 0, "result": "[]",
    }])
    assert ace.generation("task_12345678")["status"] == "processing"
    monkeypatch.setattr(ace, "post", lambda path, payload: [{
        "task_id": "task_12345678", "status": 2,
        "result": json.dumps([{"error": "model error"}]),
    }])
    assert ace.generation("task_12345678")["error"] == "model error"
    monkeypatch.setattr(ace, "post", lambda path, payload: [{
        "task_id": "task_12345678", "status": 1, "result": '[{"file":""}]',
        "progress_text": "export failed",
    }])
    assert ace.generation("task_12345678")["status"] == "failed"


def test_automatic_requires_valid_model_state(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(42, "ambient")
    event = {"session_id": 42, "status": "ready", "playback_mode": "demo_scripted",
             "source": "DEMO", "state": {"status": "demo_scripted", "baseline_ready": False},
             "target_music_state": "M2"}
    automatic.consider(event)
    assert automatic.worker is None
    event.update(playback_mode="adaptive", state={"status": "ok", "baseline_ready": True})
    started = []

    class FakeThread:
        def __init__(self, target, args, **kwargs):
            started.append((target, args))

        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(ace.threading, "Thread", FakeThread)
    automatic.consider(event)
    assert started[0][1] == (42,)
    automatic.stop()
    assert automatic.status()["status"] == "stopped"
    automatic.consider(event)
    assert len(started) == 1


def test_automatic_pauses_on_invalid_model_event_and_uses_cached_track():
    automatic = ace.AutomaticMusic()
    automatic.start(51, "piano")
    automatic.cached["M2"] = "/api/ace/generations/cached_audio/audio"
    valid = {"session_id": 51, "status": "ready", "playback_mode": "adaptive",
             "source": "LIVE", "state": {"status": "ok", "baseline_ready": False},
             "classification_confirmed": True, "signal_quality": 1.0,
             "inference_mode": "waveform_cnn", "probability_origin": "trained_waveform_cnn_experimental",
             "probabilities": {"W": .1, "N1": .8, "N2": .1}, "emitted_at_s": ace.time.time(),
             "target_music_state": "M2"}
    automatic.consider(valid)
    assert automatic.status()["status"] == "ready"
    automatic.consider({**valid, "state": {"status": "waiting", "baseline_ready": False}})
    assert automatic.status()["status"] == "paused"
    assert automatic.status()["audio_url"] is None
    automatic.consider(valid)
    assert automatic.status()["status"] == "ready"
    automatic.consider({**valid, "session_id": 50, "status": "frozen"})
    assert automatic.status()["status"] == "ready"


def test_reduced_montage_blocked_event_never_starts_automatic_music(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(53, "ambient")
    started = []
    monkeypatch.setattr(ace.threading, "Thread", lambda *args, **kwargs: started.append((args, kwargs)))
    automatic.consider({"session_id": 53, "source": "LIVE", "status": "blocked",
                        "reason": "live_inference_requires_16_channels", "playback_mode": "silent",
                        "state": None, "target_music_state": "M2"})
    assert automatic.status()["status"] == "paused"
    assert automatic.status()["audio_url"] is None
    assert started == []


def test_old_generation_completion_continues_to_new_target(monkeypatch):
    automatic = ace.AutomaticMusic()
    automatic.start(52, "ambient")
    automatic.wanted = "M1"
    submissions = []

    def fake_generate(_request):
        submissions.append(automatic.wanted)
        return {"task_id": f"task_{len(submissions):08d}"}

    def fake_generation(task_id):
        if task_id == "task_00000001":
            automatic.wanted = "M2"
        return {"status": "completed", "audio_url": f"/audio/{task_id}"}

    monkeypatch.setattr(ace, "generate", fake_generate)
    monkeypatch.setattr(ace, "generation", fake_generation)
    monkeypatch.setattr(ace.time, "monotonic", lambda: 1000 + len(submissions) * 61)
    automatic._run(52)
    assert submissions == ["M1", "M2"]
    assert automatic.status()["music_state"] == "M2"
    assert automatic.cached["M1"] == "/audio/task_00000001"
