"""Run beside the pinned SongEval checkout, inside its isolated conda environment."""
import asyncio
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import librosa
import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, Request
from hydra.utils import instantiate
from muq import MuQ
from omegaconf import OmegaConf
from safetensors.torch import load_file

ROOT = Path(os.environ.get('SONGEVAL_ROOT', '/root/autodl-tmp/SongEval'))
app = FastAPI(title='SongEval private audio evaluator')
lock = threading.Lock()
model = encoder = None
revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
checkpoint_sha = hashlib.sha256((ROOT / 'ckpt/model.safetensors').read_bytes()).hexdigest()
KEYS = ('coherence', 'musicality', 'memorability', 'structure_clarity', 'vocal_naturalness')
ENCODER_REVISION = '0562a57814f6f8bbd9fdea0a25921a2fce1a841a'


@app.get('/health')
def health():
    return {'status': 'ready' if encoder is not None else 'loading', 'model': 'SongEval',
            'revision': revision, 'device': 'cpu', 'busy': lock.locked()}


@app.on_event('startup')
def load():
    global model, encoder
    torch.set_num_threads(4)
    model = instantiate(OmegaConf.load(ROOT / 'config.yaml').generator).eval()
    model.load_state_dict(load_file(ROOT / 'ckpt/model.safetensors'), strict=True)
    encoder = MuQ.from_pretrained('OpenMuQ/MuQ-large-msd-iter', revision=ENCODER_REVISION).eval()


@app.post('/evaluate')
async def evaluate(request: Request):
    if not lock.acquire(blocking=False):
        raise HTTPException(409, 'SongEval is busy; retry after the current evaluation')
    try:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / 'audio.wav'
            size = 0
            with path.open('wb') as output:
                stream = request.stream().__aiter__()
                while True:
                    try:
                        chunk = await asyncio.wait_for(anext(stream), timeout=30)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError as exc:
                        raise HTTPException(408, 'Audio upload stalled; retry with a stable connection') from exc
                    size += len(chunk)
                    if size > 400 * 1024 * 1024:
                        raise HTTPException(413, 'Audio exceeds 400 MB')
                    output.write(chunk)
            return await asyncio.to_thread(score, path)
    finally:
        lock.release()


def score(path):
    started = time.monotonic()
    try:
        with sf.SoundFile(path) as audio:
            if audio.format != 'WAV' or audio.channels not in (1, 2) or audio.frames <= 0:
                raise ValueError('Expected nonempty mono/stereo WAV')
            duration = audio.frames / audio.samplerate
            # Bounded, reproducible coverage; never call excerpts a whole-session evaluation.
            intervals = [(0., duration)] if duration <= 30 else [
                (0., 30.), ((duration - 30) / 2, (duration + 30) / 2), (duration - 30, duration)]
            if duration <= 90:
                intervals = [(s, min(s + 30, duration)) for s in np.arange(0, duration, 30)]
            results = []
            with torch.inference_mode():
                for start, end in intervals:
                    audio.seek(round(start * audio.samplerate))
                    wav = audio.read(round((end - start) * audio.samplerate), dtype='float32', always_2d=True).mean(axis=1)
                    if not np.isfinite(wav).all():
                        raise ValueError('Nonfinite audio samples')
                    wav = librosa.resample(wav, orig_sr=audio.samplerate, target_sr=24000)
                    features = encoder(torch.from_numpy(wav).unsqueeze(0), output_hidden_states=True)['hidden_states'][6]
                    values = model(features).squeeze(0).tolist()
                    if len(values) != 5 or any(not np.isfinite(v) or not 1 <= v <= 5 for v in values):
                        raise ValueError('Invalid SongEval output')
                    results.append(dict(start_s=float(start), end_s=float(end), scores=dict(zip(KEYS, values))))
        return {'status': 'completed', 'audio_analyzed': True, 'model': 'SongEval', 'model_version': revision,
                'checkpoint_sha256': checkpoint_sha, 'encoder': 'OpenMuQ/MuQ-large-msd-iter',
                'encoder_revision': ENCODER_REVISION,
                'score_range': [1, 5], 'method': 'CPU MuQ hidden_states[6]; <=30s segments; duration-weighted mean v1',
                'coverage_scope': 'All uploaded audio in segments' if duration <= 90 else 'First, middle, last 30s excerpts only',
                'uploaded_duration_s': duration, 'analyzed_audio_seconds': sum(r['end_s']-r['start_s'] for r in results),
                'segments': results, 'scores': {k: float(np.average([r['scores'][k] for r in results],
                    weights=[r['end_s']-r['start_s'] for r in results])) for k in KEYS},
                'elapsed_s': time.monotonic()-started,
                'limitations': ['Song-trained model; instrumental sleep music is out of validated scope',
                                'Vocal naturalness is not transition naturalness',
                                'Segment aggregation differs from official full-song inference']}
    except (ValueError, RuntimeError, sf.LibsndfileError) as exc:
        raise HTTPException(422, str(exc)) from exc
