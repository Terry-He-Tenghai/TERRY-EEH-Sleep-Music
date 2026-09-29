import json

import pytest
from fastapi import HTTPException

import ace_step as ace
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
