"""EEG acquisition, local music, and automatic arrangement-plan events.

Inference runs on an independent bounded worker. Adaptive events describe
planned arrangements, not actual audio playback. BrainFlow is imported lazily.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

from adaptive_web import AdaptiveWebService
from display_filter import DisplayFilter
from powerline_filter import PowerlineNoiseFilter
from channel_mapping import CAP_ORDER
from ace_step import STYLES as ACE_STYLES, automatic as ace_automatic, router as ace_router
from babyslakh import StemTrackId, get_track as get_stem_track, router as stem_music_router
from music_library import router as music_router
from music_choices import router as music_choices_router, candidates, uploaded
from music_workbench import router as music_workbench_router

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


class StartRequest(BaseModel):
    mode: str = Field(default="demo", pattern="^(demo|brainflow)$")
    demo_profile: Literal['model', 'showcase'] = 'model'
    ip_address: str = "192.168.4.1"
    ip_port: int = Field(default=12345, ge=1, le=65535)
    gain: Literal[1, 2, 4, 6, 8, 12, 24] = 24
    music_style: Literal['all', 'ambient', 'piano', 'nature', 'strings', 'electronic'] = 'all'
    music_source: Literal['stems', 'upload', 'ace'] = 'stems'
    uploaded_track_id: str | None = Field(default=None, pattern=r'^user_[a-f0-9]{32}$')
    stem_track_id: StemTrackId | None = None
    sample_rate_hz: Literal[250, 500, 1000] = 250

    @model_validator(mode='after')
    def exclusive_music_source(self):
        if self.demo_profile == 'showcase' and (self.mode != 'demo' or self.sample_rate_hz != 250):
            raise ValueError('showcase requires demo mode and 250 Hz synthetic samples')
        if self.uploaded_track_id is not None and self.stem_track_id is not None:
            raise ValueError('uploaded_track_id and stem_track_id are mutually exclusive')
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
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._adaptive = AdaptiveWebService(self._publish)
        self._adaptive_generation = 0
        self._status = AcquisitionStatus(
            connected=False, streaming=False, mode="demo", sample_rate_hz=self._sample_rate_hz,
            channels=CHANNEL_NAMES, samples_emitted=0, error=None,
        )

    def status(self) -> AcquisitionStatus:
        with self._lock:
            return self._status

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
                return self._status
            self._sample_rate_hz = request.sample_rate_hz
            self._channels = CAP_CHANNEL_NAMES if request.mode == "brainflow" else CHANNEL_NAMES
            self._display_filter = DisplayFilter(self._sample_rate_hz, len(self._channels))
            self._powerline_filter = PowerlineNoiseFilter(self._sample_rate_hz, len(self._channels))
            self._stop_event.clear()
            self._status = AcquisitionStatus(
                connected=request.mode == "demo", streaming=True, mode=request.mode,
                sample_rate_hz=self._sample_rate_hz, channels=self._channels,
                samples_emitted=0, error=None,
            )
            self._adaptive_generation = self._adaptive.start(request.mode, self._sample_rate_hz, self._channels, request.music_style, request.uploaded_track_id, stem_track_id=request.stem_track_id, demo_profile=request.demo_profile)
            if request.music_source == 'ace':
                ace_automatic.start(self._adaptive_generation, request.music_style)
            else:
                ace_automatic.stop()
            self._thread = threading.Thread(target=self._run, args=(request, self._adaptive_generation), name="eeg-acquisition", daemon=True)
            self._thread.start()
            return self._status

    def stop(self) -> AcquisitionStatus:
        self._stop_event.set()
        ace_automatic.stop()
        self._adaptive.stop(self._adaptive_generation)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
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
            ace_automatic.consider(message)
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
        try:
            if request.mode == "brainflow":
                self._run_brainflow(request)
            else:
                self._run_demo(request)
        except Exception:
            self._adaptive.stop(generation, failed=True)
            with self._lock:
                self._status = AcquisitionStatus(
                    connected=False, streaming=False, mode=request.mode,
                    sample_rate_hz=self._sample_rate_hz, channels=self._channels,
                    samples_emitted=self._status.samples_emitted,
                    error="采集失败。请检查设备连接、采样配置及采集依赖后重试。",
                )
            self._publish_status()
        finally:
            self._adaptive.stop(generation, failed=not self._stop_event.is_set())
            self._release_board()
            with self._lock:
                if self._status.streaming:
                    self._status = AcquisitionStatus(
                        connected=False, streaming=False, mode=self._status.mode,
                        sample_rate_hz=self._sample_rate_hz, channels=self._channels,
                        samples_emitted=self._status.samples_emitted, error=self._status.error,
                    )
            self._publish_status()

    def _run_demo(self, request: StartRequest | None = None) -> None:
        from demo_showcase import showcase_waveform

        showcase = request is not None and request.demo_profile == 'showcase'
        chunk_samples = self._sample_rate_hz // 10
        rng = np.random.default_rng(42)
        phase = np.arange(len(CHANNEL_NAMES), dtype=float) * 0.31
        sample_index = 0
        while not self._stop_event.is_set():
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
        try:
            from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
        except ImportError as exc:
            raise RuntimeError("brainflow is required for brainflow mode; install the web/hardware dependencies") from exc
        params = BrainFlowInputParams()
        params.ip_address = request.ip_address
        params.ip_port = request.ip_port
        params.timeout = 3
        board = BoardShim(BoardIds.CYTON_DAISY_WIFI_BOARD.value, params)
        self._board = board
        board.prepare_session()
        board.config_board({250: "~6", 500: "~5", 1000: "~4"}[request.sample_rate_hz])
        board.config_board(self._channel_config(request.gain))
        board.start_stream()
        board.get_board_data()
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
            data = board.get_board_data()
            if data.shape[1] == 0:
                if time.monotonic() - last_received > 10.0:
                    raise RuntimeError("连续 10 秒未收到脑电数据。请关闭其他采集软件，检查脑电帽 Wi-Fi、设备电源及网络连接后重试。")
                self._stop_event.wait(0.01)
                continue
            last_received = time.monotonic()
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
        self._adaptive.submit(samples_uv, start_sample, self._sample_rate_hz,
                              self._adaptive_generation, timestamps_s, package_ids)
        clean = self._display_filter.process(samples_uv)
        self._publish({
            "type": "samples", "timestamp_s": start_sample / self._sample_rate_hz,
            "sample_rate_hz": self._sample_rate_hz, "channels": list(self._channels),
            "samples_uv": np.asarray(clean, dtype=float).round(4).tolist(),
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
        with contextlib.suppress(Exception):
            board.stop_stream()
        with contextlib.suppress(Exception):
            board.release_session()


service = AcquisitionService()
app = FastAPI(title="Terry EEG and Offline Music API", version="0.2.0")
app.include_router(music_choices_router)
app.include_router(music_router)
app.include_router(music_workbench_router)
app.include_router(stem_music_router)
app.include_router(ace_router)
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
    return {"status": "ok"}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return service.status().as_dict()


@app.get("/api/adaptive/status")
async def adaptive_status() -> dict[str, Any]:
    return service._adaptive.status()


@app.post("/api/acquisition/start")
async def start(request: StartRequest) -> dict[str, Any]:
    if request.uploaded_track_id and uploaded(request.uploaded_track_id) is None:
        raise HTTPException(422, '上传音频不存在，请重新上传或选择本地风格')
    if request.stem_track_id and get_stem_track(request.stem_track_id) is None:
        raise HTTPException(422, 'Selected BabySlakh track is unavailable')
    if request.music_source != 'ace' and not request.uploaded_track_id and not request.stem_track_id and request.music_style != 'all' and not candidates(request.music_style):
        raise HTTPException(422, '该风格暂无可播放素材，请先导入并标注风格')
    return service.start(request).as_dict()


@app.post("/api/acquisition/stop")
async def stop() -> dict[str, Any]:
    return service.stop().as_dict()


@app.websocket("/ws/waveform")
async def waveform(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = service.subscribe()
    try:
        await websocket.send_text(json.dumps(service.status().as_dict(), ensure_ascii=False))
        initial = service._adaptive.status()
        await websocket.send_text(json.dumps(initial, ensure_ascii=False))
        last_adaptive = (initial["session_id"], initial["sequence"])
        while True:
            message = await queue.get()
            # Waveforms may displace control messages in the bounded display queue.
            # Always deliver the latest changed adaptive state independently.
            latest = service._adaptive.status()
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
