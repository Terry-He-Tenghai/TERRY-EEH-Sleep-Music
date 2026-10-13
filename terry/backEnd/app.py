"""EEG acquisition, local music, and automatic arrangement-plan events.

Inference runs on an independent bounded worker. Adaptive events describe
planned arrangements, not actual audio playback. BrainFlow is imported lazily.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time
import traceback
from dataclasses import dataclass, replace
from typing import Any, Literal

from adaptive_web import AdaptiveWebService
from display_filter import DisplayFilter
from raw_recording import RawRecording
from powerline_filter import PowerlineNoiseFilter
from channel_mapping import CAP_ORDER
from ace_step import STYLES as ACE_STYLES, automatic as ace_automatic, router as ace_router
from ace_music_prompts import ChordProgression, HarmonyMode, MusicGenre
from babyslakh import StemTrackId, get_track as get_stem_track, router as stem_music_router
from music_library import router as music_router
from music_choices import router as music_choices_router, candidates, uploaded
from music_workbench import router as music_workbench_router
from session_reports import reports, router as session_reports_router, ExperimentLabel
from ace_server_manager import router as ace_server_router

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

CHANNEL_NAMES = (
    "C3", "C4", "Cz", "FC3", "FC4", "CP3", "CP4", "FCz",
    "CPz", "Fz", "P3", "Pz", "P4", "O1", "Oz", "O2",
)
CAP_CHANNEL_NAMES = CAP_ORDER
SAMPLE_RATE_HZ = 250
BACKEND_ROOT = Path(__file__).resolve().parent
ACQUISITION_REVISION = 'acquisition-diagnostics-v1'
logger = logging.getLogger('terry.acquisition')
if not logger.handlers:
    try:
        handler = RotatingFileHandler(BACKEND_ROOT / 'acquisition_errors.log',
                                     maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf8')
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class StartRequest(BaseModel):
    auto_songeval: bool = False
    save_raw_data: bool = False
    experiment: ExperimentLabel | None = None
    experiment_duration_s: int = Field(default=2700, ge=60, le=10800)
    mode: str = Field(default="demo", pattern="^(demo|brainflow)$")
    demo_profile: Literal['model', 'showcase'] = 'model'
    ip_address: str = "192.168.4.1"
    ip_port: int = Field(default=12345, ge=1, le=65535)
    gain: Literal[1, 2, 4, 6, 8, 12, 24] = 24
    music_style: Literal['all', 'ambient', 'piano', 'nature', 'strings', 'electronic'] = 'all'
    music_source: Literal['stems', 'upload', 'ace', 'external'] = 'stems'
    harmony_mode: HarmonyMode = 'major'
    chord_progression: ChordProgression = 'gentle'
    music_genre: MusicGenre | None = None
    uploaded_track_id: str | None = Field(default=None, pattern=r'^user_[a-f0-9]{32}$')
    reference_track_id: str | None = Field(default=None, pattern=r'^user_[a-f0-9]{32}$')
    stem_track_id: StemTrackId | None = None
    sample_rate_hz: Literal[250, 500, 1000] = 250
    classification_channels: Literal[2, 4, 6, 8, 16] = 16

    @model_validator(mode='after')
    def exclusive_music_source(self):
        if self.experiment and self.experiment.condition == 'fixed':
            self.music_source = 'external'
            self.uploaded_track_id = self.reference_track_id = self.stem_track_id = None
            self.music_style = 'all'
            self.auto_songeval = False
        elif self.music_source == 'external':
            raise ValueError('External music is reserved for the fixed condition')
        if self.experiment and self.experiment.condition in ('fixed', 'sham', 'closed_loop'):
            if not self.experiment.participant:
                raise ValueError('Participant name or ID is required')
            self.save_raw_data = True
            if self.experiment.condition in ('fixed', 'sham'):
                self.demo_profile = 'model'
        if self.demo_profile == 'showcase' and (self.mode != 'demo' or self.sample_rate_hz != 250):
            raise ValueError('showcase requires demo mode and 250 Hz synthetic samples')
        if self.uploaded_track_id is not None and self.stem_track_id is not None:
            raise ValueError('uploaded_track_id and stem_track_id are mutually exclusive')
        if self.reference_track_id and self.music_source != 'ace':
            raise ValueError('reference audio requires ACE-Step')
        if self.music_source == 'ace' and (self.music_style not in ACE_STYLES or self.uploaded_track_id or self.stem_track_id):
            raise ValueError('ACE-Step requires a preset style and no local track')
        return self


@dataclass(frozen=True)
class AcquisitionStatus:
    connected: bool
    streaming: bool
    mode: str
    sample_rate_hz: int
    channels: tuple[str, ...]
    samples_emitted: int
    error: str | None
    last_packet_age_s: float | None = None
    received_seconds: float = 0.0
    staleness: str = "unknown"
    recording: dict | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "status",
            "connected": self.connected,
            "streaming": self.streaming,
            "mode": self.mode,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": list(self.channels),
            "samples_emitted": self.samples_emitted,
            "error": self.error,
            # Received-time metrics from sample counts; not a hardware clock check.
            "last_packet_age_s": self.last_packet_age_s,
            "received_seconds": self.received_seconds,
            "staleness": self.staleness,
            "configured_sample_rate_hz": self.sample_rate_hz,
            "report_id": reports.current['id'] if reports.current else None,
            "recording": self.recording,
            "experiment": (reports.current or {}).get('experiment'),
            "experiment_duration_s": (reports.current or {}).get('metadata', {}).get('experiment_duration_s'),
        }


class AcquisitionService:
    """Threaded BrainFlow/demo source with a browser-friendly stream."""

    def __init__(self) -> None:
        self._sample_rate_hz = SAMPLE_RATE_HZ
        self._channels = CHANNEL_NAMES
        self._display_filter = DisplayFilter(self._sample_rate_hz, len(CHANNEL_NAMES))
        self._powerline_filter = PowerlineNoiseFilter(self._sample_rate_hz, len(CHANNEL_NAMES))
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._board: Any | None = None
        self._board_streaming = False
        self._phase = 'idle'
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._adaptive = AdaptiveWebService(self._publish)
        self._sham = AdaptiveWebService(self._publish_sham)
        self._condition = 'unassigned'
        self._sham_thread = None
        self._deadline = None
        self._adaptive_generation = 0
        self._recording = None
        self._status = AcquisitionStatus(
            connected=False, streaming=False, mode="demo", sample_rate_hz=self._sample_rate_hz,
            channels=CHANNEL_NAMES, samples_emitted=0, error=None,
        )

    def status(self) -> AcquisitionStatus:
        with self._lock:
            return replace(self._status, recording=self._recording.status() if self._recording else None)

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def start(self, request: StartRequest) -> AcquisitionStatus:
        with self._lock:
            if self._status.streaming or (self._thread is not None and self._thread.is_alive()):
                return self.status()
            self._sample_rate_hz = request.sample_rate_hz
            self._channels = CAP_CHANNEL_NAMES if request.mode == "brainflow" else CHANNEL_NAMES
            self._display_filter = DisplayFilter(self._sample_rate_hz, len(self._channels))
            self._powerline_filter = PowerlineNoiseFilter(self._sample_rate_hz, len(self._channels))
            self._stop_event.clear()
            self._condition = request.experiment.condition if request.experiment else 'unassigned'
            self._deadline = time.monotonic() + request.experiment_duration_s if self._condition != 'unassigned' else None
            if request.experiment and self._condition != 'unassigned':
                prior = [reports.load(p.stem).get('experiment') or {} for p in reports.root.glob('*.json')]
                request.experiment.trial = 1 + max((e.get('trial', 0) for e in prior
                    if e.get('participant') == request.experiment.participant and e.get('condition') == self._condition), default=0)
                if self._condition == 'sham':
                    request.experiment.sham_trajectory_id = 'showcase-96s-v1'
            metadata = request.model_dump()
            metadata.update(backend_root=str(BACKEND_ROOT), acquisition_revision=ACQUISITION_REVISION)
            if self._condition != 'unassigned':
                metadata.update(execution_version=1, music_control_source={'fixed': 'external_device', 'sham': 'scripted_demo'}.get(self._condition, 'current_eeg'))
            reports.start(metadata)
            if request.experiment is not None:
                reports.attach(reports.current['id'], 'experiment', request.experiment.model_dump())
            self._recording = None
            if request.save_raw_data:
                try:
                    self._recording = RawRecording(dict(request.model_dump(),
                        channels=list(self._channels), report_id=reports.current['id']))
                    reports.attach(reports.current['id'], 'raw_recording', self._recording.status())
                except Exception as exc:
                    reports.finish('raw_recording_start_failed', 0)
                    raise HTTPException(500, f'无法创建原始数据文件：{exc}') from exc
            self._status = AcquisitionStatus(
                connected=request.mode == "demo", streaming=True, mode=request.mode,
                sample_rate_hz=self._sample_rate_hz, channels=self._channels,
                samples_emitted=0, error=None,
            )
            try:
                self._adaptive_generation = self._adaptive.start(request.mode, self._sample_rate_hz, self._channels, request.music_style, request.uploaded_track_id, stem_track_id=request.stem_track_id, demo_profile=request.demo_profile, classification_channels=request.classification_channels, music_source='external' if self._condition in ('fixed', 'sham') else request.music_source)
                music_generation = self._adaptive_generation
                if self._condition == 'sham':
                    music_generation = self._sham.start('demo', 250, CHANNEL_NAMES, request.music_style, request.uploaded_track_id,
                        stem_track_id=request.stem_track_id, demo_profile='showcase', music_source=request.music_source,
                        generation_floor=self._adaptive_generation)
                if request.music_source == 'ace' and self._condition != 'fixed':
                    ace_automatic.start(music_generation, request.music_style, request.reference_track_id,
                                        request.harmony_mode, request.chord_progression, music_genre=request.music_genre)
                else:
                    ace_automatic.stop()
                if self._condition == 'sham':
                    self._sham_thread = threading.Thread(target=self._run_sham, args=(music_generation,), name='sham-control', daemon=True)
                    self._sham_thread.start()
                self._thread = threading.Thread(target=self._run, args=(request, self._adaptive_generation), name="eeg-acquisition", daemon=True)
                self._thread.start()
            except Exception:
                self._stop_event.set()
                if self._sham_thread is not None:
                    self._sham_thread.join(timeout=3.0)
                if self._recording:
                    self._recording.close()
                    reports.attach(reports.current['id'], 'raw_recording', self._recording.status())
                self._status = replace(self._status, connected=False, streaming=False)
                self._thread = None
                reports.finish('acquisition_start_failed', 0)
                ace_automatic.stop()
                self._adaptive.stop(self._adaptive_generation, failed=True)
                self._sham.stop()
                raise
            return self.status()

    def stop(self, reason: str = 'manual_stop') -> AcquisitionStatus:
        self._stop_event.set()
        reports.finish(reason, self._status.samples_emitted / self._sample_rate_hz)
        ace_automatic.stop()
        self._adaptive.stop(self._adaptive_generation)
        self._sham.stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        if self._sham_thread is not None:
            self._sham_thread.join(timeout=3.0)
        # The acquisition thread alone owns and releases the board.
        with self._lock:
            self._status = AcquisitionStatus(
                connected=False, streaming=False, mode=self._status.mode,
                sample_rate_hz=self._sample_rate_hz, channels=self._channels,
                samples_emitted=self._status.samples_emitted, error=self._status.error,
            )
            if thread is None or not thread.is_alive():
                self._thread = None
        self._publish_status()
        return self.status()

    def _publish(self, message: dict[str, Any]) -> None:
        if message.get("type") == "adaptive_music":
            message['experiment_condition'] = self._condition
            if reports.current:
                message['report_id'] = reports.current['id']
            inference_failed = message.get('status') == 'error'
            reports.observe(message)
            # N2 pauses music, not acquisition: a terminal event would interrupt
            # the browser's gradual fade and truncate the physiological record.
            if inference_failed:
                self._stop_event.set()
                reason = 'inference_error'
                reports.finish(reason, self._status.samples_emitted / self._sample_rate_hz)
                threading.Thread(target=self.stop, args=(reason,), daemon=True).start()
            if self._condition not in ('fixed', 'sham'):
                ace_automatic.consider(message)
            if self._condition not in ('fixed', 'sham') and message.get('source') == 'LIVE' and ace_automatic.session == message.get('session_id'):
                message['ace_sleep_paused'] = ace_automatic.status()['status'] == 'sleep_paused'
            if self._condition == 'sham':
                message = {**message, 'type': 'eeg_measurement'}
            elif self._condition == 'fixed':
                message = {**message, 'playback_mode': 'silent', 'notes': [], 'selected_track': None,
                           'experiment_condition': 'fixed', 'music_control_source': 'external_device'}
        self._broadcast(message)

    def _publish_sham(self, message):
        if self._condition != 'sham':
            return
        message.update(experiment_condition='sham', music_control_source='scripted_demo',
                       report_id=(reports.current or {}).get('id'))
        reports.observe_control(message)
        ace_automatic.consider(message)
        self._broadcast(message)

    def adaptive_status(self):
        result = self._sham.status() if self._condition == 'sham' else self._adaptive.status()
        result.update(experiment_condition=self._condition, report_id=(reports.current or {}).get('id'))
        if self._condition == 'sham':
            result['measurement'] = self._adaptive.status()
        if self._condition == 'fixed':
            result.update(playback_mode='silent', notes=[], selected_track=None, music_control_source='external_device')
        return result

    def _broadcast(self, message):
        loop = self._loop
        if loop is None:
            return

        def put_messages() -> None:
            with self._lock:
                subscribers = tuple(self._subscribers)
            for queue in subscribers:
                if queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(message)

        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(put_messages)

    def _publish_status(self) -> None:
        self._publish(self.status().as_dict())

    def _run(self, request: StartRequest, generation: int) -> None:
        self._phase = 'initializing'
        logger.info('Acquisition start mode=%s source=%s revision=%s report=%s',
                    request.mode, BACKEND_ROOT, ACQUISITION_REVISION,
                    (reports.current or {}).get('id'))
        try:
            if request.mode == "brainflow":
                self._run_brainflow(request)
            else:
                self._run_demo(request)
        except Exception as exc:
            error = f"采集失败 [{self._phase}]：{type(exc).__name__}: {exc}"
            if (request.mode == 'brainflow' and self._phase == 'prepare_session'
                    and getattr(exc, 'exit_code', None) in (4, 17)):
                error += (f"。设备 {request.ip_address}:{request.ip_port} 的初始化未完成；"
                          "请检查设备供电、USB 网卡/网线或 Wi-Fi 连接，确认设备 IP 可达，"
                          "并关闭其他占用设备的采集程序后重试。")
            detail = dict(phase=self._phase, exception_type=type(exc).__name__,
                          message=str(exc), traceback=traceback.format_exc(),
                          backend_root=str(BACKEND_ROOT), revision=ACQUISITION_REVISION,
                          samples_emitted=self._status.samples_emitted,
                          ip_address=request.ip_address, ip_port=request.ip_port)
            logger.exception('Acquisition failed phase=%s report=%s samples=%s endpoint=%s:%s',
                             self._phase, (reports.current or {}).get('id'),
                             self._status.samples_emitted, request.ip_address, request.ip_port)
            with self._lock:
                self._status = AcquisitionStatus(
                    connected=False, streaming=False, mode=request.mode,
                    sample_rate_hz=self._sample_rate_hz, channels=self._channels,
                    samples_emitted=self._status.samples_emitted,
                    error=error,
                )
            self._cleanup('publish_error', self._publish_status)
            if reports.current:
                self._cleanup('save_error', lambda: reports.attach(reports.current['id'], 'acquisition_error', detail))
            self._cleanup('finish_error_report', lambda: reports.finish(
                'acquisition_error', self._status.samples_emitted / self._sample_rate_hz))
        finally:
            stopped = self._stop_event.is_set()
            self._stop_event.set()
            # Release hardware before unrelated cleanup can fail or block.
            self._release_board()
            if self._sham_thread is not None:
                self._cleanup('join_sham', lambda: self._sham_thread.join(timeout=3.0))
            self._cleanup('stop_sham', self._sham.stop)
            self._cleanup('stop_music', ace_automatic.stop)
            if self._recording:
                self._cleanup('close_recording', self._recording.close)
                if reports.current:
                    self._cleanup('save_recording', lambda: reports.attach(
                        reports.current['id'], 'raw_recording', self._recording.status()))
            self._cleanup('finish_report', lambda: reports.finish(
                'manual_stop' if stopped else 'unexpected_end',
                self._status.samples_emitted / self._sample_rate_hz))
            self._cleanup('stop_inference', lambda: self._adaptive.stop(generation, failed=not stopped))
            with self._lock:
                if self._status.streaming:
                    self._status = AcquisitionStatus(
                        connected=False, streaming=False, mode=self._status.mode,
                        sample_rate_hz=self._sample_rate_hz, channels=self._channels,
                        samples_emitted=self._status.samples_emitted, error=self._status.error,
                    )
            self._cleanup('publish_stopped', self._publish_status)

    @staticmethod
    def _cleanup(name, action):
        try:
            action()
        except Exception:
            logger.exception('Acquisition cleanup failed: %s', name)

    def _run_sham(self, generation):
        from demo_showcase import showcase_waveform
        start = 0
        while not self._stop_event.is_set():
            times = (start + np.arange(25)) / 250
            synthetic = np.vstack([showcase_waveform(times, i, i * .31) for i in range(16)])
            self._sham.submit(synthetic, start, 250, generation)
            start += 25
            self._stop_event.wait(.1)

    def _duration_complete(self):
        if self._deadline is not None and time.monotonic() >= self._deadline:
            reports.finish('duration_complete', self._status.samples_emitted / self._sample_rate_hz)
            self._stop_event.set()
            return True
        return False

    def _run_demo(self, request: StartRequest | None = None) -> None:
        from demo_showcase import showcase_waveform

        showcase = request is not None and request.demo_profile == 'showcase'
        chunk_samples = self._sample_rate_hz // 10
        rng = np.random.default_rng(42)
        phase = np.arange(len(CHANNEL_NAMES), dtype=float) * 0.31
        sample_index = 0
        while not self._stop_event.is_set():
            if self._duration_complete():
                break
            times = (sample_index + np.arange(chunk_samples)) / self._sample_rate_hz
            data = np.vstack([
                (showcase_waveform(times, index, phase[index]) if showcase else
                 14.0 * np.sin(2 * np.pi * (8.0 + index % 4) * times + phase[index])
                 + 2.0 * np.sin(2 * np.pi * 1.2 * times))
                + rng.normal(0.0, 1.2, chunk_samples)
                for index in range(len(CHANNEL_NAMES))
            ])
            self._publish_chunk(data, sample_index)
            sample_index += chunk_samples
            time.sleep(chunk_samples / self._sample_rate_hz)

    def _run_brainflow(self, request: StartRequest) -> None:
        self._phase = 'import_brainflow'
        try:
            from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
        except ImportError as exc:
            raise RuntimeError("brainflow is required for brainflow mode; install the web/hardware dependencies") from exc
        params = BrainFlowInputParams()
        params.ip_address = request.ip_address
        params.ip_port = request.ip_port
        params.timeout = 10
        self._phase = 'create_board'
        board = BoardShim(BoardIds.CYTON_DAISY_WIFI_BOARD.value, params)
        self._board = board
        self._board_streaming = False
        self._phase = 'prepare_session'
        board.prepare_session()
        self._phase = 'configure_sample_rate'
        board.config_board({250: "~6", 500: "~5", 1000: "~4"}[request.sample_rate_hz])
        self._phase = 'configure_channels'
        board.config_board(self._channel_config(request.gain))
        self._phase = 'start_stream'
        board.start_stream()
        self._board_streaming = True
        self._phase = 'initial_read'
        board.get_board_data()
        self._phase = 'validate_channels'
        eeg_channels = BoardShim.get_eeg_channels(BoardIds.CYTON_DAISY_WIFI_BOARD.value)
        timestamp_channel = BoardShim.get_timestamp_channel(BoardIds.CYTON_DAISY_WIFI_BOARD.value)
        package_channel = BoardShim.get_package_num_channel(BoardIds.CYTON_DAISY_WIFI_BOARD.value)
        if len(eeg_channels) != len(CHANNEL_NAMES):
            raise RuntimeError(f"BrainFlow returned {len(eeg_channels)} EEG channels, expected 16")
        with self._lock:
            self._status = AcquisitionStatus(
                connected=False, streaming=True, mode="brainflow", sample_rate_hz=self._sample_rate_hz,
                channels=self._channels, samples_emitted=0, error=None,
            )
        self._publish_status()
        sample_index = 0
        last_received = time.monotonic()
        while not self._stop_event.is_set():
            if self._duration_complete():
                break
            self._phase = 'read_stream'
            data = board.get_board_data()
            if data.shape[1] == 0:
                if time.monotonic() - last_received > 10.0:
                    self._phase = 'stream_no_data'
                    raise RuntimeError("连续 10 秒未收到脑电数据。请关闭其他采集软件，检查脑电帽 Wi-Fi、设备电源及网络连接后重试。")
                self._stop_event.wait(0.01)
                continue
            last_received = time.monotonic()
            self._phase = 'process_samples'
            samples = np.asarray(data[np.asarray(eeg_channels), :], dtype=float)
            self._publish_chunk(samples, sample_index, timestamps_s=np.asarray(data[timestamp_channel, :], dtype=float),
                                package_ids=np.asarray(data[package_channel, :], dtype=float))
            if sample_index == 0:
                self._publish_status()
            sample_index += samples.shape[1]

    @staticmethod
    def _channel_config(gain: int, active_indices: tuple[int, ...] = tuple(range(16))) -> str:
        letters = "QWERTYUI"
        gain_code = {1: 0, 2: 1, 4: 2, 6: 3, 8: 4, 12: 5, 24: 6}[int(gain)]
        return "".join(
            f"x{str(index + 1) if index < 8 else letters[index - 8]}{0 if index in active_indices else 1}{gain_code}0110X"
            for index in range(16)
        )

    def _publish_chunk(self, samples_uv: np.ndarray, start_sample: int,
                       timestamps_s: np.ndarray | None = None,
                       package_ids: np.ndarray | None = None) -> None:
        if samples_uv.shape[0] != len(self._channels):
            raise ValueError("EEG data does not match the active channel montage")
        # Inference must see original uV values, including NaN/Inf; display cleanup
        # below must never turn an invalid raw signal into a valid model input.
        if self._recording:
            self._recording.submit(samples_uv, start_sample, timestamps_s, package_ids)
        self._adaptive.submit(samples_uv, start_sample, self._sample_rate_hz,
                              self._adaptive_generation, timestamps_s, package_ids)
        clean = self._display_filter.process(samples_uv)
        self._publish({
            "type": "samples", "timestamp_s": start_sample / self._sample_rate_hz,
            "sample_rate_hz": self._sample_rate_hz, "channels": list(self._channels),
            "samples_uv": np.asarray(clean, dtype=float).round(4).tolist(),
            "recording": self._recording.status() if self._recording else None,
        })
        with self._lock:
            self._status = AcquisitionStatus(
                connected=not self._stop_event.is_set(), streaming=self._status.streaming,
                mode=self._status.mode, sample_rate_hz=self._sample_rate_hz,
                channels=self._channels, samples_emitted=self._status.samples_emitted + clean.shape[1], error=None,
            )

    def _release_board(self) -> None:
        board = self._board
        self._board = None
        if board is None:
            return
        if self._board_streaming:
            self._cleanup('stop_stream', board.stop_stream)
        # Prepare may fail after allocating native resources. A missing session
        # (code 15) is expected in that case, but other release errors matter.
        try:
            board.release_session()
        except Exception as exc:
            if getattr(exc, 'exit_code', None) != 15:
                logger.exception('Acquisition cleanup failed: release_session')
        self._board_streaming = False


service = AcquisitionService()
app = FastAPI(title="Terry EEG and Offline Music API", version="0.2.0")
app.include_router(music_choices_router)
app.include_router(music_router)
app.include_router(music_workbench_router)
app.include_router(stem_music_router)
app.include_router(ace_router)
app.include_router(session_reports_router)
app.include_router(ace_server_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("TERRY_WEB_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    service.set_loop(asyncio.get_running_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    service.stop()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "backend_root": str(BACKEND_ROOT),
            "acquisition_revision": ACQUISITION_REVISION}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return service.status().as_dict()


@app.get("/api/adaptive/status")
async def adaptive_status() -> dict[str, Any]:
    return service.adaptive_status()


@app.post("/api/acquisition/start")
async def start(request: StartRequest) -> dict[str, Any]:
    if (request.uploaded_track_id and uploaded(request.uploaded_track_id) is None
            or request.reference_track_id and uploaded(request.reference_track_id) is None):
        raise HTTPException(422, '上传音频不存在，请重新上传或选择本地风格')
    if request.stem_track_id and get_stem_track(request.stem_track_id) is None:
        raise HTTPException(422, 'Selected BabySlakh track is unavailable')
    if request.music_source != 'ace' and not request.uploaded_track_id and not request.stem_track_id and request.music_style != 'all' and not candidates(request.music_style):
        raise HTTPException(422, '该风格暂无可播放素材，请先导入并标注风格')
    return service.start(request).as_dict()


@app.get('/api/acquisition/recording-info')
async def recording_info():
    return {'raw_recording_version': 1}


@app.post("/api/acquisition/stop")
async def stop() -> dict[str, Any]:
    return service.stop().as_dict()


@app.websocket("/ws/waveform")
async def waveform(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = service.subscribe()
    try:
        await websocket.send_text(json.dumps(service.status().as_dict(), ensure_ascii=False))
        initial = service.adaptive_status()
        await websocket.send_text(json.dumps(initial, ensure_ascii=False))
        last_adaptive = (initial["session_id"], initial["sequence"])
        while True:
            message = await queue.get()
            # Waveforms may displace control messages in the bounded display queue.
            # Always deliver the latest changed adaptive state independently.
            latest = service.adaptive_status()
            key = (latest["session_id"], latest["sequence"])
            if key != last_adaptive:
                await websocket.send_text(json.dumps(latest, ensure_ascii=False))
                last_adaptive = key
            if message.get("type") != "adaptive_music":
                await websocket.send_text(json.dumps(message, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(queue)
