from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class MotifVariation(str, Enum):
    COMPLETE = "complete"
    REDUCED = "reduced"
    EXTENDED = "extended"
    OCTAVE = "octave"


@dataclass(frozen=True)
class MidiNote:
    """A deterministic symbolic note expressed in beats."""

    start_beat: float
    duration_beats: float
    midi_note: int
    velocity: int
    voice: str
    phrase: int

    def validate(self) -> None:
        if self.start_beat < 0 or self.duration_beats <= 0:
            raise ValueError("MIDI note timing must be non-negative and non-zero")
        if not 0 <= self.midi_note <= 127:
            raise ValueError("MIDI note must be between 0 and 127")
        if not 1 <= self.velocity <= 127:
            raise ValueError("MIDI velocity must be between 1 and 127")


@dataclass(frozen=True)
class MIDIQualityReport:
    note_count: int
    density_notes_per_bar: float
    out_of_scale: int
    large_intervals: int
    out_of_range: int
    duplicate_starts: int

    @property
    def passes(self) -> bool:
        return self.out_of_scale == 0 and self.out_of_range == 0


# C major / A natural minor pitch classes.  The harmony is intentionally
# fixed so that the same EEG replay and seed produce the same arrangement.
_SCALE = {0, 2, 4, 5, 7, 9, 11}
_CHORDS = (
    (60, 64, 67),  # C
    (57, 60, 64),  # Am
    (53, 57, 60),  # F
    (55, 59, 62),  # G
)
_MOTIF = (0, 2, 4, 2, 1, 0, 2, 4)
_SCALE_PITCHES = (0, 2, 4, 5, 7, 9, 11)


def _voice_note(pitch: int, start: float, duration: float, voice: str, phrase: int, velocity: int) -> MidiNote:
    note = MidiNote(start, duration, pitch, velocity, voice, phrase)
    note.validate()
    return note


def _nearest_pitch(target: int, chord: tuple[int, ...], low: int = 48, high: int = 96) -> int:
    """Keep a scale tone close to the current chord and playable register."""
    candidates = [pitch + 12 * octave for pitch in chord for octave in range(-3, 5)]
    candidates = [pitch for pitch in candidates if low <= pitch <= high]
    return min(candidates, key=lambda pitch: abs(pitch - target))


def generate_midi_plan(
    state: str = "M1",
    seed: int = 42,
    bars: int = 4,
    variation: MotifVariation | str | None = None,
    phrase_index: int = 0,
) -> list[MidiNote]:
    """Generate a deterministic, evolving arrangement for one 16-beat phrase.

    The progression, bass pulse, chord-tone melody, and phrase-indexed motif
    rotation are deliberately bounded.  A new phrase can therefore sound
    related without repeating the exact same four bars forever.
    """
    if bars <= 0:
        raise ValueError("bars must be positive")
    if phrase_index < 0:
        raise ValueError("phrase_index must be non-negative")
    state = str(state).upper()
    if state not in {"M1", "M2", "M3"}:
        raise ValueError("state must be M1, M2, or M3")
    if variation is None:
        variation = {
            "M1": MotifVariation.COMPLETE,
            "M2": MotifVariation.REDUCED,
            "M3": MotifVariation.REDUCED,
        }[state]
    variation = MotifVariation(variation)
    rotation = (int(seed) + phrase_index * 3) % len(_MOTIF)
    notes: list[MidiNote] = []
    previous_melody_pitch: int | None = None
    for bar in range(bars):
        phrase = bar // 2
        bar_start = float(bar * 4)
        chord = _CHORDS[(bar + phrase_index) % len(_CHORDS)]
        if state != "M3":
            # A sustained pad plus a two-beat bass pulse gives the MIDI layer
            # an audible harmonic floor instead of a single isolated bass note.
            notes.extend(_voice_note(pitch, bar_start, 4.0, "pad", phrase, 42) for pitch in chord)
            bass_root, bass_fifth = chord[0] - 12, chord[2] - 12
            for beat, pitch in ((0.0, bass_root), (2.0, bass_fifth)):
                notes.append(_voice_note(pitch, bar_start + beat, 1.75, "bass", phrase, 64))
        if state == "M3":
            continue
        if variation == MotifVariation.REDUCED:
            rhythm = (0.0, 1.0, 2.0, 3.0)
        elif variation == MotifVariation.EXTENDED:
            rhythm = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)
        else:
            rhythm = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)
        for local_index, start_offset in enumerate(rhythm):
            motif_value = _MOTIF[(local_index + rotation + bar) % len(_MOTIF)]
            degree = (motif_value + bar + (phrase_index % 3)) % len(_SCALE_PITCHES)
            target = 72 + _SCALE_PITCHES[degree]
            # Beat starts favor chord tones; off-beats retain scale-step motion.
            if start_offset in (0.0, 2.0):
                target = _nearest_pitch(target, chord)
            if variation == MotifVariation.OCTAVE and local_index % 2:
                target -= 12
            if previous_melody_pitch is not None:
                candidates = [target + 12 * shift for shift in range(-3, 4)]
                candidates = [pitch for pitch in candidates if 48 <= pitch <= 96]
                target = min(candidates, key=lambda pitch: abs(pitch - previous_melody_pitch))
                if abs(target - previous_melody_pitch) > 7:
                    # At register edges an octave-equivalent pitch can still
                    # jump too far. Prefer a nearby chord tone on strong beats.
                    allowed = {p % 12 for p in chord} if start_offset in (0.0, 2.0) else _SCALE
                    target = min((p for p in range(48, 97)
                                  if p % 12 in allowed and abs(p - previous_melody_pitch) <= 7),
                                 key=lambda p: abs(p - target))
            previous_melody_pitch = target
            duration = 0.42 if variation != MotifVariation.EXTENDED else 0.62
            velocity = 72 if start_offset in (0.0, 2.0) else 60
            notes.append(_voice_note(target, bar_start + start_offset, duration, "melody", phrase, velocity))
    return sorted(notes, key=lambda note: (note.start_beat, note.voice, note.midi_note))


def quality_report(notes: Iterable[MidiNote], bars: int | None = None) -> MIDIQualityReport:
    """Calculate inexpensive musical safety metrics for an arrangement."""
    values = list(notes)
    for note in values:
        note.validate()
    melody = [note for note in values if note.voice == "melody"]
    ordered = sorted(melody, key=lambda note: note.start_beat)
    large_intervals = sum(
        abs(current.midi_note - previous.midi_note) > 7
        for previous, current in zip(ordered, ordered[1:])
    )
    duplicate_starts = len(ordered) - len({note.start_beat for note in ordered})
    out_of_scale = sum(note.midi_note % 12 not in _SCALE for note in melody)
    out_of_range = sum(
        not 48 <= note.midi_note <= 96
        for note in values
        if note.voice == "melody"
    )
    max_beat = max((note.start_beat for note in values), default=0.0)
    inferred_bars = bars or max(1, int(max_beat // 4) + 1)
    return MIDIQualityReport(
        note_count=len(values),
        density_notes_per_bar=len(melody) / inferred_bars,
        out_of_scale=out_of_scale,
        large_intervals=large_intervals,
        out_of_range=out_of_range,
        duplicate_starts=duplicate_starts,
    )


def _variable_length(value: int) -> bytes:
    buffer = value & 0x7F
    encoded = bytearray([buffer])
    while value > 0x7F:
        value >>= 7
        buffer = (value & 0x7F) | 0x80
        encoded.insert(0, buffer)
    return bytes(encoded)


def write_midi_file(
    notes: Iterable[MidiNote],
    path: str | Path,
    bpm: int = 60,
    ticks_per_beat: int = 480,
) -> Path:
    """Write notes as a standard type-0 MIDI file using only the stdlib."""
    if bpm <= 0 or ticks_per_beat <= 0:
        raise ValueError("bpm and ticks_per_beat must be positive")
    ordered = sorted(notes, key=lambda note: (note.start_beat, note.voice, note.midi_note))
    events: list[tuple[int, bytes]] = [(0, b"\xff\x51\x03" + struct.pack(">I", 60_000_000 // bpm)[1:])]
    for note in ordered:
        start = int(round(note.start_beat * ticks_per_beat))
        end = int(round((note.start_beat + note.duration_beats) * ticks_per_beat))
        events.extend([(start, bytes([0x90, note.midi_note, note.velocity])), (end, bytes([0x80, note.midi_note, 0]))])
    events.sort(key=lambda item: (item[0], item[1][0] == 0x90))
    track = bytearray()
    previous_tick = 0
    for tick, message in events:
        track.extend(_variable_length(max(0, tick - previous_tick)))
        track.extend(message)
        previous_tick = tick
    track.extend(b"\x00\xff\x2f\x00")
    payload = b"MThd" + struct.pack(">IHHH", 6, 0, 1, ticks_per_beat)
    payload += b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination
