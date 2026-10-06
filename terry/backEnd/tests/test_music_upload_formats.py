import wave

import numpy as np
import pytest
import soundfile as sf

from music_choices import normalize_wav
import asyncio
from fastapi import HTTPException
import music_choices


@pytest.mark.parametrize('subtype', ['PCM_U8', 'PCM_16', 'PCM_24', 'PCM_32', 'FLOAT', 'DOUBLE', 'IMA_ADPCM'])
def test_wav_encodings_normalized(tmp_path, subtype):
    source, target = tmp_path / 'source.wav', tmp_path / 'normalized.wav'
    sf.write(source, np.sin(np.arange(16000) * 0.1) * 0.3, 16000, subtype=subtype)
    normalize_wav(source, target)
    with wave.open(str(target)) as audio:
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 44100
        assert abs(audio.getnframes() / 44100 - 1) < 0.05


def test_multichannel_float_wav(tmp_path):
    source, target = tmp_path / 'source.wav', tmp_path / 'normalized.wav'
    sf.write(source, np.ones((48000, 6), dtype=np.float32) * 0.2, 48000, subtype='FLOAT')
    normalize_wav(source, target)
    with wave.open(str(target)) as audio:
        assert audio.getnchannels() == 1
        assert audio.getnframes() == 44100


def test_corrupt_wav_rejected(tmp_path):
    source = tmp_path / 'source.wav'
    source.write_bytes(b'not a wave file')
    with pytest.raises(sf.LibsndfileError):
        normalize_wav(source, tmp_path / 'normalized.wav')


def test_storage_quota_not_reported_as_file_size(tmp_path, monkeypatch):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    with (uploads / 'existing.wav').open('wb') as handle:
        handle.truncate(499_999_999)
    monkeypatch.setattr(music_choices, 'MUSIC_DIR', tmp_path)
    monkeypatch.setattr(music_choices, 'UPLOADS', uploads)
    class Request:
        headers = {'content-type': 'audio/wav'}

        async def stream(self):
            yield b'1234'

    with pytest.raises(HTTPException) as error:
        asyncio.run(music_choices.upload(Request()))
    assert error.value.status_code == 422
    assert '80MB' not in error.value.detail
