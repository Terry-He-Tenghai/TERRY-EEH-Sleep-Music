"""Session evidence, not clinical outcomes or physical-output measurements."""
from copy import deepcopy
from pathlib import Path
import json
import threading
import time
import uuid

import numpy as np
import soundfile as sf
from scipy import signal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

ROOT = Path(__file__).parent / 'session_reports'
router = APIRouter(prefix='/api/session-reports', tags=['session-reports'])


class Reports:
    def __init__(self, root=ROOT):
        self.root = root
        self.lock = threading.RLock()
        self.current = None
        self.last_window = None
        self.n2_count = 0

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{self.current['id']}.json"
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.current, ensure_ascii=False, allow_nan=False), encoding='utf8')
        temporary.replace(path)

    def start(self, metadata):
        with self.lock:
            self.current = dict(id=uuid.uuid4().hex, started_at_s=time.time(), ended_at_s=None,
                                end_reason=None, metadata=metadata, windows=[], browser=None,
                                audio=None, limitations=['Browser PCM is digital output, not speaker output.',
                                'No hardware loopback latency or ear-level SPL measurement.',
                                'Scores are not calibrated sleep probabilities; no clinical sleep claim.',
                                'Risk screens do not establish comfort; blinded listening is required.'])
            self.last_window = None
            self.n2_count = 0
            self.save()
            return self.current['id']

    def observe(self, event):
        with self.lock:
            if not self.current or self.current['ended_at_s'] is not None:
                return False
            # Terminal/plan-only events repeat the previous window; never count them again.
            end = event.get('timestamp_s')
            if end is None or end == self.last_window or event.get('status') in ('stopped', 'error'):
                return False
            self.last_window = end
            fields = ['session_id', 'sequence', 'timestamp_s', 'emitted_at_s', 'status', 'reason',
                      'source', 'probabilities', 'signal_quality', 'channel_repair', 'waveform_model',
                      'interpretable_features', 'classification_confirmed', 'demo_scripted',
                      'classification_ms', 'band_power_uv2', 'current_music_state', 'stem_mix',
                      'waveform', 'gains', 'inference_mode']
            self.current['windows'].append({key: deepcopy(event.get(key)) for key in fields})
            probs = event.get('probabilities') or {}
            valid = (event.get('source') == 'LIVE' and event.get('classification_confirmed')
                     and event.get('signal_quality', 0) == 1 and bool(probs))
            self.n2_count = self.n2_count + 1 if valid and max(probs, key=probs.get) == 'N2' else 0
            self.save()
            return self.n2_count >= 2

    def finish(self, reason, received_seconds):
        with self.lock:
            if self.current and self.current['ended_at_s'] is None:
                self.current.update(ended_at_s=time.time(), end_reason=reason,
                                    received_seconds=received_seconds)
                windows = self.current['windows']
                evaluated = [w for w in windows if w.get('signal_quality') is not None]
                self.current['eeg_summary'] = dict(
                    duration_s=self.current['ended_at_s'] - self.current['started_at_s'],
                    evaluated_windows=len(evaluated),
                    qualified_window_ratio=(sum(w['signal_quality'] == 1 for w in evaluated) / len(evaluated)
                                            if evaluated else None),
                    ratio_scope='evaluated windows, overlapping; not sample-duration coverage',
                    packet_loss=None, packet_loss_reason='not yet aggregated from hardware packet IDs')
                self.save()

    def load(self, identifier):
        if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise HTTPException(404, 'Report not found')
        path = self.root / f'{identifier}.json'
        if not path.exists():
            raise HTTPException(404, 'Report not found')
        return json.loads(path.read_text(encoding='utf8'))

    def attach(self, identifier, key, value):
        with self.lock:
            report = self.load(identifier)
            report[key] = value
            report['trace'] = build_trace(report)
            path = self.root / f'{identifier}.json'
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False), encoding='utf8')
            temporary.replace(path)
            if self.current and self.current['id'] == identifier:
                self.current = report


reports = Reports()


def build_trace(report):
    browser = report.get('browser') or {}
    windows = {window['sequence']: window for window in report.get('windows', [])}
    metrics = ((report.get('audio') or {}).get('metrics') or {}).get('frames', [])
    origin = browser.get('recording_started_audio_s')
    rows = []
    for event in browser.get('events', []):
        if event.get('type') not in ('applied', 'phrase-scheduled', 'playback-started'):
            continue
        window = windows.get(event.get('sequence'))
        exact = window is not None and event.get('engine') != 'ace'
        audio_time = event.get('audio_time_s')
        relative = audio_time - origin if audio_time is not None and origin is not None else None
        rows.append(dict(sequence=event.get('sequence'),
                         eeg_window=window if exact else None, control=event,
                         link_scope='same control sequence' if exact else 'generation provenance unavailable',
                         recording_time_s=relative,
                         nearby_audio_frames=[frame for frame in metrics if relative is not None
                                              and relative-1 <= frame['time_s'] <= relative+3],
                         interpretation='Nearby audio is observational; not proof of causal effect or speaker timing.'))
    return rows


def analyze_audio(path):
    """Blockwise screens preserve stereo peaks and avoid loading long recordings."""
    frames = []
    previous = None
    elapsed = 0.
    with sf.SoundFile(path) as audio:
        rate = audio.samplerate
        for block in audio.blocks(blocksize=rate, dtype='float32', always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError('Nonfinite PCM samples')
            rms = float(np.sqrt(np.mean(block.astype(float) ** 2)))
            freq, stereo_psd = signal.welch(block, fs=rate, nperseg=min(2048, len(block)), axis=0)
            psd = stereo_psd.mean(axis=1)
            total = float(psd.sum())
            frames.append(dict(time_s=elapsed, duration_s=len(block)/rate,
                               rms_dbfs=20*np.log10(max(rms, 1e-12)),
                               sample_peak_dbfs=20*np.log10(max(float(np.abs(block).max()), 1e-12)),
                               clipped_samples=int(np.count_nonzero(np.abs(block) >= 1)),
                               centroid_hz=float(np.sum(freq*psd)/total) if total > 1e-15 else None,
                               high_frequency_ratio=float(psd[freq >= 8000].sum()/total) if total > 1e-15 else None,
                               block_boundary_step=float(np.abs(block[0] - previous).max()) if previous is not None else None))
            previous = block[-1]
            elapsed += len(block)/rate
    jumps = [dict(time_s=b['time_s'], jump_db=b['rms_dbfs']-a['rms_dbfs'])
             for a, b in zip(frames, frames[1:]) if a['rms_dbfs'] > -60 and b['rms_dbfs']-a['rms_dbfs'] > 6]
    return dict(method='1-second digital PCM RMS/PSD screens; RMS is not LUFS', frames=frames,
                rms_jump_candidates=jumps, bpm=None, bpm_reason='reliable beat estimator not implemented',
                onset_density=None, key=None, chords=None, true_peak_dbtp=None,
                unavailable_reason='No validated beat, tonal, chord or oversampled true-peak estimator yet',
                comfort_conclusion=None)


@router.get('')
def list_reports():
    paths = sorted(ROOT.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:100]
    return [json.loads(p.read_text(encoding='utf8')) for p in paths]


@router.get('/{identifier}')
def get_report(identifier: str):
    return reports.load(identifier)


@router.post('/{identifier}/browser')
async def browser_report(identifier: str, request: Request):
    value = await request.json()
    if not isinstance(value, dict) or len(value.get('events', [])) > 100000:
        raise HTTPException(422, 'Invalid browser evidence')
    reports.attach(identifier, 'browser', value)
    return {'status': 'saved'}


@router.put('/{identifier}/audio')
async def audio_report(identifier: str, request: Request):
    import asyncio
    reports.load(identifier)
    path = ROOT / f'{identifier}.wav'
    temporary = path.with_suffix('.part')
    try:
        with temporary.open('wb') as output:
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > 400 * 1024 * 1024:
                    raise ValueError('Report recording exceeds bounded recorder capacity')
                output.write(chunk)
        with sf.SoundFile(temporary) as audio:
            if audio.format != 'WAV' or audio.frames <= 0 or audio.channels not in (1, 2):
                raise ValueError('Expected final-mix PCM WAV')
        metrics = await asyncio.to_thread(analyze_audio, temporary)
        temporary.replace(path)
        reports.attach(identifier, 'audio', dict(url=f'/api/session-reports/{identifier}/audio', metrics=metrics))
    except (ValueError, sf.LibsndfileError) as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    return {'status': 'saved'}


@router.get('/{identifier}/audio')
def download_audio(identifier: str):
    reports.load(identifier)
    path = ROOT / f'{identifier}.wav'
    if not path.exists():
        raise HTTPException(404, 'Recording unavailable')
    return FileResponse(path, media_type='audio/wav', filename=f'{identifier}-final-mix.wav')
