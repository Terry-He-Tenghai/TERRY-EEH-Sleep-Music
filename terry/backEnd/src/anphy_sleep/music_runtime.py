from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .audio import AudioPlayer, NullAudioPlayer, PygameAudioPlayer, VlcAudioPlayer
from .contracts import MusicCommand, StateUpdate
from .music_policy import (
    MUSIC_PIPELINES,
    FiveModeMusicController,
    MusicMode,
    PolicyThresholds,
)
from .adaptive_music import AdaptiveMusicPolicy, select_suno_track
from .suno import (
    SunoApiError,
    SunoClient,
    TrackRepository,
    generation_request_for_mode,
)


class SunoGenerationWorker(threading.Thread):
    """Serialize network generation requests away from EEG and audio threads."""

    def __init__(
        self,
        client: SunoClient,
        repository: TrackRepository,
        callback_url: str,
        model: str = "V5_5",
        result_source: str = "poll",
        poll_interval_seconds: float = 30.0,
        poll_timeout_seconds: float = 360.0,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(name="suno-generation", daemon=True)
        self.client = client
        self.repository = repository
        self.callback_url = callback_url
        self.model = model
        self.result_source = str(result_source).lower()
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.poll_timeout_seconds = float(poll_timeout_seconds)
        self.sleeper = sleeper or time.sleep
        self.requests: queue.Queue[MusicMode | None] = queue.Queue()
        self.queued: set[MusicMode] = set()
        self.lock = threading.Lock()

    def request(self, mode: MusicMode) -> bool:
        if not MUSIC_PIPELINES[mode].generate_with_suno:
            return False
        with self.lock:
            if mode in self.queued or self.repository.task_exists(mode):
                return False
            self.queued.add(mode)
        self.requests.put(mode)
        return True

    def run(self) -> None:
        while True:
            mode = self.requests.get()
            if mode is None:
                self.requests.task_done()
                return
            try:
                generation = generation_request_for_mode(
                    mode,
                    self.callback_url,
                    self.model,
                )
                task_id = self.client.generate(generation)
                self.repository.register_task(mode, task_id)
                if self.result_source == "poll":
                    record = self.client.wait_for_completion(
                        task_id,
                        interval_seconds=self.poll_interval_seconds,
                        timeout_seconds=self.poll_timeout_seconds,
                        sleeper=self.sleeper,
                    )
                    self.repository.ingest_callback(record)
            except (SunoApiError, ValueError) as error:
                self.repository.record_generation_error(mode, str(error))
                with self.lock:
                    self.queued.discard(mode)
            finally:
                self.requests.task_done()

    def shutdown(self) -> None:
        self.requests.put(None)


@dataclass(frozen=True)
class RuntimeStatus:
    pending_mode: str | None
    last_error: str | None


class MusicPlaybackWorker(threading.Thread):
    """Resolve sparse commands against the cache and keep audio calls off EEG."""

    def __init__(
        self,
        repository: TrackRepository,
        player: AudioPlayer,
        generation_worker: SunoGenerationWorker | None = None,
        approved_only: bool = True,
    ) -> None:
        super().__init__(name="music-playback", daemon=True)
        self.repository = repository
        self.player = player
        self.generation_worker = generation_worker
        self.approved_only = approved_only
        self.commands: queue.Queue[MusicCommand | None] = queue.Queue()
        self.pending: MusicCommand | None = None
        self.last_error: str | None = None

    def submit(self, command: MusicCommand) -> None:
        if command.action not in {"none", "hold"}:
            self.commands.put(command)

    @staticmethod
    def _mode(command: MusicCommand) -> MusicMode | None:
        raw = command.parameters.get("mode")
        try:
            return MusicMode(str(raw)) if raw is not None else None
        except ValueError:
            return None

    def _resolve_and_execute(self, command: MusicCommand) -> bool:
        if command.action == "fade_out":
            duration = float(command.parameters.get("crossfade_seconds", 25.0))
            self.player.fade_out(duration)
            return True
        if command.action == "stop":
            self.player.stop()
            return True
        mode = self._mode(command)
        adaptive_role = str(command.parameters.get("adaptive_suno_role", ""))
        role_mode = {"warm_pad": MusicMode.ALPHA_STABILIZATION, "transition": MusicMode.THETA_TRANSITION, "minimal_drone": MusicMode.SLEEP_PROTECTION, "repair": MusicMode.MICRO_AROUSAL_REPAIR}
        if adaptive_role in role_mode:
            mode = role_mode[adaptive_role]
        if mode is None:
            self.last_error = "music command did not contain a valid mode"
            return True
        track = self.repository.select(mode, approved_only=self.approved_only)
        if track is None:
            if self.generation_worker is not None:
                self.generation_worker.request(mode)
            return False
        volume = int(command.parameters.get("target_volume", 35))
        if command.action == "play":
            self.player.play(track.url, volume)
        elif command.action == "crossfade":
            self.player.crossfade(
                track.url,
                volume,
                float(command.parameters.get("crossfade_seconds", 25.0)),
            )
        elif command.action == "overlay":
            self.player.overlay(track.url, volume)
        elif command.action == "generate":
            return True
        return True

    def run(self) -> None:
        while True:
            try:
                command = self.commands.get(timeout=1.0)
            except queue.Empty:
                if self.pending is not None and self._resolve_and_execute(
                    self.pending
                ):
                    self.pending = None
                continue
            if command is None:
                self.commands.task_done()
                return
            try:
                if not self._resolve_and_execute(command):
                    self.pending = command
            except Exception as error:
                self.last_error = str(error)
            finally:
                self.commands.task_done()

    def status(self) -> RuntimeStatus:
        mode = self._mode(self.pending) if self.pending is not None else None
        return RuntimeStatus(
            pending_mode=mode.value if mode is not None else None,
            last_error=self.last_error,
        )

    def shutdown(self) -> None:
        self.commands.put(None)


class AdaptiveMusicRuntime:
    """MusicController implementation that is non-blocking for RealtimeSession."""

    def __init__(
        self,
        repository: TrackRepository,
        policy: FiveModeMusicController | None = None,
        player: AudioPlayer | None = None,
        generation_worker: SunoGenerationWorker | None = None,
        approved_only: bool = True,
    ) -> None:
        self.repository = repository
        self.policy = policy or FiveModeMusicController()
        self.adaptive_policy = AdaptiveMusicPolicy()
        self.last_adaptive_target = None
        self.player = player or NullAudioPlayer()
        self.generation_worker = generation_worker
        self.playback_worker = MusicPlaybackWorker(
            repository,
            self.player,
            generation_worker,
            approved_only=approved_only,
        )

    def start(self, pregenerate: bool = True) -> None:
        if self.generation_worker is not None:
            self.generation_worker.start()
            if pregenerate:
                for mode, pipeline in MUSIC_PIPELINES.items():
                    if pipeline.generate_with_suno:
                        self.generation_worker.request(mode)
        self.playback_worker.start()

    def update(self, state: StateUpdate) -> MusicCommand:
        command = self.policy.update(state)
        target = self.adaptive_policy.target(state)
        self.last_adaptive_target = target
        parameters = dict(command.parameters)
        parameters.update({"adaptive_suno_role": target.role.value, "adaptive_music_state": target.state.value, "adaptive_midi_variation": target.variation.value, "adaptive_transition_seconds": target.transition_seconds, "adaptive_reason": target.reason})
        command = MusicCommand(command.action, parameters, command.reason, command.schema_version)
        self.playback_worker.submit(command)
        return command

    def shutdown(self) -> None:
        self.playback_worker.shutdown()
        if self.generation_worker is not None:
            self.generation_worker.shutdown()
        try:
            self.player.stop()
        except Exception:
            pass


def build_music_runtime(config: dict) -> AdaptiveMusicRuntime:
    """Build the configured runtime without starting any threads or API calls."""
    music = config["music"]
    repository = TrackRepository(music["cache_file"])
    backend = str(music.get("player_backend", "null")).lower()
    if backend == "null":
        player: AudioPlayer = NullAudioPlayer()
    elif backend == "vlc":
        player = VlcAudioPlayer()
    elif backend == "pygame":
        player = PygameAudioPlayer()
    else:
        raise ValueError(f"Unsupported music player backend: {backend}")

    generation_worker = None
    if bool(music.get("enabled", False)):
        suno = music.get("suno", {})
        callback_url = str(suno.get("callback_url", ""))
        if not callback_url:
            raise ValueError(
                "music.suno.callback_url is required when music.enabled=true"
            )
        client = SunoClient(base_url=str(suno["base_url"]))
        generation_worker = SunoGenerationWorker(
            client,
            repository,
            callback_url=callback_url,
            model=str(suno.get("model", "V5_5")),
            result_source=str(music.get("result_source", "poll")),
            poll_interval_seconds=float(
                music.get("poll_interval_seconds", 30.0)
            ),
            poll_timeout_seconds=float(
                music.get("poll_timeout_seconds", 360.0)
            ),
        )
    return AdaptiveMusicRuntime(
        repository,
        policy=FiveModeMusicController(
            PolicyThresholds.from_config(config)
        ),
        player=player,
        generation_worker=generation_worker,
        approved_only=bool(music.get("approved_only", True)),
    )
