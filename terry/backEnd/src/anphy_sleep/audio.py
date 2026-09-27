from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import requests


class AudioPlayer(Protocol):
    def play(self, url: str, volume: int) -> None: ...

    def crossfade(
        self,
        url: str,
        volume: int,
        duration_seconds: float,
    ) -> None: ...

    def overlay(self, url: str, volume: int) -> None: ...

    def fade_out(self, duration_seconds: float) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class PlaybackEvent:
    action: str
    url: str | None
    volume: int | None
    duration_seconds: float | None = None


class NullAudioPlayer:
    """Deterministic test/dry-run backend that never touches an audio device."""

    def __init__(self) -> None:
        self.events: list[PlaybackEvent] = []

    def play(self, url: str, volume: int) -> None:
        self.events.append(PlaybackEvent("play", url, volume))

    def crossfade(
        self,
        url: str,
        volume: int,
        duration_seconds: float,
    ) -> None:
        self.events.append(
            PlaybackEvent("crossfade", url, volume, duration_seconds)
        )

    def overlay(self, url: str, volume: int) -> None:
        self.events.append(PlaybackEvent("overlay", url, volume))

    def fade_out(self, duration_seconds: float) -> None:
        self.events.append(
            PlaybackEvent("fade_out", None, 0, duration_seconds)
        )

    def stop(self) -> None:
        self.events.append(PlaybackEvent("stop", None, None))


class PygameAudioPlayer:
    """Windows-friendly pygame backend; downloads remote URLs before playback."""

    def __init__(self) -> None:
        try:
            import pygame
        except ImportError as error:
            raise RuntimeError(
                "Install pygame to use music.player_backend: pygame"
            ) from error
        pygame.mixer.init()
        self.pygame = pygame
        self.lock = threading.RLock()
        self.current_volume = 0
        self._cache_dir = Path(tempfile.mkdtemp(prefix="anphy-music-"))

    def _resolve(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return url
        name = Path(url.split("?", 1)[0]).name or "track.mp3"
        destination = self._cache_dir / name
        if not destination.suffix:
            destination = destination.with_suffix(".mp3")
        if not destination.exists():
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return str(destination)

    def play(self, url: str, volume: int) -> None:
        with self.lock:
            path = self._resolve(url)
            self.pygame.mixer.music.load(path)
            self.pygame.mixer.music.set_volume(
                max(0.0, min(1.0, int(volume) / 100.0))
            )
            self.pygame.mixer.music.play(-1)
            self.current_volume = int(volume)

    def crossfade(
        self,
        url: str,
        volume: int,
        duration_seconds: float,
    ) -> None:
        with self.lock:
            fade_ms = max(1, int(duration_seconds * 1000))
            self.pygame.mixer.music.fadeout(fade_ms)
            time.sleep(max(0.0, duration_seconds))
            self.play(url, volume)

    def overlay(self, url: str, volume: int) -> None:
        path = self._resolve(url)
        sound = self.pygame.mixer.Sound(path)
        sound.set_volume(max(0.0, min(1.0, int(volume) / 100.0)))
        sound.play()

    def fade_out(self, duration_seconds: float) -> None:
        with self.lock:
            fade_ms = max(1, int(duration_seconds * 1000))
            self.pygame.mixer.music.fadeout(fade_ms)
            time.sleep(max(0.0, duration_seconds))
            self.current_volume = 0

    def stop(self) -> None:
        with self.lock:
            self.pygame.mixer.music.stop()
            self.current_volume = 0


class VlcAudioPlayer:
    """Optional VLC backend for URLs and local files with gradual volume changes."""

    def __init__(self) -> None:
        try:
            import vlc
        except ImportError as error:
            raise RuntimeError(
                "Install the optional 'music' dependencies and system libVLC"
            ) from error
        self.vlc = vlc
        self.instance = vlc.Instance("--no-video")
        self.current = None
        self.current_volume = 0
        self.lock = threading.RLock()

    def _new_player(self, url: str):
        player = self.instance.media_player_new()
        player.set_media(self.instance.media_new(url))
        return player

    def play(self, url: str, volume: int) -> None:
        with self.lock:
            if self.current is not None:
                self.current.stop()
            self.current = self._new_player(url)
            self.current.audio_set_volume(int(volume))
            self.current.play()
            self.current_volume = int(volume)

    def crossfade(
        self,
        url: str,
        volume: int,
        duration_seconds: float,
    ) -> None:
        with self.lock:
            previous = self.current
            previous_volume = self.current_volume
            next_player = self._new_player(url)
            next_player.audio_set_volume(0)
            next_player.play()
            steps = max(1, int(round(duration_seconds * 5)))
            for step in range(1, steps + 1):
                fraction = step / steps
                next_player.audio_set_volume(int(volume * fraction))
                if previous is not None:
                    previous.audio_set_volume(
                        int(previous_volume * (1 - fraction))
                    )
                time.sleep(duration_seconds / steps)
            if previous is not None:
                previous.stop()
            self.current = next_player
            self.current_volume = int(volume)

    def overlay(self, url: str, volume: int) -> None:
        player = self._new_player(url)
        player.audio_set_volume(int(volume))
        player.play()

        def wait_and_release() -> None:
            time.sleep(1)
            while player.is_playing():
                time.sleep(0.5)
            player.stop()

        threading.Thread(target=wait_and_release, daemon=True).start()

    def fade_out(self, duration_seconds: float) -> None:
        with self.lock:
            if self.current is None:
                return
            start_volume = self.current_volume
            steps = max(1, int(round(duration_seconds * 5)))
            for step in range(1, steps + 1):
                self.current.audio_set_volume(
                    int(start_volume * (1 - step / steps))
                )
                time.sleep(duration_seconds / steps)
            self.current.stop()
            self.current = None
            self.current_volume = 0

    def stop(self) -> None:
        with self.lock:
            if self.current is not None:
                self.current.stop()
            self.current = None
            self.current_volume = 0
