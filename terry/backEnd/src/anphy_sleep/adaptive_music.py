"""EEG-to-music target policy and deterministic local track selection.

Consumes StateUpdate without changing EEG preprocessing. Targets require a
separate player adapter; producing a target does not itself play audio.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from .contracts import StateUpdate
from .music_engine.layers import MusicState
from .music_engine.midi import MotifVariation


class SunoRole(str, Enum):
    WARM_PAD = "warm_pad"
    TRANSITION = "transition"
    MINIMAL_DRONE = "minimal_drone"
    REPAIR = "repair"


@dataclass(frozen=True)
class AdaptiveMusicTarget:
    role: SunoRole
    state: MusicState
    variation: MotifVariation
    melody_gain: float
    bass_gain: float
    brightness: float
    transition_seconds: float
    reason: str


class AdaptiveMusicPolicy:
    """Initial engineering mapping, not a validated clinical sleep policy."""

    def __init__(self, minimum_signal_quality: float = .75):
        self.minimum_signal_quality = minimum_signal_quality

    def target(self, update: StateUpdate) -> AdaptiveMusicTarget:
        if update.status != "ok" or update.signal_quality < self.minimum_signal_quality:
            return AdaptiveMusicTarget(
                SunoRole.REPAIR, MusicState.M2, MotifVariation.REDUCED,
                .08, .10, .20, 8., f"freeze or repair: signal status={update.status}"
            )
        probabilities = update.aasm_state_probabilities or {}
        n2 = float(probabilities.get("N2", 0.))
        n1 = float(probabilities.get("N1", 0.))
        future = float(update.n2_within_5m_probability or 0.)
        if n2 >= .65:
            return AdaptiveMusicTarget(
                SunoRole.MINIMAL_DRONE, MusicState.M3, MotifVariation.EXTENDED,
                0., .08, .14, 12., "stable N2: minimal drone and extended tones"
            )
        if n1 >= .55 or future >= .65:
            return AdaptiveMusicTarget(
                SunoRole.TRANSITION, MusicState.M2, MotifVariation.REDUCED,
                .16, .18, .30, 8., "transition likelihood: reduce density and brightness"
            )
        return AdaptiveMusicTarget(
            SunoRole.WARM_PAD, MusicState.M1, MotifVariation.COMPLETE,
            .34, .26, .50, 6., "wake/high uncertainty: retain predictable full arrangement"
        )


def select_suno_track(
    tracks: Iterable[Mapping[str, object]],
    role: SunoRole,
    *,
    used_ids: set[str] | None = None,
) -> Mapping[str, object] | None:
    """Choose by role/purpose tags with stable ordering and a repeat fallback.

    Availability is supplied by the catalog adapter; this helper does not verify
    files. Explicit adaptive_role requires catalog schema support before use.
    """
    used_ids = used_ids or set()
    keywords = {
        SunoRole.WARM_PAD: ("warm_pad", "pad", "铺底"),
        SunoRole.TRANSITION: ("transition", "m2", "过渡"),
        SunoRole.MINIMAL_DRONE: ("minimal_drone", "m3", "极简", "drone"),
        SunoRole.REPAIR: ("repair", "texture", "修复", "纹理"),
    }[role]
    candidates = []
    for track in tracks:
        if track.get("available") is False:
            continue
        text = " ".join(
            str(track.get(key, "")).lower()
            for key in ("adaptive_role", "purpose", "title")
        )
        if any(keyword in text for keyword in keywords):
            candidates.append(track)
    if not candidates:
        return None
    fresh = [track for track in candidates if str(track.get("id", "")) not in used_ids]
    return sorted(fresh or candidates, key=lambda item: str(item.get("id", "")))[0]
