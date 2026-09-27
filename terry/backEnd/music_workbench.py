"""Bounded manual symbolic arrangements; never renders or plays audio.

M3 has no symbolic notes. Its nonzero pad/texture gains describe independent
browser audio layers (including a selected local Suno pad), not MIDI voices.
Note ``phrase`` retains the generator's eight-beat motif grouping; the
sixteen-beat ``phrase_beats`` is the scheduler/control phrase duration.
"""
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from anphy_sleep.music_engine.layers import MusicState, preset_gains
from anphy_sleep.music_engine.midi import generate_midi_plan, quality_report, write_midi_file
from anphy_sleep.music_engine.scheduler import MusicScheduler

router = APIRouter(prefix="/api/music-workbench", tags=["music-workbench"])
Variation = Literal["auto", "complete", "reduced", "extended", "octave"]


def arrangement(
    state: Literal["M1", "M2", "M3"] = "M1",
    seed: Annotated[int, Query(ge=0, le=2147483647)] = 42,
    bars: Annotated[int, Query(ge=4, le=4)] = 4,
    variation: Variation = "auto",
    transpose: Annotated[int, Query(ge=-12, le=12)] = 0,
) -> dict:
    """Shared validated plan for JSON and MIDI; bounded to sixteen beats."""
    resolved = ("complete" if state == "M1" else "reduced") if variation == "auto" else variation
    total_beats = bars * 4
    notes = [replace(note, midi_note=note.midi_note + transpose,
                     duration_beats=min(note.duration_beats, total_beats - note.start_beat))
             for note in generate_midi_plan(state, seed, bars, resolved)
             if note.start_beat < total_beats]
    if any(not 0 <= note.midi_note <= 127 for note in notes):
        raise HTTPException(status_code=422, detail="Transposition exceeds the legal MIDI pitch range")
    # quality_report assumes untransposed C major. Recompute pitch-class
    # membership against the shifted scale, retaining actual register checks.
    scale = sorted({(pitch + transpose) % 12 for pitch in (0, 2, 4, 5, 7, 9, 11)})
    report = replace(quality_report(notes, bars), out_of_scale=sum(
        note.midi_note % 12 not in scale for note in notes if note.voice == "melody"
    ))
    return {
        "state": state, "seed": seed, "bars": bars,
        "variation": variation, "resolved_variation": resolved, "transpose": transpose,
        "bpm": 60, "beats_per_bar": 4, "phrase_beats": 16, "total_beats": total_beats,
        "gains": preset_gains(state).as_dict(),
        "waveform": asdict(MusicScheduler()._waveform(MusicState(state))),
        "notes": [asdict(note) for note in notes],
        "midi_quality": {**asdict(report), "passes": report.passes,
                         "scope": "transposed_plan", "scale_pitch_classes": scale},
    }


@router.get("/plan")
def plan(response: Response, data: dict = Depends(arrangement)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return data


@router.get("/midi")
def midi(data: dict = Depends(arrangement)) -> Response:
    from anphy_sleep.music_engine.midi import MidiNote

    # Read bytes before leaving the scope: no leaked files or deferred reads.
    with TemporaryDirectory(prefix="terry-music-workbench-") as directory:
        path = write_midi_file([MidiNote(**note) for note in data["notes"]],
                               Path(directory) / "arrangement.mid", bpm=data["bpm"])
        payload = path.read_bytes()
    filename = (f"terry-{data['state']}-seed{data['seed']}-{data['bars']}bars-"
                f"{data['resolved_variation']}-transpose{data['transpose']}.mid")
    return Response(payload, media_type="audio/midi", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "Access-Control-Expose-Headers": "Content-Disposition",
    })
