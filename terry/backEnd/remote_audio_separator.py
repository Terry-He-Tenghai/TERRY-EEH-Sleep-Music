"""CPU-only accompaniment service deployed next to ACE-Step over an SSH tunnel."""

import hashlib
import io
import os
from pathlib import Path
import threading
import logging
import time

os.environ.setdefault('TORCH_HOME', '/root/autodl-tmp/torch-cache')

import numpy as np
import soundfile as sf
import torch
from demucs.apply import apply_model
from demucs.audio import convert_audio
from demucs.pretrained import get_model
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

app = FastAPI()
CACHE = Path('/root/autodl-tmp/accompaniment-cache')
CACHE.mkdir(parents=True, exist_ok=True)
lock = threading.Lock()
model = None
logger = logging.getLogger('uvicorn.error')
torch.set_num_threads(6)


@app.get('/health')
def health():
    return {'status': 'ok', 'model': 'htdemucs', 'device': 'cpu', 'loaded': model is not None}


@app.post('/separate')
async def separate(request: Request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 80_000_000:
            raise HTTPException(413, 'Audio exceeds separation limit')
    # Run inference outside the ASGI event loop.
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(separate_audio, bytes(data))


def separate_audio(data):
    global model
    started = time.monotonic()
    try:
        samples, rate = sf.read(io.BytesIO(data), dtype='float32', always_2d=True)
    except Exception as exc:
        raise HTTPException(422, 'Invalid PCM audio') from exc
    if rate <= 0 or len(samples) == 0 or len(samples) / rate > 600.1 or samples.shape[1] > 2:
        raise HTTPException(422, 'Expected mono/stereo audio of at most 600 seconds')
    if not np.isfinite(samples).all():
        raise HTTPException(422, 'Non-finite audio samples')
    digest = hashlib.sha256(b'htdemucs-v1:' + data).hexdigest()
    path = CACHE / f'{digest}.wav'
    with lock:
        if not path.exists():
            if model is None:
                model = get_model('htdemucs').cpu().eval()
            audio = convert_audio(torch.from_numpy(samples.T.copy()), rate, model.samplerate, model.audio_channels)
            reference = audio.mean(0)
            mean, scale = reference.mean(), reference.std(unbiased=False).clamp_min(1e-6)
            with torch.inference_mode():
                stems = apply_model(model, ((audio - mean) / scale)[None], device='cpu',
                                    shifts=0, split=True, overlap=0.25, num_workers=0)[0]
            stems = stems * scale + mean
            accompaniment = stems[[i for i, name in enumerate(model.sources) if name != 'vocals']].sum(0)
            peak = accompaniment.abs().max().clamp_min(1.0)
            output = (accompaniment / peak).T.numpy()
            temporary = path.with_suffix('.tmp.wav')
            sf.write(temporary, output, model.samplerate, subtype='PCM_16')
            temporary.replace(path)
    logger.info('Accompaniment %s ready in %.2fs', digest[:12], time.monotonic() - started)
    return FileResponse(path, media_type='audio/wav', filename='accompaniment.wav')
