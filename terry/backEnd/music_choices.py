"""Local-only bounded PCM WAV uploads, separate from the trusted Suno manifest."""
import asyncio
import os
import re
import uuid
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from music_library import MUSIC_DIR, Track, _audio_path, _read_manifest

router = APIRouter(prefix='/api/music', tags=['music'])
STYLES = {'ambient': '氛围 / 铺底', 'piano': '钢琴', 'nature': '自然环境', 'strings': '弦乐', 'electronic': '电子'}
UPLOADS = MUSIC_DIR / 'uploads'
LIMIT = 80_000_000
lock = asyncio.Lock()


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
        raise HTTPException(415, '请上传PCM WAV文件')
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
        files = list(UPLOADS.glob('*'))
        used = sum(p.stat().st_size for p in files if p.is_file())
        if len(files) >= 20 or used >= 500_000_000:
            raise HTTPException(413, '本地上传空间已满，请先清理music/uploads')
        track_id = 'user_' + uuid.uuid4().hex
        temporary = UPLOADS / (track_id + '.part')
        final = UPLOADS / (track_id + '.wav')
        try:
            size = 0
            with temporary.open('xb') as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > LIMIT or used + size > 500_000_000:
                        raise HTTPException(413, '音频不能超过80MB')
                    handle.write(chunk)
            try:
                with wave.open(str(temporary), 'rb') as audio:
                    frames, rate = audio.getnframes(), audio.getframerate()
                    if (audio.getcomptype() != 'NONE' or audio.getnchannels() not in (1, 2)
                            or audio.getsampwidth() not in (1, 2, 3, 4) or not 8000 <= rate <= 96000
                            or not 8 <= frames / rate <= 900):
                        raise ValueError('unsupported audio')
                    expected = frames * audio.getnchannels() * audio.getsampwidth()
                    actual = 0
                    while data := audio.readframes(16384):
                        actual += len(data)
                    if actual != expected:
                        raise ValueError('truncated audio')
            except (wave.Error, EOFError, ValueError):
                raise HTTPException(422, '需要完整的8–900秒、单/双声道PCM WAV音频')
            os.replace(temporary, final)
            return {'id': track_id, 'title': '用户上传音频', 'audio_url': f'/api/music/{track_id}/audio'}
        finally:
            temporary.unlink(missing_ok=True)
