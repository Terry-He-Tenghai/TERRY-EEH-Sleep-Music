"""Local-only bounded WAV uploads, normalized separately from the catalog."""
import asyncio
import os
import re
import shutil
import uuid
import wave
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from music_library import MUSIC_DIR, Track, _audio_path, _read_manifest

router = APIRouter(prefix='/api/music', tags=['music'])
STYLES = {'ambient': '氛围 / 铺底', 'piano': '钢琴', 'nature': '自然环境', 'strings': '弦乐', 'electronic': '电子'}
UPLOADS = MUSIC_DIR / 'uploads'
lock = asyncio.Lock()


def normalize_wav(source, destination):
    with sf.SoundFile(source) as audio:
        if (audio.format not in ('WAV', 'WAVEX', 'RF64') or audio.frames <= 0
                or not 0 < audio.frames / audio.samplerate <= 900
                or audio.frames * audio.channels > 40_000_000):
            raise ValueError('Invalid or oversized WAV')
        rate = audio.samplerate
        samples = audio.read(dtype='float32', always_2d=True)
    if not np.isfinite(samples).all():
        raise ValueError('Nonfinite audio samples')
    if samples.shape[1] > 2:
        samples = samples.mean(axis=1, keepdims=True)
    if rate != 44100:
        divisor = gcd(rate, 44100)
        samples = resample_poly(samples, 44100 // divisor, rate // divisor)
    peak = float(np.max(np.abs(samples)))
    if peak > 1:
        samples /= peak
    with wave.open(str(destination), 'wb') as output:
        output.setnchannels(samples.shape[1])
        output.setsampwidth(2)
        output.setframerate(44100)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())


def uploaded(track_id):
    if not re.fullmatch(r'user_[a-f0-9]{32}', track_id):
        return None
    track = Track(id=track_id, title='用户上传音频', file=f'uploads/{track_id}.wav')
    return track if _audio_path(track) else None


def candidates(style):
    tracks, _ = _read_manifest()
    return [t for t in tracks if _audio_path(t) and (style == 'all' or style in t.styles)]


@router.get('/choices')
def choices():
    return {'styles': [{'id': 'all', 'label': '全部本地素材', 'count': len(candidates('all'))}] +
            [{'id': key, 'label': label, 'count': len(candidates(key))} for key, label in STYLES.items()]}


@router.post('/uploads')
async def upload(request: Request):
    # Browser sends a same-origin raw body, not a multipart filename or path.
    if request.headers.get('content-type', '').split(';')[0] not in ('audio/wav', 'audio/x-wav'):
        raise HTTPException(415, '请上传WAV文件')
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        host = urlsplit(origin).hostname
        if host not in ('localhost', '127.0.0.1', '::1'):
            raise HTTPException(403, '仅允许本机页面上传')
    async with lock:
        if MUSIC_DIR.is_symlink() or UPLOADS.is_symlink():
            raise HTTPException(400, '上传目录配置无效')
        UPLOADS.mkdir(parents=True, exist_ok=True)
        track_id = 'user_' + uuid.uuid4().hex
        temporary = UPLOADS / (track_id + '.part')
        final = UPLOADS / (track_id + '.wav')
        normalized = UPLOADS / (track_id + '.normalized')
        try:
            size = 0
            with temporary.open('xb') as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if shutil.disk_usage(UPLOADS).free < len(chunk) + 100_000_000:
                        raise HTTPException(507, '本地磁盘剩余空间不足，请释放磁盘空间')
                    handle.write(chunk)
            try:
                await asyncio.to_thread(normalize_wav, temporary, normalized)
            except (sf.LibsndfileError, wave.Error, EOFError, ValueError):
                raise HTTPException(422, 'WAV无法解码、已损坏或超过900秒/解码大小限制')
            os.replace(normalized, final)
            return {'id': track_id, 'title': '用户上传音频', 'audio_url': f'/api/music/{track_id}/audio'}
        finally:
            temporary.unlink(missing_ok=True)
            normalized.unlink(missing_ok=True)
