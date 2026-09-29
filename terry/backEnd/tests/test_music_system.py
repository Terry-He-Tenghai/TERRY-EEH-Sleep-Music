import json
from pathlib import Path

from anphy_sleep.audio import NullAudioPlayer
from anphy_sleep.contracts import StateUpdate
from anphy_sleep.music_policy import (
    FiveModeMusicController,
    MusicMode,
    PolicyThresholds,
)
from anphy_sleep.music_runtime import AdaptiveMusicRuntime
from anphy_sleep.suno import (
    SunoClient,
    TrackRepository,
    generation_request_for_mode,
)


def _state(
    time_s: float,
    probabilities: dict[str, float],
    future_n2: float = 0.2,
    beta_z: float = 0.0,
    alpha_z: float = 0.0,
    theta_z: float = 0.0,
) -> StateUpdate:
    return StateUpdate(
        session_id="test",
        window_end_s=time_s,
        signal_quality=1.0,
        status="ok",
        baseline_ready=True,
        n2_within_5m_probability=future_n2,
        aasm_state_probabilities=probabilities,
        interpretable_features={
            "frontal_beta_z": beta_z,
            "posterior_alpha_z": alpha_z,
            "central_theta_z": theta_z,
        },
    )


def test_five_mode_policy_confirms_sparse_transitions() -> None:
    controller = FiveModeMusicController(
        PolicyThresholds(
            decision_interval_seconds=30,
            confirmations_required=2,
            minimum_mode_dwell_seconds=0,
        )
    )
    commands = [
        controller.update(
            _state(0, {"W": 0.9, "N1": 0.08, "N2": 0.02}, beta_z=1)
        )
    ]
    for time_s in (30, 60):
        commands.append(
            controller.update(
                _state(
                    time_s,
                    {"W": 0.85, "N1": 0.12, "N2": 0.03},
                    beta_z=-0.4,
                    alpha_z=1.0,
                )
            )
        )
    for time_s in (90, 120, 150):
        commands.append(
            controller.update(
                _state(
                    time_s,
                    {"W": 0.15, "N1": 0.78, "N2": 0.07},
                    future_n2=0.7,
                    theta_z=1.0,
                )
            )
        )
    for time_s in (180, 210, 240):
        commands.append(
            controller.update(
                _state(
                    time_s,
                    {"W": 0.03, "N1": 0.15, "N2": 0.82},
                    future_n2=0.9,
                    theta_z=1.2,
                )
            )
        )

    event_modes = [
        command.parameters.get("mode")
        for command in commands
        if command.action in {"play", "crossfade", "fade_out"}
    ]
    assert event_modes == [
        MusicMode.ANTI_HYPERAROUSAL.value,
        MusicMode.ALPHA_STABILIZATION.value,
        MusicMode.THETA_TRANSITION.value,
        MusicMode.SLEEP_PROTECTION.value,
    ]
    assert commands[0].parameters["music_state"] == "M1"
    assert "layer_pad_gain" in commands[-1].parameters
    assert "phrase_boundary" in commands[-1].parameters


def test_micro_arousal_uses_cached_overlay_command() -> None:
    controller = FiveModeMusicController()
    controller.current_mode = MusicMode.THETA_TRANSITION
    command = controller.update(
        _state(
            300,
            {"W": 0.6, "N1": 0.35, "N2": 0.05},
            beta_z=3.0,
        )
    )
    assert command.action == "overlay"
    assert (
        command.parameters["mode"]
        == MusicMode.MICRO_AROUSAL_REPAIR.value
    )


def test_suno_request_and_callback_cache(tmp_path: Path) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return b'{"code":200,"msg":"success","data":{"taskId":"task-1"}}'

    def opener(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    client = SunoClient(api_key="secret", opener=opener)
    request = generation_request_for_mode(
        MusicMode.ANTI_HYPERAROUSAL,
        "https://example.test/suno/callback/secret",
    )
    assert client.generate(request) == "task-1"
    assert captured["payload"]["instrumental"] is True
    assert captured["payload"]["customMode"] is True
    assert "prompt" not in captured["payload"]

    repository = TrackRepository(tmp_path / "cache.json")
    repository.register_task(MusicMode.ANTI_HYPERAROUSAL, "task-1")
    added = repository.ingest_callback(
        {
            "data": {
                "taskId": "task-1",
                "callbackType": "first",
                "data": [
                    {
                        "id": "track-1",
                        "title": "Track One",
                        "audioUrl": "https://audio.test/one.mp3",
                    },
                    {
                        "id": "track-2",
                        "title": "Track Two",
                        "audioUrl": "https://audio.test/two.mp3",
                    },
                ],
            }
        }
    )
    assert added == 2
    assert repository.select(MusicMode.ANTI_HYPERAROUSAL) is None
    approved = repository.approve(MusicMode.ANTI_HYPERAROUSAL, 0)
    assert approved.url == "https://audio.test/one.mp3"
    assert (
        repository.select(MusicMode.ANTI_HYPERAROUSAL).url
        == approved.url
    )


def test_runtime_plays_only_approved_cached_track(tmp_path: Path) -> None:
    repository = TrackRepository(tmp_path / "cache.json")
    # AdaptiveMusicRuntime maps the awake warm_pad role to ALPHA_STABILIZATION.
    repository.register_task(MusicMode.ALPHA_STABILIZATION, "task-1")
    repository.ingest_callback(
        {
            "taskId": "task-1",
            "callbackType": "complete",
            "audioUrl": "https://audio.test/approved.mp3",
        }
    )
    repository.approve(MusicMode.ALPHA_STABILIZATION, 0)
    player = NullAudioPlayer()
    runtime = AdaptiveMusicRuntime(
        repository,
        player=player,
        approved_only=True,
    )
    runtime.start(pregenerate=False)
    command = runtime.update(
        _state(0, {"W": 0.9, "N1": 0.08, "N2": 0.02}, beta_z=1)
    )
    assert command.parameters['adaptive_suno_role'] == 'warm_pad'
    runtime.playback_worker.commands.join()
    runtime.shutdown()
    assert player.events[0].action == "play"
    assert player.events[0].url == "https://audio.test/approved.mp3"


def test_suno_polling_ingests_record_info(tmp_path: Path) -> None:
    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return self.body

    def opener(request, timeout):
        if request.get_method() == "POST":
            return Response(
                b'{"code":200,"msg":"success","data":{"taskId":"task-9"}}'
            )
        assert "record-info" in request.full_url
        assert "taskId=task-9" in request.full_url
        return Response(
            json.dumps(
                {
                    "code": 200,
                    "msg": "success",
                    "data": {
                        "taskId": "task-9",
                        "status": "SUCCESS",
                        "response": {
                            "sunoData": [
                                {
                                    "id": "audio-1",
                                    "audioUrl": "https://audio.test/poll.mp3",
                                    "title": "Polled Track",
                                }
                            ]
                        },
                    },
                }
            ).encode("utf-8")
        )

    client = SunoClient(api_key="secret", opener=opener)
    task_id = client.generate(
        generation_request_for_mode(
            MusicMode.ANTI_HYPERAROUSAL,
            "https://example.com/suno/callback",
        )
    )
    record = client.wait_for_completion(
        task_id,
        interval_seconds=0,
        timeout_seconds=5,
        sleeper=lambda _: None,
    )
    repository = TrackRepository(tmp_path / "cache.json")
    repository.register_task(MusicMode.ANTI_HYPERAROUSAL, task_id)
    assert repository.ingest_callback(record) == 1
    track = repository.select(
        MusicMode.ANTI_HYPERAROUSAL,
        approved_only=False,
    )
    assert track is not None
    assert track.url == "https://audio.test/poll.mp3"
