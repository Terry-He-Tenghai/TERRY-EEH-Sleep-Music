"""Read-only access to the 20 curated BabySlakh original WAV stem mixes.

The dataset contains more instruments than the browser mixer needs. Each track
therefore exposes four deterministic, non-drum stems assigned to the mixer's
piano, strings, bass, and pad controls. Metadata and original files remain
read-only; MIDI is never read, generated, or modified here.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import stat
from typing import Any, Literal
import wave

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

StemTrackId = Literal[
    'Track00001', 'Track00002', 'Track00003', 'Track00004', 'Track00005',
    'Track00006', 'Track00007', 'Track00008', 'Track00009', 'Track00010',
    'Track00011', 'Track00012', 'Track00013', 'Track00014', 'Track00015',
    'Track00016', 'Track00017', 'Track00018', 'Track00019', 'Track00020',
]
DEFAULT_ROOT = Path(__file__).absolute().parents[1] / 'assest' / 'babyslakh_16k.tar' / 'babyslakh_16k'

# Four deterministic stems per track. The role is the browser mix-control
# target, not a claim that the source instrument is literally that role.
# The original validation tracks are included in the same 20-track catalog.
CURATED: dict[str, dict[str, str]] = {
    'Track00001': {'S03': 'bass', 'S02': 'piano', 'S04': 'strings', 'S05': 'pad'},
    'Track00002': {'S01': 'bass', 'S06': 'piano', 'S00': 'strings', 'S03': 'pad'},
    'Track00003': {'S01': 'bass', 'S00': 'piano', 'S02': 'strings', 'S07': 'pad'},
    'Track00004': {'S01': 'bass', 'S06': 'piano', 'S05': 'strings', 'S00': 'pad'},
    'Track00005': {'S04': 'bass', 'S02': 'piano', 'S11': 'strings', 'S01': 'pad'},
    'Track00006': {'S03': 'bass', 'S01': 'piano', 'S04': 'strings', 'S02': 'pad'},
    'Track00007': {'S02': 'bass', 'S01': 'piano', 'S06': 'strings', 'S05': 'pad'},
    'Track00008': {'S00': 'bass', 'S02': 'piano', 'S04': 'strings', 'S06': 'pad'},
    'Track00009': {'S06': 'bass', 'S00': 'piano', 'S04': 'strings', 'S10': 'pad'},
    'Track00010': {'S00': 'bass', 'S05': 'piano', 'S01': 'strings', 'S03': 'pad'},
    'Track00011': {'S01': 'bass', 'S02': 'piano', 'S03': 'strings', 'S00': 'pad'},
    'Track00012': {'S05': 'bass', 'S03': 'piano', 'S06': 'strings', 'S01': 'pad'},
    'Track00013': {'S00': 'bass', 'S03': 'piano', 'S04': 'strings', 'S06': 'pad'},
    'Track00014': {'S01': 'bass', 'S05': 'piano', 'S03': 'strings', 'S00': 'pad'},
    'Track00015': {'S04': 'bass', 'S00': 'piano', 'S03': 'strings', 'S01': 'pad'},
    'Track00016': {'S01': 'bass', 'S00': 'piano', 'S04': 'strings', 'S06': 'pad'},
    'Track00017': {'S03': 'bass', 'S08': 'piano', 'S02': 'strings', 'S01': 'pad'},
    'Track00018': {'S15': 'bass', 'S07': 'piano', 'S03': 'strings', 'S10': 'pad'},
    'Track00019': {'S08': 'bass', 'S01': 'piano', 'S00': 'strings', 'S14': 'pad'},
    'Track00020': {'S01': 'bass', 'S02': 'pad', 'S03': 'piano', 'S05': 'strings'},
}
router = APIRouter(prefix='/api/stem-music', tags=['stem-music'])


def _root() -> Path:
    return Path(os.environ.get('TERRY_BABYSLAKH_ROOT') or DEFAULT_ROOT).expanduser().absolute()


def _safe_file(path: Path) -> Path:
    # Check before resolving: resolve() alone would hide linked ancestors.
    if '..' in path.parts:
        raise ValueError('Parent traversal is forbidden')
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise ValueError('Linked paths are forbidden')
    if not path.is_file():
        raise ValueError('Not a regular file')
    return path


def _stem_path(track_id: str, stem_id: str) -> Path:
    if track_id not in CURATED or stem_id not in CURATED[track_id]:
        raise ValueError('Unknown curated stem')
    return _safe_file(_root() / track_id / 'stems' / f'{stem_id}.wav')


def _wav_header(path: Path) -> dict[str, Any]:
    with wave.open(str(path), 'rb') as audio:
        frames, rate, channels = audio.getnframes(), audio.getframerate(), audio.getnchannels()
        if frames <= 0 or rate <= 0 or channels not in (1, 2):
            raise ValueError('Unsupported or empty WAV')
        return {'duration_seconds': frames / rate, 'sample_rate_hz': rate, 'channels': channels}


def get_track(track_id: str) -> dict[str, Any] | None:
    """Return a track only when all four curated stems exist and are aligned."""
    if track_id not in CURATED:
        return None
    try:
        stems = [
            {'id': stem_id, 'role': role, **_wav_header(_stem_path(track_id, stem_id)),
             'url': f'/api/stem-music/{track_id}/stems/{stem_id}/audio'}
            for stem_id, role in CURATED[track_id].items()
        ]
        first = stems[0]
        if any(s['sample_rate_hz'] != first['sample_rate_hz'] or
               abs(s['duration_seconds'] - first['duration_seconds']) > 1 / first['sample_rate_hz']
               for s in stems):
            return None
        return {'id': track_id, 'title': f'BabySlakh {track_id}',
                'duration_seconds': first['duration_seconds'],
                'sample_rate_hz': first['sample_rate_hz'], 'channels': first['channels'],
                'stems': stems}
    except (OSError, ValueError, wave.Error, EOFError):
        return None


@router.get('')
def list_tracks() -> dict[str, Any]:
    tracks = [track for track_id in CURATED if (track := get_track(track_id)) is not None]
    return {'tracks': tracks}


@router.get('/{track_id}/stems/{stem_id}/audio')
def stem_audio(track_id: str, stem_id: str) -> FileResponse:
    try:
        path = _stem_path(track_id, stem_id)
        _wav_header(path)
    except (OSError, ValueError, wave.Error, EOFError):
        raise HTTPException(404, 'Curated stem unavailable') from None
    return FileResponse(path, media_type='audio/wav')


def project_stem_mix(track_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
    """Project existing validated controls, never infer or invent EEG state."""
    if event.get('status') != 'ready' or event.get('track_status') != 'available':
        return None
    mode = event.get('playback_mode')
    if mode == 'conservative':
        level = None
        gains = {'piano': .12, 'strings': .08, 'bass': .02, 'pad': .10}
        brightness = .15
    elif mode in ('adaptive', 'demo_scripted'):
        if mode == 'demo_scripted' and not (
            event.get('source') == 'DEMO'
            and event.get('inference_mode') == 'demo_scripted'
            and event.get('demo_scripted') is True
            and event.get('probability_origin') == 'scripted_not_model'
        ):
            return None
        level = (event.get('modulation') or {}).get('control_level')
        if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(level) or not 0 <= level <= 1:
            return None
        gains = {'piano': .18 + .52 * level, 'strings': .32 - .20 * level,
                 'bass': .04 + .28 * level, 'pad': .28 - .20 * level}
        brightness = .15 + .65 * level
    else:
        return None
    return {'track_id': track_id, 'mode': mode, 'control_level': level,
            'gains': gains, 'brightness': brightness, 'transition_seconds': 3.0}
