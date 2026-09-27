from __future__ import annotations

from typing import Protocol

from .contracts import MusicCommand, StateUpdate


class MusicController(Protocol):
    """Adapter boundary for a future music generation or playback service."""

    def update(self, state: StateUpdate) -> MusicCommand:
        """Translate a model state into one transport-neutral music command."""


class NoOpMusicController:
    """Safe default: expose the interface without changing any music."""

    def update(self, state: StateUpdate) -> MusicCommand:
        return MusicCommand(
            action="none",
            parameters={},
            reason=(
                "music integration is intentionally disabled"
                if state.status == "ok"
                else f"no action while state is {state.status}"
            ),
        )
