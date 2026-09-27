"""Bounded raw-EEG adapter producing arrangement plans, never audio playback.

Hardware channel order requires TERRY_EEG_CHANNEL_MAP_CONFIRMED=1 after the
operator verifies CH0–CH15 against config.hardware.yaml. This is an explicit
operator assertion, not automatic validation of electrode placement.
"""
from __future__ import annotations

import copy
import math
import logging
import os
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Literal
from types import SimpleNamespace

import numpy as np

from babyslakh import StemTrackId, project_stem_mix

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("uvicorn.error")


@dataclass
class _Session:
    generation: int
    source: str
    rate: int
    channels: tuple[str, ...]
    music_style: str = 'all'
    uploaded_track_id: str | None = None
    stem_track_id: StemTrackId | None = None
    demo_profile: Literal['model', 'showcase'] = 'model'
    chunks: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=32))
    cancelled: threading.Event = field(default_factory=threading.Event)
    started_at: float = field(default_factory=time.monotonic)
    last_received: float | None = None


class AdaptiveWebService:
    """One daemon worker; no inference, model IO or joins on acquisition thread."""

    def __init__(self, publish: Callable[[dict[str, Any]], None]) -> None:
        self._publish = publish
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._session: _Session | None = None
        self._generation = 0
        self._sequence = 0
        self._last = self._empty_event(0, "DEMO")

    @staticmethod
    def _empty_event(generation: int, source: str) -> dict[str, Any]:
        return {
            "type": "adaptive_music", "schema_version": "1.0",
            "source": source, "status": "stopped", "reason": "acquisition_stopped",
            "session_id": generation, "generation": generation, "sequence": 0,
            "timestamp_s": 0.0, "emitted_at_s": time.time(),
            "planned_only": True, "playback_started": False,
            "playback_mode": "silent", "inference_hold_reason": None,
            "state": None, "probabilities": None, "signal_quality": None,
            "interpretable_features": None, "channel_repair": None, "inference_mode": "standard",
            "current_music_state": None, "target_music_state": None,
            "notes": [], "gains": None, "waveform": None, "variation": None,
            "selected_track": None, "track_status": "not_selected",
            "bpm": None, "phrase_beats": None, "phrase_index": None, "seed": None,
            "plan_updated": False,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._last)

    def start(self, mode: str, rate: int, channels: tuple[str, ...], music_style: str = 'all', uploaded_track_id: str | None = None, stem_track_id: StemTrackId | None = None, *, demo_profile: Literal['model', 'showcase'] = 'model') -> int:
        if demo_profile not in ('model', 'showcase'):
            raise ValueError('Unknown demo profile')
        if demo_profile == 'showcase' and (mode != 'demo' or rate != 250):
            raise ValueError('showcase requires demo mode and 250 Hz synthetic samples')
        with self._lock:
            if self._session:
                self._session.cancelled.set()
            self._generation += 1
            ctx = _Session(self._generation, "LIVE" if mode == "brainflow" else "DEMO", rate, channels, music_style, uploaded_track_id, stem_track_id, demo_profile=demo_profile)
            self._session = ctx
            self._last = self._empty_event(ctx.generation, ctx.source)
            self._emit(ctx, status="waiting", reason="initializing_inference")
            if rate != 250:
                self._fail(ctx, "blocked", "inference_requires_250_hz_no_resampling")
            else:
                if self._thread is None or not self._thread.is_alive():
                    self._thread = threading.Thread(target=self._worker, name="adaptive-planner", daemon=True)
                    self._thread.start()
                self._wake.set()
            return ctx.generation

    def stop(self, generation: int | None = None, *, failed: bool = False) -> None:
        with self._lock:
            ctx = self._session
            if ctx is None or (generation is not None and ctx.generation != generation):
                return
            # Keep a diagnosed failure visible when acquisition exits naturally.
            if failed:
                if not ctx.cancelled.is_set():
                    self._fail(ctx, "error", "acquisition_failed")
                return
            if self._last["status"] == "stopped":
                return
            self._emit(ctx, terminal=True, status="stopped", reason="acquisition_stopped", notes=[], plan_updated=False)
            ctx.cancelled.set()
            self._wake.set()

    def _emit(self, ctx: _Session, *, terminal: bool = False, **fields: Any) -> None:
        with self._lock:
            if ctx is not self._session or (ctx.cancelled.is_set() and not terminal):
                return
            previous_status = (self._last.get("status"), self._last.get("reason"))
            self._sequence += 1
            self._last = {**self._last, "plan_updated": False, **fields,
                          "sequence": self._sequence, "emitted_at_s": time.time()}
            if ctx.stem_track_id:
                self._last['stem_mix'] = project_stem_mix(ctx.stem_track_id, self._last)
            if previous_status != (self._last["status"], self._last["reason"]):
                logger.info("[adaptive] session=%s source=%s status=%s reason=%s eeg_seconds=%.1f",
                            ctx.generation, ctx.source, self._last["status"], self._last["reason"],
                            self._last["timestamp_s"])
            self._publish(copy.deepcopy(self._last))

    def _fail(self, ctx: _Session, status: str, reason: str) -> None:
        with self._lock:
            self._emit(ctx, status=status, reason=reason, notes=[], plan_updated=False,
                       playback_mode="silent", inference_hold_reason=None, modulation=None,
                       state=None, probabilities=None, signal_quality=None)
            ctx.cancelled.set()

    def submit(self, samples_uv: np.ndarray, start_sample: int, rate: int,
               generation: int, timestamps_s: np.ndarray | None = None,
               package_ids: np.ndarray | None = None) -> None:
        with self._lock:
            ctx = self._session
            if ctx is None or ctx.generation != generation or ctx.cancelled.is_set():
                return
            # Bound both queue count and individual allocation, even for board bursts.
            if samples_uv.ndim != 2 or not 0 < samples_uv.shape[1] <= 2500:
                self._fail(ctx, "blocked", "invalid_or_oversized_chunk_restart_required")
                return
            received = time.monotonic()
            if ctx.last_received is None and received - ctx.started_at > 30.0:
                self._fail(ctx, "blocked", "first_sample_timeout_restart_required")
                return
            if ctx.last_received is not None and received - ctx.last_received > 2.0:
                self._fail(ctx, "frozen", "acquisition_gap_restart_required")
                return
            ctx.last_received = received
            try:
                ctx.chunks.put_nowait((np.array(samples_uv, dtype=float, copy=True), start_sample, rate,
                                       None if timestamps_s is None else np.array(timestamps_s, dtype=float, copy=True), received,
                                       None if package_ids is None else np.array(package_ids, dtype=float, copy=True)))
            except queue.Full:
                self._fail(ctx, "blocked", "inference_queue_overflow_restart_required")

    @staticmethod
    def _track(state: str, ctx: _Session | None = None) -> tuple[dict[str, str] | None, str]:
        if ctx and ctx.stem_track_id:
            from babyslakh import get_track
            track = get_track(ctx.stem_track_id)
            return ({'id': track['id'], 'title': track['title']}, 'available') if track else (None, 'stem_track_missing')

        from music_library import _read_manifest, _audio_path

        if ctx and ctx.uploaded_track_id:
            from music_choices import uploaded
            track = uploaded(ctx.uploaded_track_id)
            return ({"id": track.id, "url": f"/api/music/{track.id}/audio", "title": track.title}, "available") if track else (None, "uploaded_track_missing")
        tracks, status = _read_manifest()
        if ctx and ctx.music_style != 'all':
            tracks = [t for t in tracks if ctx.music_style in t.styles]
        if status != "ready":
            return None, "catalog_unavailable"
        # Only existing explicit purpose classifications; never infer from titles.
        patterns = {"M1": r"^L1\s*/\s*Pad\b", "M2": r"^M2(?:\s|$)", "M3": r"^M3(?:\s|$)"}
        for track in sorted(tracks, key=lambda item: item.id):
            if re.search(patterns[state], track.purpose, re.IGNORECASE) and _audio_path(track) is not None:
                return {"id": track.id, "url": f"/api/music/{track.id}/audio", "title": track.title}, "available"
        if ctx and ctx.music_style != 'all':
            for track in sorted(tracks, key=lambda item: item.id):
                if _audio_path(track) is not None:
                    return {"id": track.id, "url": f"/api/music/{track.id}/audio", "title": track.title}, "available"
        return None, "no_available_track_for_state"

    def _conservative(self, ctx: _Session, reason: str, **fields: Any) -> None:
        """Audible arrangement without claiming a valid sleep classification."""
        from anphy_sleep.music_engine.midi import generate_midi_plan

        repair = fields.get("channel_repair") or {}
        if not repair.get("valid_channels"):
            self._emit(ctx, **fields, status="frozen", reason="no_valid_electrodes",
                       playback_mode="silent", notes=[], selected_track=None)
            return
        track, track_status = self._track("M1", ctx)
        # Keep the already selected local bed during electrode degradation instead
        # of switching to a different song just because classification is missing.
        with self._lock:
            if self._last.get("selected_track") and self._last.get("track_status") == "available":
                track = copy.deepcopy(self._last["selected_track"])
                track_status = "available"
        notes = [asdict(note) for note in generate_midi_plan("M2", seed=42, variation="extended")
                 if note.voice == "melody"][:4]
        for index, note in enumerate(notes):
            note["velocity"] = min(note["velocity"], 35)
            note["start_beat"] = index * 4.0
            note["duration_beats"] = 3.0
        self._emit(ctx, **fields, status="ready" if track else "waiting",
                   reason="conservative_audio_without_classification" if track else "conservative_track_missing",
                   inference_hold_reason=reason, playback_mode="conservative", modulation=None,
                   current_music_state="M2", target_music_state="M2",
                   notes=notes, gains={"master": .06, "pad": .3, "melody": .08, "bass": 0, "texture": 0},
                   waveform={"master_gain": .4, "brightness": .15, "reverb_send": 0, "stereo_width": .2},
                   variation="extended", selected_track=track, track_status=track_status,
                   bpm=60, phrase_beats=16, seed=42, plan_updated=True)

    def _worker(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                ctx = self._session
            if ctx is None or ctx.cancelled.is_set():
                continue
            try:
                self._process(ctx)
            except Exception:
                logger.exception("[adaptive] inference worker failed session=%s", ctx.generation)
                # Detailed traceback stays in the local backend terminal, not the API.
                self._fail(ctx, "error", "adaptive_inference_failed_restart_required")

    def _process_showcase(self, ctx: _Session) -> None:
        """Consume validated synthetic samples, without loading any ML artifacts.

        The probabilities are presentation inputs, not inferred sleep state.
        Signal quality describes sample validity only, never electrode quality.
        """
        from demo_showcase import MUSIC_STATES, PROBABILITIES, showcase_stage
        from eeg_music_modulation import EegMusicModulator

        if ctx.source != 'DEMO' or ctx.rate != 250:
            self._fail(ctx, 'blocked', 'showcase_requires_demo_250_hz')
            return
        expected_sample, next_emit_sample = 0, 750
        previous_timestamp = None
        self._emit(ctx, status='waiting', reason='collecting_scripted_demo_samples',
                   inference_mode='demo_scripted', demo_scripted=True,
                   probability_origin='scripted_not_model',
                   signal_quality_scope='synthetic_sample_validity_only')
        while not ctx.cancelled.is_set():
            try:
                samples, start, rate, timestamps, received, _ = ctx.chunks.get(timeout=.25)
            except queue.Empty:
                with self._lock:
                    now = time.monotonic()
                    if ctx.last_received is None:
                        if now - ctx.started_at > 30.0:
                            self._fail(ctx, 'blocked', 'first_sample_timeout_restart_required')
                    elif now - ctx.last_received > 2.0:
                        self._fail(ctx, 'frozen', 'acquisition_stale_restart_required')
                continue
            if ctx.cancelled.is_set():
                return
            if time.monotonic() - received > 3.0:
                self._fail(ctx, 'blocked', 'inference_backlog_restart_required')
                return
            if rate != 250 or start != expected_sample:
                self._fail(ctx, 'blocked', 'sample_discontinuity_restart_required')
                return
            if samples.ndim != 2 or not 0 < samples.shape[1] <= 2500:
                self._fail(ctx, 'blocked', 'invalid_or_oversized_chunk_restart_required')
                return
            if samples.shape[0] != len(ctx.channels):
                self._fail(ctx, 'blocked', 'invalid_channel_count_restart_required')
                return
            if not np.isfinite(samples).all():
                self._fail(ctx, 'blocked', 'nonfinite_synthetic_samples_restart_required')
                return
            if timestamps is not None:
                if timestamps.shape != (samples.shape[1],) or not np.isfinite(timestamps).all():
                    self._fail(ctx, 'blocked', 'invalid_hardware_timestamps_restart_required')
                    return
                chain = timestamps if previous_timestamp is None else np.r_[previous_timestamp, timestamps]
                intervals = np.diff(chain)
                if np.any(intervals < 0) or np.any(intervals > 2.0):
                    self._fail(ctx, 'blocked', 'hardware_timestamp_discontinuity_restart_required')
                    return
                previous_timestamp = float(timestamps[-1])
            expected_sample += samples.shape[1]
            while expected_sample >= next_emit_sample and not ctx.cancelled.is_set():
                elapsed = next_emit_sample / 250
                stage = showcase_stage(elapsed)
                music_state = MUSIC_STATES[stage]
                probabilities = dict(PROBABILITIES[stage])
                # Each scripted step sets the mapping target deterministically;
                # never pretend a baseline or smoothed model result exists.
                scripted_state = SimpleNamespace(window_end_s=elapsed,
                    aasm_state_probabilities=probabilities, interpretable_features={})
                notes, gains, waveform, modulation = EegMusicModulator().apply(scripted_state, music_state, 42)
                modulation.update(demo_scripted=True, probability_origin='scripted_not_model',
                                  transition_source='deterministic_demo_stage', smoothing_seconds=0)
                track, track_status = self._track(music_state, ctx)
                now = time.monotonic()
                if now - received > 3.0 or (ctx.last_received is not None and now - ctx.last_received > 2.0):
                    self._fail(ctx, 'frozen', 'inference_result_stale_restart_required')
                    return
                self._emit(ctx, status='ready', reason='scripted_demo_not_model_inference',
                    timestamp_s=elapsed, demo_elapsed_s=elapsed, demo_stage=stage,
                    playback_mode='demo_scripted', inference_mode='demo_scripted',
                    demo_scripted=True, probability_origin='scripted_not_model',
                    inference_hold_reason=None,
                    state={'status': 'demo_scripted', 'baseline_ready': False,
                           'window_end_s': elapsed, 'n2_within_5m_probability': None},
                    probabilities=probabilities, signal_quality=1.0,
                    signal_quality_scope='synthetic_sample_validity_only',
                    interpretable_features=None, channel_repair=None,
                    current_music_state=music_state, target_music_state=music_state,
                    notes=notes, gains=gains, waveform=waveform, modulation=modulation,
                    variation=f"eeg-density-{modulation['density_band']}",
                    selected_track=track, track_status=track_status,
                    bpm=60, phrase_beats=16, phrase_index=int(elapsed // 16), seed=42,
                    plan_updated=True)
                next_emit_sample += 750

    def _process(self, ctx: _Session) -> None:
        from anphy_sleep.config import load_config, load_local_env

        if ctx.source == "LIVE" and len(ctx.channels) != 16:
            self._fail(ctx, "blocked", "live_inference_requires_16_channels")
            return
        load_local_env(ROOT)
        experimental_map = ctx.source == "LIVE" and os.getenv("TERRY_EEG_EXPERIMENTAL_16CH_MAPPING") == "1"
        config, _ = load_config(ROOT / ("config.yaml" if experimental_map else "config.hardware.yaml"))
        if experimental_map:
            from channel_mapping import CAP_ORDER, MODEL_ORDER
            if ctx.channels != CAP_ORDER or tuple(config["channels"]["target"]) != MODEL_ORDER:
                self._fail(ctx, "blocked", "experimental_channel_mapping_contract_mismatch")
                return
        logger.info("[adaptive] preflight session=%s source=%s rate=%s channel_map_confirmed=%s expected_order=%s",
                    ctx.generation, ctx.source, ctx.rate,
                    os.getenv("TERRY_EEG_CHANNEL_MAP_CONFIRMED") == "1", config["channels"]["target"])
        if not experimental_map and tuple(config["channels"]["target"]) != ctx.channels:
            self._fail(ctx, "blocked", "configured_channel_order_mismatch")
            return
        if ctx.source == "LIVE" and os.getenv("TERRY_EEG_CHANNEL_MAP_CONFIRMED") != "1":
            logger.warning("[adaptive] Classification has NOT started: verify physical CH0-CH15 order against config.hardware.yaml, then set TERRY_EEG_CHANNEL_MAP_CONFIRMED=1 in backEnd/.env and restart. Waveform acquisition is independent.")
            self._fail(ctx, "blocked", "physical_channel_map_unconfirmed_set_TERRY_EEG_CHANNEL_MAP_CONFIRMED_after_verification")
            return
        if float(config["signal"]["target_sfreq_hz"]) != 250:
            self._fail(ctx, "blocked", "inference_requires_250_hz_no_resampling")
            return
        if ctx.demo_profile == 'showcase' and ctx.source != 'DEMO':
            self._fail(ctx, 'blocked', 'showcase_requires_demo_source')
            return
        if ctx.demo_profile == 'showcase':
            self._process_showcase(ctx)
            return
        # Same model artifacts and config-root resolution as CLI stream-demo.
        model_dir = Path(config["data"]["results_dir"]) / "models"
        prediction = model_dir / "future_n2_logistic_continuous.joblib"
        state_model = model_dir / "sleep_state_logistic_30s.joblib"
        logger.info("[adaptive] model files prediction_exists=%s state_exists=%s", prediction.is_file(), state_model.is_file())
        if not prediction.is_file() or not state_model.is_file():
            self._fail(ctx, "blocked", "configured_realtime_models_missing")
            return
        from anphy_sleep.contracts import EegChunk
        from anphy_sleep.streaming import RealtimeSession, SignalPipeline, OnlineFeatureState
        from anphy_sleep.music_engine.scheduler import MusicScheduler
        from anphy_sleep.music_engine.midi import generate_midi_plan

        from channel_repair import repair_channels
        from eeg_music_modulation import EegMusicModulator
        modulator = EegMusicModulator()
        # Web-only experimental missing-channel policy; training/CLI config stays unchanged.
        config["quality"]["minimum_clean_channel_fraction"] = .5
        session = RealtimeSession(config, prediction, state_model, session_id=str(ctx.generation))
        logger.info("[adaptive] models loaded session=%s baseline_seconds=%s", ctx.generation, config.get("realtime", {}).get("baseline_seconds"))
        last_progress_s = -30.0
        music = config.get("music", {})
        policy = music.get("policy", {})
        scheduler = MusicScheduler(
            bpm=float(music.get("bpm", 60)), phrase_beats=int(music.get("phrase_beats", 16)),
            confirmations_required=int(policy.get("confirmations_required", 2)),
            minimum_dwell_seconds=float(policy.get("minimum_mode_dwell_seconds", 60)),
            smoothing_seconds=float(policy.get("smoothing_seconds", 30)),
            minimum_signal_quality=.5,
        )
        seed = int(config.get("project", {}).get("random_seed", 42))
        expected_sample = 0
        repaired_sample = 0
        repair_buffer = np.empty((len(ctx.channels), 0))
        previous_repair = None
        recovery_required = False
        from classification_gate import ClassificationGate
        classification_gate = ClassificationGate()
        inference_origin_s = 0.0
        previous_timestamp: float | None = None
        previous_package: int | None = None
        last_plan: tuple[str, str] | None = None
        planned_notes: list[dict[str, Any]] = []
        self._emit(ctx, status="waiting", reason="collecting_baseline_and_state_windows")
        while not ctx.cancelled.is_set():
            try:
                samples, start, rate, timestamps, received, package_ids = ctx.chunks.get(timeout=.25)
            except queue.Empty:
                with self._lock:
                    now = time.monotonic()
                    if ctx.last_received is None:
                        if now - ctx.started_at > 30.0:
                            self._fail(ctx, "blocked", "first_sample_timeout_restart_required")
                    elif now - ctx.last_received > 2.0:
                        self._fail(ctx, "frozen", "acquisition_stale_restart_required")
                continue
            if ctx.cancelled.is_set():
                return
            if time.monotonic() - received > 3.0:
                self._fail(ctx, "blocked", "inference_backlog_restart_required")
                return
            if rate != 250 or start != expected_sample:
                self._fail(ctx, "blocked", "sample_discontinuity_restart_required")
                return
            if samples.shape[0] != len(ctx.channels):
                self._fail(ctx, "blocked", "invalid_channel_count_restart_required")
                return
            if ctx.source == "LIVE" and timestamps is None:
                self._fail(ctx, "blocked", "hardware_timestamps_missing")
                return
            if timestamps is not None:
                if timestamps.shape != (samples.shape[1],) or not np.isfinite(timestamps).all():
                    self._fail(ctx, "blocked", "invalid_hardware_timestamps_restart_required")
                    return
                times = timestamps if previous_timestamp is None else np.r_[previous_timestamp, timestamps]
                intervals = np.diff(times)
                # Cyton Daisy WiFi stamps host receipt time, not ADC sample time.
                # Network batching can repeat timestamps or exceed a 4ms interval.
                # Keep large gaps/clock reversal blocked; use device counters below
                # for sample continuity rather than requiring uniform receipt times.
                if np.any(intervals < 0) or np.any(intervals > 2.0):
                    logger.warning("[adaptive] receipt timestamp gap session=%s min_dt=%s max_dt=%s",
                                   ctx.generation, float(intervals.min()), float(intervals.max()))
                    self._fail(ctx, "blocked", "hardware_timestamp_discontinuity_restart_required")
                    return
                previous_timestamp = float(timestamps[-1])
            if ctx.source == "LIVE":
                if (package_ids is None or package_ids.shape != (samples.shape[1],)
                        or not np.isfinite(package_ids).all()
                        or np.any(package_ids != np.floor(package_ids))
                        or np.any(package_ids < 0) or np.any(package_ids > 255)):
                    self._fail(ctx, "blocked", "invalid_hardware_package_counters_restart_required")
                    return
                # Daisy WiFi combines two 8-channel packets with the same ID into
                # one 16-channel sample; output IDs advance by one modulo 256.
                counters = package_ids.astype(np.int64)
                chain = counters if previous_package is None else np.r_[previous_package, counters]
                steps = np.diff(chain) % 256
                if np.any(steps != 1):
                    index = int(np.flatnonzero(steps != 1)[0])
                    logger.warning("[adaptive] device counter discontinuity session=%s sample=%s previous=%s next=%s step=%s",
                                   ctx.generation, start, chain[index], chain[index + 1], steps[index])
                    self._fail(ctx, "blocked", "hardware_package_discontinuity_restart_required")
                    return
                previous_package = int(counters[-1])
            if expected_sample == 0:
                logger.info("[adaptive] first valid chunk session=%s samples=%s timestamps=%s device_counters=%s",
                            ctx.generation, samples.shape[1], timestamps is not None, package_ids is not None)
            expected_sample += samples.shape[1]
            repair_buffer = np.concatenate([repair_buffer, samples], axis=1)
            if repair_buffer.shape[1] < 1500:
                continue
            repaired, repair = repair_channels(repair_buffer, ctx.channels,
                                               float(config["signal"]["amplitude_reject_uv"]),
                                               filter_sos=session.signal.filter_sos,
                                               sample_rate_hz=rate)
            repair["window_end_s"] = expected_sample / rate
            if repaired is None:
                classification_gate.reset()
                # A poor electrode window is recoverable, not a cancelled device
                # session. Discard it and keep checking new raw data every batch.
                logger.info("[adaptive] electrode QC valid=%s/%s rejected=%s",
                            len(repair["valid_channels"]), len(ctx.channels),
                            {item["channel"]: item["reason"] for item in repair["channels"] if not item["valid"]})
                self._conservative(ctx, "insufficient_valid_channels_rechecking",
                           timestamp_s=expected_sample / rate, channel_repair=repair,
                           state=None, probabilities=None, signal_quality=repair["valid_fraction"],
                           interpretable_features=None, inference_mode="unavailable")
                recovery_required = True
                repair_buffer = np.empty((len(ctx.channels), 0))
                continue
            if recovery_required:
                # Never splice valid samples across a rejected gap or reuse a
                # baseline from before it. Retain loaded model weights only.
                session.signal = SignalPipeline(config)
                modulator = EegMusicModulator()
                session.feature_state = OnlineFeatureState(config)
                session.state_feature_history.clear()
                scheduler = MusicScheduler(
                    bpm=float(music.get("bpm", 60)), phrase_beats=int(music.get("phrase_beats", 16)),
                    confirmations_required=int(policy.get("confirmations_required", 2)),
                    minimum_dwell_seconds=float(policy.get("minimum_mode_dwell_seconds", 60)),
                    smoothing_seconds=float(policy.get("smoothing_seconds", 30)), minimum_signal_quality=.5)
                inference_origin_s = (expected_sample - repaired.shape[1]) / rate
                repaired_sample = 0
                previous_repair = None
                last_plan = None
                last_progress_s = -30.0
                recovery_required = False
                logger.info("[adaptive] electrode QC recovered; rebuilding baseline from eeg_seconds=%.1f", inference_origin_s)
            # Overlapping model windows can include samples from the previous
            # repair batch; report the conservative union of missing channels.
            missing = set(repair["imputed_channels"])
            if previous_repair is not None:
                missing.update(previous_repair["imputed_channels"])
            reported_repair = {**repair, "imputed_channels": sorted(missing),
                               "valid_channels": [c for c in ctx.channels if c not in missing],
                               "valid_fraction": (len(ctx.channels) - len(missing)) / len(ctx.channels)}
            if previous_repair is None or repair["imputed_channels"] != previous_repair["imputed_channels"]:
                logger.info("[adaptive] channel mean repair valid=%s/%s imputed=%s experimental=true",
                            len(repair["valid_channels"]), len(ctx.channels), repair["imputed_channels"])
            previous_repair = repair
            config.setdefault("realtime", {})["mean_imputed_channels"] = sorted(missing)
            reported_repair["global_mean_regions"] = [
                name for name, channels in config["channels"]["regions"].items()
                if all(channel in missing for channel in channels)
            ]
            if experimental_map:
                from channel_mapping import ESTIMATED_CHANNELS, MODEL_ORDER, map_cap_to_model
                repaired = map_cap_to_model(repaired, ctx.channels)
                config["realtime"]["mean_imputed_channels"] = sorted(set(missing) | set(ESTIMATED_CHANNELS))
                reported_repair["estimated_channels"] = list(ESTIMATED_CHANNELS)
                reported_repair["mapping"] = "experimental_14_measured_2_interpolated"
            chunk = EegChunk(timestamp_s=repaired_sample / rate, sample_rate_hz=rate,
                             channel_names=MODEL_ORDER if experimental_map else ctx.channels,
                             samples=repaired, unit="uV", session_id=str(ctx.generation))
            repaired_sample += repaired.shape[1]
            repair_buffer = np.empty((len(ctx.channels), 0))
            for output in session.push(chunk):
                if ctx.cancelled.is_set():
                    return
                last_received = ctx.last_received
                if time.monotonic() - received > 3.0 or (last_received is not None and time.monotonic() - last_received > 2.0):
                    self._fail(ctx, "frozen", "inference_result_stale_restart_required")
                    return
                state = replace(output.state, signal_quality=min(output.state.signal_quality, reported_repair["valid_fraction"]))
                if state.window_end_s - last_progress_s >= 30:
                    logger.info("[adaptive] progress session=%s eeg_seconds=%.1f state=%s baseline_ready=%s quality=%s probabilities_available=%s queue=%s",
                                ctx.generation, state.window_end_s, state.status, state.baseline_ready,
                                state.signal_quality, bool(state.aasm_state_probabilities), ctx.chunks.qsize())
                    last_progress_s = state.window_end_s
                probabilities = state.aasm_state_probabilities
                valid_probs = bool(probabilities) and all(
                    key in probabilities for key in ("W", "N1", "N2")
                ) and all(math.isfinite(value) and 0 <= value <= 1 for value in probabilities.values())
                valid_probs = valid_probs and abs(sum(probabilities.values()) - 1) <= .01
                valid_future = state.n2_within_5m_probability is not None and math.isfinite(state.n2_within_5m_probability) and 0 <= state.n2_within_5m_probability <= 1
                valid_quality = math.isfinite(state.signal_quality) and 0 <= state.signal_quality <= 1
                public_state = {"status": state.status, "baseline_ready": state.baseline_ready,
                                "window_end_s": float(state.window_end_s),
                                "n2_within_5m_probability": state.n2_within_5m_probability if valid_future and state.baseline_ready else None}
                interpretable_features = {
                    key: float(value) for key, value in state.interpretable_features.items()
                    if isinstance(value, (int, float)) and math.isfinite(float(value))
                }
                fields = dict(timestamp_s=inference_origin_s + float(state.window_end_s), state=public_state,
                              inference_elapsed_s=float(state.window_end_s),
                              channel_repair=reported_repair,
                              inference_mode="cap_mapping_experimental" if experimental_map else "mean_imputed_experimental" if missing else "standard",
                              probabilities=dict(probabilities) if valid_probs else None,
                              signal_quality=float(state.signal_quality) if valid_quality else None,
                              interpretable_features=interpretable_features)
                hold_status = None
                hold_reason = None
                if state.status == "signal_invalid" or not valid_quality or state.signal_quality < scheduler.minimum_signal_quality:
                    hold_status, hold_reason = "frozen", "invalid_or_low_quality_eeg"
                elif state.status == "warming_up":
                    hold_status, hold_reason = "waiting", "warming_up_inference_features"
                elif probabilities is None:
                    hold_status, hold_reason = "waiting", "collecting_state_probability_windows"
                elif state.status != "ok" or not valid_probs:
                    hold_status, hold_reason = "frozen", "invalid_state_probabilities"
                if hold_status is None and not classification_gate.update(state):
                    hold_status, hold_reason = "waiting", "confirming_state_classification"
                if hold_status is not None:
                    if hold_reason != "confirming_state_classification":
                        classification_gate.reset()
                    # Unready/invalid windows never accumulate confirmations or smoothing history.
                    scheduler.pending_state = None
                    scheduler.pending_count = 0
                    scheduler.history.clear()
                    self._conservative(ctx, hold_reason, **fields)
                    modulator = EegMusicModulator()
                    last_plan = None
                    continue
                decision_state = state if state.baseline_ready and valid_future else replace(
                    state, n2_within_5m_probability=None, interpretable_features={})
                frame = scheduler.update(decision_state)
                key = (frame.music_state.value, frame.motif_variation.value)
                planned_notes, dynamic_gains, dynamic_waveform, modulation = modulator.apply(decision_state, key[0], seed)
                changed = True  # Continuous controls are updated even within the same M state.
                track, track_status = self._track(key[0], ctx)
                self._emit(ctx, **fields, status="ready", reason=frame.reason,
                           playback_mode="adaptive", inference_hold_reason=None,
                           classification_confirmed=True,
                           current_music_state=key[0], target_music_state=frame.target_state.value,
                           notes=planned_notes, gains=dynamic_gains, waveform=dynamic_waveform,
                           modulation=modulation,
                           variation=f"eeg-density-{modulation['density_band']}", selected_track=track, track_status=track_status,
                           bpm=scheduler.bpm, phrase_beats=scheduler.phrase_beats,
                           phrase_index=frame.phrase_index, seed=seed, plan_updated=changed)
                last_plan = key
