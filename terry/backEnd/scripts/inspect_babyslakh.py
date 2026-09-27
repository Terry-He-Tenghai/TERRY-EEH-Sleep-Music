"""Read-only BabySlakh inventory; never infers genre or changes source audio.

Run with the project's Python (PyYAML is already a dependency).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import wave

import yaml


def wav_info(path: Path) -> dict:
    try:
        with wave.open(str(path), 'rb') as audio:
            return {'file': path.name, 'seconds': round(audio.getnframes() / audio.getframerate(), 3),
                    'sample_rate': audio.getframerate(), 'channels': audio.getnchannels(),
                    'frames': audio.getnframes()}
    except (OSError, wave.Error, EOFError) as exc:
        return {'file': path.name, 'error': str(exc)}


def inspect(root: Path) -> dict:
    tracks = []
    for directory in sorted(root.glob('Track*')):
        if not directory.is_dir():
            continue
        metadata_path = directory / 'metadata.yaml'
        if not metadata_path.is_file():
            tracks.append({'track': directory.name, 'error': 'metadata.yaml missing'})
            continue
        metadata = yaml.safe_load(metadata_path.read_text(encoding='utf-8'))
        stems = []
        for stem_id, info in metadata.get('stems', {}).items():
            audio = directory / 'stems' / f'{stem_id}.wav'
            midi = directory / 'MIDI' / f'{stem_id}.mid'
            stems.append({'id': stem_id, 'instrument': info.get('midi_program_name'),
                          'class': info.get('inst_class'), 'drums': info.get('is_drum'),
                          'plugin': info.get('plugin_name'),
                          'wav': wav_info(audio) if audio.is_file() else None,
                          'midi_exists': midi.is_file()})
        mixtures = [wav_info(p) for p in sorted(directory.glob('*.wav'))]
        tracks.append({'track': directory.name, 'mixtures': mixtures, 'stems': stems,
                       'midi_files': [p.relative_to(directory).as_posix() for p in sorted(directory.rglob('*.mid'))],
                       'genre': 'unverified; instrument labels are not genre annotations'})
    return {'root': str(root.resolve()), 'track_count': len(tracks), 'tracks': tracks,
            'scope': 'Metadata, actual file existence and WAV headers only; not a listening or full integrity test.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error('Dataset directory does not exist')
    print(json.dumps(inspect(args.root), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
