"""Session evidence, not clinical outcomes or physical-output measurements."""
from copy import deepcopy
from pathlib import Path
import json
import threading
import time
import uuid
import unicodedata
import sys
try:
    import resource
except ImportError:
    resource = None

import numpy as np
import soundfile as sf
from scipy import signal
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query
from fastapi.responses import FileResponse
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator, ConfigDict
from typing import Literal
import csv
import io
from music_evaluation import evaluate_music, unavailable

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
            self._cpu_started = time.process_time()
            self.current = dict(id=uuid.uuid4().hex, started_at_s=time.time(), ended_at_s=None,
                                end_reason=None, metadata=metadata, windows=[], browser=None,
                                audio=None, control_windows=[], ai_music_evaluation=unavailable('No final-mix audio uploaded yet.'),
                                limitations=['Browser PCM is digital output, not speaker output.',
                                'No hardware loopback latency or ear-level SPL measurement.',
                                'Scores are not calibrated sleep probabilities; no clinical sleep claim.',
                                'Risk screens do not establish comfort; blinded listening is required.'])
            self.last_window = None
            self.n2_count = 0
            self.save()
            return self.current['id']

    def observe_control(self, event):
        with self.lock:
            if self.current and self.current['ended_at_s'] is None:
                self.current['control_windows'].append({key: deepcopy(event.get(key)) for key in
                    ('timestamp_s', 'sequence', 'source', 'status', 'reason', 'demo_scripted', 'current_music_state')})
                self.save()

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
            return self.n2_count >= 3

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
                elapsed = self.current['eeg_summary']['duration_s']
                self.current['engineering'] = dict(
                    backend_cpu_mean_percent=100 * (time.process_time() - self._cpu_started) / elapsed if elapsed > 0 else None,
                    backend_process_peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 2 if sys.platform == 'darwin' else 1024) if resource else None,
                    scope='Backend process CPU, 100% per core; RSS peak since process start, not session-only; browser/remote server excluded')
                self.save()
                if self is reports:
                    queue_automatic_song(self.current['id'])

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


class ExperimentLabel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    participant: str = Field(default='', max_length=64)
    condition: Literal['unassigned', 'fixed', 'sham', 'closed_loop'] = 'unassigned'
    trial: int = Field(default=1, ge=1, le=10000)
    notes: str = Field(default='', max_length=2000)
    comfort: float | None = Field(default=None, ge=1, le=7)
    musicality: float | None = Field(default=None, ge=1, le=7)
    visit: int | None = Field(default=None, ge=1, le=3)
    sequence: Literal['', 'ABC', 'ACB', 'BAC', 'BCA', 'CAB', 'CBA'] = ''
    trial_status: Literal['unreviewed', 'completed', 'interrupted', 'withdrawn', 'excluded'] = 'unreviewed'
    condition_verified: bool = False
    protocol_version: str = Field(default='', max_length=100)
    sham_trajectory_id: str = Field(default='', max_length=100)
    baseline_start_s: float | None = Field(default=None, ge=0)
    baseline_end_s: float | None = Field(default=None, ge=0)
    intervention_start_s: float | None = Field(default=None, ge=0)
    intervention_end_s: float | None = Field(default=None, ge=0)
    lseq_gts_items: list[float | None] = Field(default_factory=lambda: [None, None, None], min_length=3, max_length=3)
    relaxation_vas: float | None = Field(default=None, ge=0, le=10)
    sleep_difficulty_vas: float | None = Field(default=None, ge=0, le=10)
    kss_before: int | None = Field(default=None, ge=1, le=9)
    kss_after: int | None = Field(default=None, ge=1, le=9)
    sus_items: list[int | None] = Field(default_factory=lambda: [None] * 10, min_length=10, max_length=10)
    transition_naturalness_vas: float | None = Field(default=None, ge=0, le=10)
    prior_sleep_hours: float | None = Field(default=None, ge=0, le=24)
    caffeine_mg: float | None = Field(default=None, ge=0, le=2000)
    medication_notes: str = Field(default='', max_length=500)
    adverse_event: str = Field(default='', max_length=500)
    sound_pressure_dba: float | None = Field(default=None, ge=0, le=140)
    audio_material_id: str = Field(default='', max_length=100)
    motion_threshold: float | None = Field(default=None, ge=0)
    motion_max_gap_s: float = Field(default=2, gt=0, le=60)

    @model_validator(mode='after')
    def validate_protocol(self):
        self.participant = unicodedata.normalize('NFC', self.participant.strip())
        if any(unicodedata.category(c).startswith('C') for c in self.participant):
            raise ValueError('Participant name must not contain control characters')
        if self.participant.startswith(('=', '+', '-', '@')):
            raise ValueError('Participant name must not start with a spreadsheet formula prefix')
        if any(v is not None and not 1 <= v <= 5 for v in self.sus_items):
            raise ValueError('SUS requires ten original 1–5 responses or missing values')
        if any(v is not None and (not np.isfinite(v) or not 0 <= v <= 100) for v in self.lseq_gts_items):
            raise ValueError('GTS items must be 0–100 or missing')
        for start, end in ((self.baseline_start_s, self.baseline_end_s),
                           (self.intervention_start_s, self.intervention_end_s)):
            if (start is None) != (end is None) or (start is not None and end <= start):
                raise ValueError('Phase requires both bounds and a positive duration')
        if self.baseline_end_s is not None and self.intervention_start_s is not None and self.baseline_end_s > self.intervention_start_s:
            raise ValueError('Baseline and intervention must not overlap')
        return self


def mean_available(values):
    values = [float(v) for v in values if isinstance(v, (int, float)) and np.isfinite(v)]
    return float(np.mean(values)) if values else None


def experiment_row(report):
    label = report.get('experiment') or {}
    windows = report.get('windows', [])
    browser = report.get('browser') or {}
    frames = ((report.get('audio') or {}).get('metrics') or {}).get('frames', [])
    events = browser.get('events', [])
    summary = report.get('eeg_summary') or {}
    audio_metrics = (report.get('audio') or {}).get('metrics') or {}
    audio_rate = audio_metrics.get('sample_rate_hz')
    ai = report.get('ai_music_evaluation') or unavailable('Legacy report: no AI evaluation recorded.')
    recorded = sum(f.get('duration_s', 0) for f in frames) if frames else None
    coverage = (recorded / summary['duration_s'] if recorded is not None and summary.get('duration_s', 0) > 0 else None)
    row = dict(id=report['id'], started_at_s=report['started_at_s'],
               ended=report.get('ended_at_s') is not None,
               mode=report.get('metadata', {}).get('mode', 'unknown'),
               participant=label.get('participant', ''), condition=label.get('condition', 'unassigned'),
               trial=label.get('trial', 1), end_reason=report.get('end_reason'),
               executed_condition=report.get('metadata', {}).get('experiment', {}).get('condition') if report.get('metadata', {}).get('experiment') else None,
               execution_version=report.get('metadata', {}).get('execution_version'),
               music_source=report.get('metadata', {}).get('music_source'),
               duration_s=summary.get('duration_s'),
               qualified_window_ratio=summary.get('qualified_window_ratio'),
               classification_ms=mean_available([w.get('classification_ms') for w in windows]),
               recorded_seconds=browser.get('recorded_seconds'),
               recording_status=browser.get('recording_status'),
               analyzed_audio_seconds=recorded,
               recording_session_duration_ratio=coverage,
               recording_completeness=('partial_memory_limit' if browser.get('recording_status') == 'partial_memory_limit'
                                       else 'no_audio' if not frames else 'coverage_not_verified'),
               rms_dbfs=mean_available([f.get('rms_dbfs') for f in frames]),
               ai_evaluation_status=ai['status'], ai_evaluation_reason=ai.get('reason'),
               ai_model=ai.get('model'), ai_model_version=ai.get('model_version'), ai_method=ai.get('method'),
               ai_pleasantness=(ai.get('scores') or {}).get('pleasantness'),
               ai_coherence=(ai.get('scores') or {}).get('coherence'),
               ai_transition_naturalness=(ai.get('scores') or {}).get('transition_naturalness'),
               audio_sample_rate_hz=audio_rate,
               centroid_hz=mean_available([f.get('centroid_hz') for f in frames]),
               high_frequency_ratio=(mean_available([f.get('high_frequency_ratio') for f in frames])
                                     if audio_rate and audio_rate > 16000 else None),
               sample_peak_dbfs=max((f['sample_peak_dbfs'] for f in frames), default=None),
               clipped_samples=sum(f.get('clipped_samples', 0) for f in frames) if frames else None,
               rms_jump_candidates=len(report['audio']['metrics'].get('rms_jump_candidates', [])) if frames else None,
               playback_errors=sum(e.get('type') == 'playback-error' for e in events) if browser else None,
               control_events=sum(e.get('type') in ('applied', 'phrase-scheduled') for e in events) if browser else None,
               download_ms=mean_available([e.get('duration_ms') for e in events if e.get('type') == 'download']),
               decode_ms=mean_available([e.get('duration_ms') for e in events if e.get('type') == 'decode']),
               comfort=label.get('comfort'), musicality=label.get('musicality'))
    for band in ('alpha', 'alpha_8_12', 'theta', 'beta'):
        row[f'{band}_power_uv2'] = mean_available([
            mean_available((w.get('band_power_uv2') or {}).get('values', {}).get(band, []))
            for w in windows if w.get('signal_quality') == 1])
    from experiment_analysis import protocol_metrics
    row.update(protocol_metrics(report))
    row.update({key: (report.get('engineering') or {}).get(key) for key in
                ('backend_cpu_mean_percent', 'backend_process_peak_rss_mb')})
    from songeval_client import KEYS
    song = normalized_song(report)
    row.update(songeval_status=song.get('status', 'unavailable'), songeval_reason=song.get('reason'),
               songeval_model_version=song.get('model_version'), songeval_method=song.get('method'),
               songeval_coverage_scope=song.get('coverage_scope'),
               songeval_analyzed_seconds=song.get('analyzed_audio_seconds'))
    for key in KEYS:
        row[f'songeval_{key}'] = (song.get('scores') or {}).get(key) if song.get('status') == 'completed' else None
    return row


def all_experiment_rows():
    rows = [experiment_row(json.loads(p.read_text(encoding='utf8')))
            for p in reports.root.glob('*.json')]
    return sorted(rows, key=lambda row: row['started_at_s'], reverse=True)


# Static routes must precede /{identifier}.
@router.get('/experiments/summary')
def experiment_summary():
    return {'rows': all_experiment_rows(), 'storage': str(reports.root.resolve()),
            'protocol_analysis_version': 1,
            'experiment_execution_version': 1,
            'songeval_version': 1,
            'scope': 'Local evidence; execution-versioned sessions implement treatment assignment. Legacy labels alone do not.'}


@router.get('/experiments/export.csv')
def experiment_export():
    rows = all_experiment_rows()
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return Response('\ufeff' + output.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="experiment-data.csv"'})


@router.get('/experiments/analysis')
def experiment_analysis(include_demo: bool = False, ids: list[str] | None = Query(default=None)):
    from experiment_analysis import analyze_cohort
    rows = all_experiment_rows()
    if isinstance(ids, list):
        rows = [r for r in rows if r['id'] in ids]
    return analyze_cohort(rows, include_demo=include_demo)


@router.put('/{identifier}/physiology')
async def physiology_report(identifier: str, request: Request):
    from experiment_analysis import validate_physiology, parse_physiology_csv
    payload = await request.body()
    if len(payload) > 5 * 1024 * 1024:
        raise HTTPException(413, 'Physiology import exceeds 5 MB')
    try:
        data = (parse_physiology_csv(payload) if request.headers.get('content-type', '').startswith('text/csv')
                else validate_physiology(json.loads(payload)))
    except (ValueError, TypeError, KeyError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    reports.attach(identifier, 'physiology', data)
    return {'status': 'saved', 'samples': len(data['samples'])}


@router.put('/{identifier}/experiment')
def label_experiment(identifier: str, label: ExperimentLabel):
    report = reports.load(identifier)
    if report.get('metadata', {}).get('execution_version'):
        original = (report['metadata'].get('experiment') or {}).get('condition')
        if label.condition != original:
            raise HTTPException(422, 'Executed condition is immutable; record deviations in notes')
    reports.attach(identifier, 'experiment', label.model_dump())
    return {'status': 'saved'}


song_job_lock = threading.Lock()
active_song_jobs = set()
audio_uploads = set()


def normalized_song(report):
    from songeval_client import empty
    song = report.get('songeval') or {}
    if song.get('status') in ('running', 'queued') and report.get('id') not in active_song_jobs:
        return empty('failed', 'Evaluation interrupted by backend restart; request again')
    return song


def queue_automatic_song(identifier):
    from songeval_client import empty
    with reports.lock:
        report = reports.load(identifier)
        path = reports.root / f'{identifier}.wav'
        if (not report.get('metadata', {}).get('auto_songeval') or
                not report.get('ended_at_s') or not report.get('audio') or
                not path.exists() or identifier in active_song_jobs or identifier in audio_uploads or
                (report.get('songeval') or {}).get('status') == 'completed'):
            return
        active_song_jobs.add(identifier)
        frames = report['audio'].get('metrics', {}).get('frames', [])
        if frames and all(frame.get('sample_peak_dbfs', 0) <= -120 for frame in frames):
            active_song_jobs.discard(identifier)
            reports.attach(identifier, 'songeval', empty(reason='Recording contains only silence; no music to evaluate'))
            return
        reports.attach(identifier, 'songeval', empty('queued', 'Automatic final-mix evaluation queued'))
        def worker():
            song_job_lock.acquire()
            try:
                reports.attach(identifier, 'songeval', empty('running', 'Automatic final-mix evaluation'))
            except Exception:
                active_song_jobs.discard(identifier)
                song_job_lock.release()
                return
            run_songeval(identifier, path)
        threading.Thread(target=worker, name='automatic-songeval', daemon=True).start()


def run_songeval(identifier, path):
    from songeval_client import evaluate, empty
    try:
        result = evaluate(path)
        result['evaluated_at_s'] = time.time()
        reports.attach(identifier, 'songeval', result)
    except Exception:
        reports.attach(identifier, 'songeval', empty('failed', 'SongEval background evaluation failed'))
    finally:
        active_song_jobs.discard(identifier)
        song_job_lock.release()


@router.post('/{identifier}/songeval', status_code=202)
async def song_evaluation(identifier: str, request: Request, background_tasks: BackgroundTasks):
    from songeval_client import empty
    body = await request.json()
    if not isinstance(body, dict) or body.get('send_audio_to_server') is not True:
        raise HTTPException(422, 'Explicit authorization to send final-mix audio is required')
    report = reports.load(identifier)
    if identifier in active_song_jobs:
        raise HTTPException(409, 'This recording is already queued or running')
    if identifier in audio_uploads:
        raise HTTPException(409, 'Wait for final-mix audio upload to finish')
    path = reports.root / f'{identifier}.wav'
    if not report.get('ended_at_s') or not report.get('audio') or not path.exists():
        raise HTTPException(422, 'An ended session with saved final-mix audio is required')
    frames = report['audio'].get('metrics', {}).get('frames', [])
    if frames and all(frame.get('sample_peak_dbfs', 0) <= -120 for frame in frames):
        raise HTTPException(422, 'Recording contains only silence; no music to evaluate')
    if not song_job_lock.acquire(blocking=False):
        raise HTTPException(409, 'Another SongEval evaluation is running')
    try:
        active_song_jobs.add(identifier)
        reports.attach(identifier, 'songeval', empty('running', 'Final mix sent to configured private SongEval server'))
        background_tasks.add_task(run_songeval, identifier, path)
    except Exception:
        active_song_jobs.discard(identifier)
        song_job_lock.release()
        raise
    return {'status': 'running'}


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
        channels = audio.channels
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
                sample_rate_hz=rate, channels=channels,
                rms_jump_candidates=jumps, bpm=None, bpm_reason='reliable beat estimator not implemented',
                onset_density=None, key=None, chords=None, true_peak_dbtp=None,
                unavailable_reason='No validated beat, tonal, chord or oversampled true-peak estimator yet',
                comfort_conclusion=None)


@router.get('')
def list_reports():
    paths = reports.root.glob('*.json')
    results = [json.loads(p.read_text(encoding='utf8')) for p in paths]
    results.sort(key=lambda report: report['started_at_s'], reverse=True)
    results = results[:100]
    for report in results:
        if 'songeval' in report:
            report['songeval'] = normalized_song(report)
    return results


@router.get('/{identifier}')
def get_report(identifier: str):
    report = reports.load(identifier)
    if 'songeval' in report:
        report['songeval'] = normalized_song(report)
    return report


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
    if identifier in active_song_jobs or identifier in audio_uploads:
        raise HTTPException(409, 'Wait for SongEval before replacing audio')
    path = reports.root / f'{identifier}.wav'
    temporary = path.with_suffix('.part')
    audio_uploads.add(identifier)
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
        from songeval_client import empty
        reports.attach(identifier, 'songeval', empty(reason='Audio replaced; request SongEval for this recording'))
        evaluation = await asyncio.to_thread(evaluate_music, path)
        evaluation['evaluated_at_s'] = time.time()
        evaluation['analyzed_audio_seconds'] = sum(f['duration_s'] for f in metrics['frames'])
        evaluation['coverage_scope'] = 'Uploaded recording only; whole-session coverage not verified.'
        reports.attach(identifier, 'ai_music_evaluation', evaluation)
    except (ValueError, sf.LibsndfileError) as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    finally:
        audio_uploads.discard(identifier)
        temporary.unlink(missing_ok=True)
    queue_automatic_song(identifier)
    return {'status': 'saved'}


@router.get('/{identifier}/audio')
def download_audio(identifier: str):
    reports.load(identifier)
    path = reports.root / f'{identifier}.wav'
    if not path.exists():
        raise HTTPException(404, 'Recording unavailable')
    return FileResponse(path, media_type='audio/wav', filename=f'{identifier}-final-mix.wav')
